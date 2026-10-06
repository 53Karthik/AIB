import math

from .datetime import parse_stamp, day_of, month_of, iso_of, hours_between
from .extracts import text, id_of
from .outcome import OUTCOME, judge, norm
from .workflows import by_policy, latest_before, number


def candidates_before(workflows, when):
    return sum(workflow["created"] <= when for workflow in workflows or [])


def workflow_detail(workflow):
    return {
        "workflowNumber": workflow["number"], "workflowType": workflow["type"],
        "policy": workflow["policy"], "product": workflow["product"],
        "description": workflow["description"], "assignee": workflow["assignee"],
        "assigneeCode": workflow["assigneeCode"], "workflowOpen": workflow["open"],
    }


def workflow_item(ctx, sla, workflow, deadline):
    clock = ctx.cal.clock_start(workflow["created"])
    return {
        "sla": sla, "key": workflow["number"], "month": month_of(workflow["created"]),
        "outcome": judge(workflow["closeDay"], deadline, ctx.as_of_day),
        "startedAt": iso_of(workflow["created"]), "clockStart": clock["day"],
        "beforeCutoff": clock["beforeCutoff"], "deadline": deadline,
        "completedAt": workflow["closeDay"], **workflow_detail(workflow),
    }


def rule23A(ctx):
    types = set(map(norm, ctx.definition("23A")["params"]["workflowTypes"]))
    return {"items": [workflow_item(ctx, "23A", workflow, ctx.cal.cutoff_rule(workflow["created"]))
                      for workflow in ctx.workflows if norm(workflow["type"]) in types], "outOfScope": 0}


def build_mapping(rows):
    mapping = {}
    for row in rows:
        key = f'{norm(row.get("product"))}|{norm(row.get("transaction"))}'
        code = str(row.get("code") or "").strip().upper()
        if not code:
            continue
        if key in mapping and mapping[key]["code"] != code:
            raise ValueError(f'Mapping for 23B gives {row.get("product")} / {row.get("transaction")} two codes: {mapping[key]["code"]} and {code}')
        mapping.setdefault(key, {"code": code, "dependency": row.get("dependency")})
    return mapping


def records_of(ctx, kind):
    return [record for extract in ctx.extracts if extract["kind"] == kind for record in extract["records"]]


def rule23B_EBQ(ctx):
    nul_code = ctx.definition("23B_NUL")["params"]["mappingCode"]
    ul_code = ctx.definition("23B_UL_S1")["params"]["mappingCode"]
    items, unmapped = [], []
    for record in records_of(ctx, "ebq"):
        product, transaction = text(record, "product"), text(record, "transaction type")
        mapped = ctx.mapping.get(f"{norm(product)}|{norm(transaction)}")
        code = mapped["code"] if mapped else None
        sla = "23B_NUL" if code == nul_code else "23B_UL_S1" if code == ul_code else None
        start = parse_stamp(record.get("transaction start date"))
        if sla is None:
            unmapped.append({"product": product, "transactionType": transaction, "month": month_of(start)})
            continue
        status = text(record, "status").upper()
        merged = parse_stamp(record.get("transaction merged date"))
        clock = ctx.cal.clock_start(start)
        deadline = ctx.cal.next_day(start) if sla == "23B_NUL" else ctx.cal.same_day(start)
        completed = day_of(merged) if status == "MERGED" else None
        items.append({
            "sla": sla, "key": text(record, "transaction reference"), "sourceRow": record["_row"],
            "month": month_of(start), "outcome": OUTCOME["EXCLUDED"] if status == "REJECTED" else judge(completed, deadline, ctx.as_of_day),
            "startedAt": day_of(start), "clockStart": clock["day"], "beforeCutoff": None,
            "deadline": deadline, "completedAt": completed,
            "businessDaysTaken": ctx.cal.business_days_between(clock["day"], completed) if completed else None,
            "policy": id_of(record, "policy number"), "product": product, "transactionType": transaction,
            "transactionReference": text(record, "transaction reference"), "status": status,
            "dependency": mapped["dependency"], "userId": text(record, "user id"),
        })
    return {"items": items, "outOfScope": len(unmapped), "unmapped": unmapped}


def rule23B_Step2(ctx):
    params = ctx.definition("23B_UL_S2")["params"]
    approvals = by_policy(ctx.workflows, params["workflowType"])
    items = []
    for record in records_of(ctx, "withdrawal"):
        policy = id_of(record, "policy number")
        last = parse_stamp(record.get("date and time of last status"))
        status = text(record, "transaction status")
        amount = number(record.get("transaction amount"))
        base = {
            "sla": "23B_UL_S2", "key": str(record["_row"]), "sourceRow": record["_row"],
            "policy": policy, "product": text(record, "product name"),
            "transactionType": text(record, "transaction type"), "transactionStatus": status,
            "amount": amount if amount and math.isfinite(amount) else None, "lastStatusAt": iso_of(last),
        }
        workflow = latest_before(approvals.get(policy), last)
        if workflow is None:
            items.append({**base, "month": month_of(last), "outcome": OUTCOME["NO_MATCH"]})
            continue
        clock = ctx.cal.clock_start(workflow["created"])
        deadline = ctx.cal.cutoff_rule(workflow["created"])
        completed = day_of(last) if norm(status) == norm(params["completeStatus"]) else None
        items.append({
            **base, "candidateWorkflows": candidates_before(approvals.get(policy), last),
            **workflow_detail(workflow), "product": base["product"], "month": month_of(workflow["created"]),
            "outcome": judge(completed, deadline, ctx.as_of_day), "startedAt": iso_of(workflow["created"]),
            "clockStart": clock["day"], "beforeCutoff": clock["beforeCutoff"], "deadline": deadline,
            "completedAt": completed,
        })
    return {"items": items, "outOfScope": 0}


def rule23B_Step3(ctx):
    want = norm(ctx.definition("23B_UL_S3")["params"]["workflowType"])
    return {"items": [workflow_item(ctx, "23B_UL_S3", workflow, ctx.cal.cutoff_rule(workflow["created"]))
                      for workflow in ctx.workflows if norm(workflow["type"]) == want], "outOfScope": 0}


def rule23C(ctx):
    params = ctx.definition("23C")["params"]
    products = set(map(norm, params["products"]))
    approvals = by_policy(ctx.workflows, params["workflowType"])
    items, out_of_scope = [], 0
    for record in records_of(ctx, "cancellation"):
        product = text(record, "product name")
        if norm(product) not in products:
            out_of_scope += 1
            continue
        policy = id_of(record, "policy number")
        last = parse_stamp(record.get("date and time of last status"))
        base = {"sla": "23C", "key": str(record["_row"]), "sourceRow": record["_row"],
                "policy": policy, "product": product, "cancellationReason": text(record, "cancellation reason"),
                "lastStatusAt": iso_of(last), "completedAt": day_of(last)}
        workflow = latest_before(approvals.get(policy), last)
        if workflow is None:
            items.append({**base, "month": month_of(last), "outcome": OUTCOME["NO_MATCH"]})
            continue
        elapsed = hours_between(workflow["created"], last)
        items.append({
            **base, **workflow_detail(workflow), "product": product,
            "candidateWorkflows": candidates_before(approvals.get(policy), last),
            "month": month_of(workflow["created"]), "outcome": OUTCOME["MET"] if elapsed < params["maxHours"] else OUTCOME["MISSED"],
            "startedAt": iso_of(workflow["created"]), "elapsedHours": math.floor(elapsed * 10000 + 0.5) / 10000,
        })
    return {"items": items, "outOfScope": out_of_scope}


def rule23E(ctx):
    params = ctx.definition("23E")["params"]
    prefix, phrase = norm(params["workflowTypePrefix"]), norm(params["phrase"])
    items, out_of_scope = [], 0
    for workflow in ctx.workflows:
        is_type = norm(workflow["type"]).startswith(prefix)
        has_phrase = phrase in norm(workflow["description"])
        if not is_type or not has_phrase:
            if is_type or has_phrase:
                out_of_scope += 1
            continue
        items.append(workflow_item(ctx, "23E", workflow, ctx.cal.next_day(workflow["created"])))
    return {"items": items, "outOfScope": out_of_scope}


RULES = [rule23A, rule23B_EBQ, rule23B_Step2, rule23B_Step3, rule23C, rule23E]
