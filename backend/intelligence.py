from datetime import date

from .engine.engine import load_schedule
from .engine.outcome import OUTCOME
from .insights import is_measured, miss_drivers
from .store import day_label


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


def trend_for(definition, window, latest_full):
    points = []
    for analysis in window:
        result = next((result for result in analysis["results"] if result["id"] == definition["id"]), {})
        points.append({
            "month": analysis["reporting_month"], "label": analysis["label"], "partial": analysis["partial"],
            "rateCompleted": result.get("rateCompleted"), "rateInclOpen": result.get("rateInclOpen"),
            "status": result.get("status", "NO_DATA"),
            **{key: result.get(key, 0) for key in ("met", "missed", "openPastDeadline", "openNotYetDue")},
        })
    complete = [point for point in points if not point["partial"] and point["status"] != "NO_DATA"]
    streak = 0
    for point in reversed(complete):
        if point["status"] != "FAIL":
            break
        streak += 1
    met, missed, overdue = (sum(point[key] for point in points) for key in ("met", "missed", "openPastDeadline"))
    window_rate = rate(met, met + missed)
    ranked = sorted(complete, key=lambda point: point["rateCompleted"])
    return {
        **{key: definition[key] for key in ("id", "label", "name", "target", "statement")},
        "parent": definition.get("parent"), "points": points, "observations": len(complete),
        "passMonths": sum(point["status"] == "PASS" for point in complete),
        "failMonths": sum(point["status"] == "FAIL" for point in complete), "failStreak": streak,
        "window": {"met": met, "missed": missed, "openPastDeadline": overdue, "rateCompleted": window_rate,
                   "rateInclOpen": rate(met, met + missed + overdue),
                   "status": "NO_DATA" if window_rate is None else "PASS" if window_rate >= definition["target"] - 1e-12 else "FAIL"},
        "latest": next((point for point in points if point["month"] == latest_full["month"]), None),
        "worst": ranked[0] if ranked else None, "best": ranked[-1] if ranked else None,
    }


def backlog_of(items, schedule, as_of):
    output = []
    for definition in schedule["slas"]:
        if definition.get("parts"):
            continue
        overdue = [item for item in items if item["sla"] == definition["id"] and item["outcome"] == OUTCOME["OPEN_PAST"]]
        if not overdue:
            continue
        oldest = min(item["deadline"] for item in overdue)
        by_month = {}
        for item in overdue:
            by_month[item["month"]] = by_month.get(item["month"], 0) + 1
        output.append({
            **{key: definition[key] for key in ("id", "label", "name")}, "count": len(overdue),
            "oldestDeadline": oldest, "oldestDeadlineLabel": day_label(oldest),
            "daysOverdue": (date.fromisoformat(as_of) - date.fromisoformat(oldest)).days if as_of else None,
            "byMonth": by_month,
        })
    return sorted(output, key=lambda backlog: -backlog["count"])


def build_intelligence(store, scope="all"):
    history = [store.read_analysis(month) for month in reversed(store.list_months())]
    history = [analysis for analysis in history if analysis]
    window = history if scope == "all" else [analysis for analysis in history if analysis["reporting_month"] <= scope]
    snapshot = store.read_snapshot() or {}
    if not window:
        return {"scope": scope, "months": [], "trends": [], "drivers": [], "backlog": [], "empty": True}
    schedule = load_schedule()
    focus = window[-1]
    full_months = [analysis for analysis in window if not analysis["partial"]]
    latest_full = full_months[-1] if full_months else focus
    latest_ref = {"month": latest_full["reporting_month"], "label": latest_full["label"]}
    trends = [trend_for(definition, window, latest_ref) for definition in schedule["slas"]]
    headline = [trend for trend in trends if not trend["parent"]]
    items = [item for analysis in window for item in analysis.get("items", [])]
    backlog = backlog_of(items, schedule, snapshot.get("as_of"))
    def months(population):
        return [{"month": analysis["reporting_month"], "label": analysis["label"], "partial": analysis["partial"]} for analysis in population]
    return {
        "scope": scope, "empty": False, "asOf": snapshot.get("as_of"), "asOfLabel": snapshot.get("as_of_label"),
        "months": months(window), "allMonths": months(history), "focusLabel": focus["label"],
        "focusPartial": focus["partial"], "latestFull": latest_ref, "trends": trends,
        "drivers": miss_drivers(items, min_items=5, min_failures=3, limit=10), "backlog": backlog,
        "headline": {
            "monthsAnalysed": len(window), "slaCount": len(headline),
            "passingLatest": sum((trend["latest"] or {}).get("status") == "PASS" for trend in headline),
            "failingLatest": sum((trend["latest"] or {}).get("status") == "FAIL" for trend in headline),
            "failingLatestIds": [trend["id"] for trend in headline if (trend["latest"] or {}).get("status") == "FAIL"],
            "failMonths": sum(trend["failMonths"] for trend in headline),
            "scoredMonths": sum(trend["observations"] for trend in headline),
            "openPastDeadline": sum(entry["count"] for entry in backlog), "measured": sum(map(is_measured, items)),
        },
    }
