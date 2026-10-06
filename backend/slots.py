from .engine.extracts import is_blank


EXTRACT_SLOTS = [
    {"id": "ebq", "kind": "ebq", "mark": "EB", "label": "EBQ Correspondence Report", "feeds": ["23B_NUL", "23B_UL_S1"]},
    {"id": "cancellation", "kind": "cancellation", "mark": "CR", "label": "Cancellation Tracker (CANREVEXT)", "feeds": ["23C"]},
    {"id": "withdrawal", "kind": "withdrawal", "mark": "WD", "label": "Withdrawal extract (WITHDRAWALEXT)", "feeds": ["23B_UL_S2"]},
    {"id": "workflow-open", "kind": "workflow", "mark": "WO", "label": "Workflow extract — open items", "feeds": ["23A", "23B_UL_S2", "23B_UL_S3", "23C", "23E"]},
    {"id": "workflow-closed", "kind": "workflow", "mark": "WC", "label": "Workflow extract — closed items", "feeds": ["23A", "23B_UL_S2", "23B_UL_S3", "23C", "23E"]},
]


def slots_of(parsed):
    if parsed["kind"] != "workflow":
        return [parsed["kind"]]
    closed = sum(not is_blank(record.get("close date")) and str(record.get("close date")).strip().lower() != "nan"
                 for record in parsed["records"])
    slots = []
    if len(parsed["records"]) - closed:
        slots.append("workflow-open")
    if closed:
        slots.append("workflow-closed")
    return slots or ["workflow-open"]
