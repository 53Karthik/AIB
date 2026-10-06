import re


OUTCOME = {
    "MET": "MET",
    "MISSED": "MISSED",
    "OPEN_PAST": "OPEN - PAST DEADLINE",
    "OPEN_DUE": "OPEN - NOT YET DUE",
    "EXCLUDED": "EXCLUDED - REJECTED",
    "NO_MATCH": "NO MATCHING WORKFLOW",
}


def judge(completed_day, deadline, as_of_day):
    if completed_day:
        return OUTCOME["MET"] if completed_day <= deadline else OUTCOME["MISSED"]
    return OUTCOME["OPEN_PAST"] if deadline < as_of_day else OUTCOME["OPEN_DUE"]


def norm(value):
    return re.sub(r"\s+", " ", str(value if value is not None else "").strip()).lower()
