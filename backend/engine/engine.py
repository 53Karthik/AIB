import json
from pathlib import Path
from types import SimpleNamespace

from .calendar import Calendar
from .outcome import OUTCOME
from .rules import RULES, build_mapping
from .workflows import collect_workflows, derive_as_of


ROOT = Path(__file__).resolve().parents[2]
COUNT_KEYS = dict(zip(OUTCOME.values(), ("met", "missed", "openPastDeadline", "openNotYetDue", "excluded", "noMatch")))


def load_schedule():
    return json.loads((ROOT / "config/sla-schedule.json").read_text(encoding="utf-8"))


def load_mapping_rows():
    return json.loads((ROOT / "config/mapping-23b.json").read_text(encoding="utf-8"))["rows"]


def empty_counts():
    return dict.fromkeys(COUNT_KEYS.values(), 0)


def score_counts(definition, counts):
    completed = counts["met"] + counts["missed"]
    with_open = completed + counts["openPastDeadline"]
    rate = counts["met"] / completed if completed else None
    return {
        "id": definition["id"], "label": definition["label"], "name": definition["name"],
        "parent": definition.get("parent"), "target": definition["target"], **counts,
        "completed": completed, "rateCompleted": rate,
        "rateInclOpen": counts["met"] / with_open if with_open else None,
        "status": "NO_DATA" if rate is None else "PASS" if rate >= definition["target"] - 1e-12 else "FAIL",
    }


def counts_by(items, key_fn):
    groups = {}
    for item in items:
        counts = groups.setdefault(key_fn(item), {}).setdefault(item["sla"], empty_counts())
        count_key = COUNT_KEYS.get(item["outcome"])
        if count_key:
            counts[count_key] += 1
    return groups


def score_all(schedule, by_sla):
    results = []
    for definition in schedule["slas"]:
        counts = empty_counts()
        for part in definition.get("parts", [definition["id"]]):
            for key, value in (by_sla or {}).get(part, {}).items():
                counts[key] += value
        results.append(score_counts(definition, counts))
    return results


def evaluate(extracts, *, schedule=None, mapping_rows=None, as_of=None):
    schedule = load_schedule() if schedule is None else schedule
    mapping_rows = load_mapping_rows() if mapping_rows is None else mapping_rows
    workflows = collect_workflows(extracts)
    derived = derive_as_of(workflows, extracts)
    as_of_day = as_of if as_of is not None else derived["day"] if derived else None
    if not as_of_day:
        raise ValueError("Could not establish the extract date from the files; supply it explicitly")
    definitions = {definition["id"]: definition for definition in schedule["slas"]}

    def definition(sla):
        if sla not in definitions:
            raise ValueError(f"SLA {sla} is not defined in config/sla-schedule.json")
        return definitions[sla]

    calendar = schedule.get("calendar", {})
    ctx = SimpleNamespace(extracts=extracts, workflows=workflows, as_of_day=as_of_day,
                          cal=Calendar(calendar.get("holidays", []), calendar.get("cutoffHour", 15)),
                          mapping=build_mapping(mapping_rows), definition=definition)
    items, out_of_scope, unmapped = [], {}, []
    for rule in RULES:
        result = rule(ctx)
        items.extend(result["items"])
        sla_ids = list(dict.fromkeys(item["sla"] for item in result["items"]))
        if result["outOfScope"]:
            out_of_scope["+".join(sla_ids) or rule.__name__] = result["outOfScope"]
        if "unmapped" in result:
            unmapped = result["unmapped"]
    months = counts_by(items, lambda item: item["month"])
    return {
        "asOf": as_of_day, "asOfSource": "Set explicitly" if as_of else derived["source"] if derived else None,
        "schedule": schedule, "mappingRows": mapping_rows, "workflows": workflows, "items": items,
        "outOfScope": out_of_scope, "unmapped23B": unmapped,
        "monthly": [{"month": month, "results": score_all(schedule, months[month])} for month in sorted(month for month in months if month)],
        "totals": score_all(schedule, counts_by(items, lambda item: "all").get("all")),
    }
