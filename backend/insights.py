import math

from .engine.outcome import OUTCOME


DIMENSIONS = [("assignee", "Assigned to"), ("userId", "EBQ user"), ("product", "Product"),
              ("workflowType", "Workflow type"), ("transactionType", "Transaction type")]


def is_failure(item):
    return item["outcome"] in (OUTCOME["MISSED"], OUTCOME["OPEN_PAST"])


def is_measured(item):
    return item["outcome"] == OUTCOME["MET"] or is_failure(item)


def rounded(value, scale):
    return math.floor(value * scale + 0.5) / scale


def pct(numerator, denominator):
    return rounded(numerator / denominator * 100, 100) if denominator else None


def miss_drivers(items, *, min_items=5, min_failures=2, min_lift=1.25, limit=12):
    by_sla = {}
    for item in items:
        if is_measured(item):
            by_sla.setdefault(item["sla"], []).append(item)
    output = []
    for sla, population in by_sla.items():
        failures = sum(map(is_failure, population))
        if not failures:
            continue
        base_rate = failures / len(population)
        for dimension, label in DIMENSIONS:
            groups = {}
            for item in population:
                key = str(item.get(dimension) or "").strip()
                if not key:
                    continue
                group = groups.setdefault(key, {"measured": 0, "missed": 0, "openPastDeadline": 0})
                group["measured"] += 1
                group["missed"] += item["outcome"] == OUTCOME["MISSED"]
                group["openPastDeadline"] += item["outcome"] == OUTCOME["OPEN_PAST"]
            if len(groups) < 2:
                continue
            for key, group in groups.items():
                failed = group["missed"] + group["openPastDeadline"]
                if group["measured"] < min_items or failed < min_failures:
                    continue
                output.append({
                    "sla": sla, "dimension": dimension, "dimensionLabel": label, "key": key, **group,
                    "failures": failed, "failRatePct": pct(failed, group["measured"]),
                    "slaFailRatePct": pct(failures, len(population)), "sharePct": pct(failed, failures),
                    "volumeSharePct": pct(group["measured"], len(population)),
                    "timesSlaRate": rounded(failed / group["measured"] / base_rate, 100),
                    "excessFailures": rounded(failed - group["measured"] * base_rate, 10),
                })
    return sorted((driver for driver in output if driver["timesSlaRate"] >= min_lift),
                  key=lambda driver: -driver["excessFailures"])[:limit]
