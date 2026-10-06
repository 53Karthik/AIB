import re

from .engine.datetime import month_of
from .engine.extracts import text
from .engine.outcome import OUTCOME, norm
from .engine.workflows import by_policy
from .insights import rounded
from .slots import EXTRACT_SLOTS


def plural(count, one, many):
    return f"{count:,} {one if count == 1 else many}"


def summarise(findings):
    return {"total": len(findings), **{severity: sum(finding["severity"] == severity for finding in findings)
                                      for severity in ("red", "amber", "info")}}


def add(findings, kind, severity, title, detail, affected=()):
    findings.append({"id": f"{kind}:{len(findings)}", "affected": list(affected), "type": kind,
                     "severity": severity, "title": title, "detail": detail})


def ordered(findings):
    order = {"red": 0, "amber": 1, "info": 2}
    return sorted(findings, key=lambda finding: order[finding["severity"]])


def set_findings(*, sources, mapping_rows, extracts, schedule):
    findings = []
    labels = {definition["id"]: definition["label"] for definition in schedule["slas"]}
    present = {slot for source in sources for slot in source["covers"]}
    for slot in EXTRACT_SLOTS:
        if slot["id"] not in present:
            add(findings, "missing_extract", "red", f'{slot["label"]} not supplied',
                f'Without it, {", ".join(labels.get(sla, sla) for sla in slot["feeds"])} cannot be fully measured.', slot["feeds"])
    keys = [f'{norm(row["product"])}|{norm(row["transaction"])}' for row in mapping_rows]
    duplicates = len(keys) - len(set(keys))
    odd_codes = sum(bool(row.get("code")) and row["code"].strip() != row["code"].strip().upper() for row in mapping_rows)
    padded = sum(row["transaction"] != row["transaction"].strip() or row["product"] != row["product"].strip() for row in mapping_rows)
    bits = []
    if duplicates:
        bits.append(f"{plural(duplicates, 'pair is', 'pairs are')} listed twice (each is counted once)")
    if odd_codes:
        bits.append(f"{plural(odd_codes, 'code is', 'codes are')} not upper case, e.g. 'Ul' (read as UL)")
    if padded:
        bits.append(f"{plural(padded, 'value has', 'values have')} stray spaces (trimmed before matching)")
    if bits:
        add(findings, "mapping_quirks", "info", "Mapping for 23B normalised on read",
            f"{'; '.join(bits)}. Matching is on Product + Transaction, ignoring case and spacing.", ["23B_NUL", "23B_UL_S1"])
    long_ids = sum(len(re.sub(r"\D", "", text(record, "request id"))) > 15
                   for extract in extracts if extract["kind"] == "withdrawal" for record in extract["records"])
    if long_ids:
        add(findings, "request_id_precision", "info", "WITHDRAWALEXT Request IDs have lost precision",
            f"{plural(long_ids, 'Request ID is', 'Request IDs are')} longer than Excel's 15 significant digits, so their final digits are unreliable. Withdrawals are matched to workflows by policy, never by Request ID.", ["23B_UL_S2"])
    nan_cells = sum(isinstance(value, str) and value.strip().lower() == "nan"
                    for extract in extracts for record in extract["records"] for value in record.values())
    if nan_cells:
        add(findings, "nan_placeholders", "info", f"{plural(nan_cells, 'cell holds', 'cells hold')} the text 'nan'",
            "An export placeholder for an empty value (e.g. 'Approver Role already approved' on withdrawals awaiting authorisation). Treated as blank.")
    return ordered(findings)


def month_findings(*, month, items, results, as_of, as_of_label, unmapped, workflows, schedule, step_two_matched):
    findings = []
    labels = {definition["id"]: definition["label"] for definition in schedule["slas"]}
    population = [item for item in items if item["month"] == month]
    if as_of[:7] == month:
        due = sum(item["outcome"] == OUTCOME["OPEN_DUE"] for item in population)
        extra = f", and {plural(due, 'item is', 'items are')} open but not yet due" if due else ""
        add(findings, "partial_period", "amber", f"Period incomplete — extract taken {as_of_label}",
            f"Activity after the extract date is not included{extra}. Figures for this month will move when a later extract is loaded.")
    rollups = {definition["id"] for definition in schedule["slas"] if definition.get("parts")}
    for result in results:
        if result["id"] in rollups or not result["openPastDeadline"]:
            continue
        completed = f'({rounded(result["rateCompleted"] * 100, 100):.2f}%) ' if result["rateCompleted"] is not None else ""
        with_open = f', which is {rounded(result["rateInclOpen"] * 100, 100):.2f}%' if result["rateInclOpen"] is not None else ""
        add(findings, "open_past_deadline", "red",
            f'{labels.get(result["id"], result["id"])}: {plural(result["openPastDeadline"], "item", "items")} open past deadline',
            f"Still open at the extract date with the deadline already passed. They are outside Rate (Completed) {completed}but count against Rate (incl. Open){with_open}.", [result["id"]])
    no_match = [item for item in population if item["outcome"] == OUTCOME["NO_MATCH"]]
    if no_match:
        policies = ", ".join(item["policy"] for item in no_match[:6]) + (", …" if len(no_match) > 6 else "")
        add(findings, "no_matching_workflow", "amber", f"{plural(len(no_match), 'withdrawal has', 'withdrawals have')} no approval workflow",
            f"No 'Workflow for Withdrawal Approval' exists on the policy before the withdrawal's last status, so Step 2 has no clock start. Listed, not scored. Policies: {policies}.", list(dict.fromkeys(item["sla"] for item in no_match)))
    definition = next((definition for definition in schedule["slas"] if definition["id"] == "23B_UL_S2"), None)
    if definition and workflows:
        orphans = [workflow for group in by_policy(workflows, definition["params"]["workflowType"]).values() for workflow in group
                   if month_of(workflow["created"]) == month and workflow["number"] not in step_two_matched]
        if orphans:
            numbers = ", ".join(workflow["number"] for workflow in orphans[:6]) + (", …" if len(orphans) > 6 else "")
            add(findings, "unmatched_approval_workflow", "info", f"{plural(len(orphans), 'withdrawal approval workflow has', 'withdrawal approval workflows have')} no withdrawal",
                f"Created this month with no WITHDRAWALEXT record on the policy that they govern. Not part of Step 2. Workflows: {numbers}.", ["23B_UL_S2"])
    superseded = [item for item in population if item.get("candidateWorkflows", 0) > 1]
    if superseded:
        add(findings, "superseded_workflow", "info", f"{plural(len(superseded), 'item had', 'items had')} more than one approval workflow",
            "The policy carried an earlier approval workflow before the one that led to the event; the latest one created before the event was used (workbook default 7).", list(dict.fromkeys(item["sla"] for item in superseded)))
    rejected = [item for item in population if item["outcome"] == OUTCOME["EXCLUDED"]]
    if rejected:
        add(findings, "rejected_excluded", "info", f"{plural(len(rejected), 'rejected EBQ item', 'rejected EBQ items')} excluded",
            "REJECTED transactions are not processing work and are left out of 23B (workbook default 4).", list(dict.fromkeys(item["sla"] for item in rejected)))
    unmapped_here = [item for item in unmapped if item["month"] == month]
    if unmapped_here:
        pairs = {}
        for item in unmapped_here:
            key = f'{item["product"]} / {item["transactionType"]}'
            pairs[key] = pairs.get(key, 0) + 1
        top = sorted(pairs.items(), key=lambda pair: -pair[1])[:3]
        detail = "; ".join(f"{key} ({count})" for key, count in top)
        add(findings, "unmapped_ebq", "info", f"{plural(len(unmapped_here), 'EBQ transaction is', 'EBQ transactions are')} outside Mapping for 23B",
            f"Their Product + Transaction pair is not in the mapping, so they are not measured under 23B. Most frequent: {detail}.")
    dependent = [item for item in population if item.get("dependency")]
    if dependent:
        add(findings, "dependency", "info", f"{plural(len(dependent), '23B item has', '23B items have')} a dependency in the mapping",
            "For example an underwriting assessment. The SLA is still measured from start to merged (workbook default 2).", list(dict.fromkeys(item["sla"] for item in dependent)))
    return ordered(findings)
