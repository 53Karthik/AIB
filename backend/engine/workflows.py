import math
import re
from datetime import datetime

from .datetime import parse_stamp, day_of, add_days
from .extracts import text, id_of
from .outcome import norm


def number(value):
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return float("nan")


def collect_workflows(extracts):
    workflows = []
    for extract in extracts:
        if extract["kind"] != "workflow":
            continue
        for record in extract["records"]:
            created = parse_stamp(record.get("created date"))
            if created is None:
                continue
            closed = parse_stamp(record.get("close date"))
            pending = record.get("pending since days")
            workflows.append({
                "number": id_of(record, "workflow number"), "type": text(record, "workflow type"),
                "policy": id_of(record, "reference number"), "product": text(record, "product name"),
                "created": created, "closeDay": day_of(closed), "status": text(record, "status"),
                "open": closed is None, "description": text(record, "workflow description"),
                "assignee": text(record, "assigned to name"), "assigneeCode": text(record, "assigned to"),
                "createdBy": text(record, "created by"),
                "pendingDays": None if pending is None or pending == "" else number(pending),
                "sourceRow": record["_row"],
            })
    return workflows


def by_policy(workflows, workflow_type):
    grouped = {}
    for workflow in workflows:
        if norm(workflow["type"]) == norm(workflow_type):
            grouped.setdefault(workflow["policy"], []).append(workflow)
    for group in grouped.values():
        group.sort(key=lambda workflow: workflow["created"])
    return grouped


def latest_before(workflows, when):
    if not workflows or when is None:
        return None
    hit = None
    for workflow in workflows:
        if workflow["created"] <= when:
            hit = workflow
    return hit


def derive_as_of(workflows, extracts):
    votes = {}
    for workflow in workflows:
        pending = workflow["pendingDays"]
        if not workflow["open"] or pending is None or not math.isfinite(pending):
            continue
        day = add_days(day_of(workflow["created"]), math.trunc(pending))
        votes[day] = votes.get(day, 0) + 1
    if votes:
        day = max(votes, key=votes.get)
        return {"day": day, "source": f"Workflow Created Date + Pending Since Days ({votes[day]} open workflows agree)"}
    latest = None
    for extract in extracts:
        for record in extract["records"]:
            for value in record.values():
                if isinstance(value, datetime) or isinstance(value, str) and re.match(r"^\d{1,2}/\d{1,2}/\d{4}", value):
                    stamp = parse_stamp(value)
                    if stamp is not None and (latest is None or stamp > latest):
                        latest = stamp
    return {"day": add_days(day_of(latest), 1), "source": "Day after the latest activity in the extracts"} if latest else None
