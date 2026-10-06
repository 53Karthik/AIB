import json
import re

from .narrative import brief, sla_facts, driver_facts, pct, numeric, unsupported_figures


STOP = set("the is are was why what which how and for our this that did does fail failed failing pass passed sla slas target month months we it in on at of to a an about tell me show explain where worst report rate service level levels items many".split())
ALIASES = {
    "23A": ["23a", "policy issue", "issue policy", "issuance", "new business"],
    "23B_NUL": ["23b nul", "nul", "non unit linked", "alteration", "alterations"],
    "23B_UL": ["23b ul", "ul", "unit linked", "unit"],
    "23B_UL_S1": ["step 1", "step1", "ebq unit linked"],
    "23B_UL_S2": ["step 2", "step2", "withdrawal", "withdrawals"],
    "23B_UL_S3": ["step 3", "step3", "unit adjustment", "adjustments"],
    "23C": ["23c", "cancellation", "cancellations", "cancel"],
    "23E": ["23e", "eft", "unrecognised", "payment", "payments", "manual review"],
}
SYSTEM_PROMPT = """You answer questions about this Irish life assurance Schedule 23 SLA governance report from ALREADY COMPUTED figures only.
Never state a number absent from the context, recompute, re-round, estimate, forecast or predict. Pass/fail is rateCompleted against target; overdue open items are separate.
Answer in 2 to 4 sentences, without headings, bullets, preamble or sign-off, in plain British/Irish English.
Explain failures from slaInQuestion.historyByMonth, whereFailuresConcentrate and openPastDeadline. If the context lacks the answer, say so and name what the report covers. If unrelated, say you only cover this report. Never use only, sole or the single about a count unless it is exactly 1."""


def tokens(text):
    return [word for word in re.sub(r"[^a-z0-9\s]", " ", str(text).lower()).split() if word not in STOP]


def resolve_sla(question, trends):
    question_tokens = tokens(question)
    vocabulary = [(trend, set(tokens(trend["label"]) + tokens(trend["name"]) + [word for alias in ALIASES.get(trend["id"], []) for word in tokens(alias)])) for trend in trends]
    spread = {}
    for trend, terms in vocabulary:
        for term in terms:
            spread[term] = spread.get(term, 0) + 1
    best, best_score = None, 0
    for trend, terms in vocabulary:
        score = sum(1 / spread.get(word, 1) for word in question_tokens
                    if any(term == word or len(word) > 3 and term.startswith(word) or len(term) > 3 and word.startswith(term) for term in terms))
        if score > best_score:
            best, best_score = trend, score
    return best if best_score >= 0.5 else None


def build_context(intel, question):
    base = brief(intel)
    trend = resolve_sla(question, intel["trends"])
    if not trend:
        return {**base, "questionAboutSpecificSla": False}
    return {**base, "questionAboutSpecificSla": True, "slaInQuestion": {
        **sla_facts(trend), "statement": trend["statement"],
        "historyByMonth": [{"month": point["label"], "incomplete": point["partial"], "rateCompleted": pct(point["rateCompleted"]),
                            **{key: point[key] for key in ("status", "met", "missed", "openPastDeadline")}}
                           for point in trend["points"] if point["status"] != "NO_DATA" or point["openPastDeadline"]],
        "whereFailuresConcentrate": [driver_facts(driver, intel) for driver in intel["drivers"] if driver["sla"] == trend["id"]],
        "openPastDeadline": next((backlog for backlog in intel["backlog"] if backlog["id"] == trend["id"]), None),
    }}


def compose_answer(intel, question):
    trend = resolve_sla(question, intel["trends"])
    latest = intel["latestFull"]["label"]
    if not trend:
        failing = [trend for trend in intel["trends"] if not trend["parent"] and (trend["latest"] or {}).get("status") == "FAIL"]
        text = f'This report covers {intel["headline"]["monthsAnalysed"]} periods to {intel["focusLabel"]}. In {latest}, {intel["headline"]["passingLatest"]} of {intel["headline"]["slaCount"]} service levels met target'
        text += "; " + ", ".join(f'{trend["label"]} ({pct(trend["latest"]["rateCompleted"])} against {pct(trend["target"])})' for trend in failing) + " did not. " if failing else ". "
        return text + f'{intel["headline"]["openPastDeadline"]:,} items were open past deadline at the extract date. Ask about a service level by code (23A, 23B NUL, 23B UL, 23C, 23E) for its history and where its failures sit.'
    text = f'{trend["label"]} ({trend["name"]}) targets {pct(trend["target"])}. '
    point = trend["latest"]
    if point and point["status"] != "NO_DATA":
        text += f'In {latest} it achieved {pct(point["rateCompleted"])} — {"met" if point["status"] == "PASS" else "missed"} ({point["met"]} met, {point["missed"]} missed). '
    else:
        text += f"It has no completed items in {latest}. "
    text += f'Across the window it failed {trend["failMonths"]} of {trend["observations"]} complete months, {pct(trend["window"]["rateCompleted"])} overall.'
    parts = [text]
    if trend["worst"]:
        parts.append(f'Its weakest complete month was {trend["worst"]["label"]} at {pct(trend["worst"]["rateCompleted"])}.')
    drivers = [driver for driver in intel["drivers"] if driver["sla"] == trend["id"]][:2]
    if drivers:
        parts.append("Failures concentrate in " + " and ".join(f'{driver["key"]} ({driver["dimensionLabel"].lower()}: {driver["failures"]} failures, {numeric(driver["failRatePct"])}% against {numeric(driver["slaFailRatePct"])}% overall)' for driver in drivers) + ".")
    backlog = next((backlog for backlog in intel["backlog"] if backlog["id"] == trend["id"]), None)
    if backlog:
        parts.append(f'{backlog["count"]} of its items were open past deadline at the extract date, the oldest due {backlog["oldestDeadlineLabel"]}.')
    return " ".join(parts)


def ask_assistant(intel, question, narrative, allow_model=True):
    trimmed = str(question or "").strip()
    if not trimmed:
        return {"answer": "Ask a question about this report.", "source": "rules"}
    matched = resolve_sla(trimmed, intel["trends"])
    grounding = {"matchedSla": f'{matched["label"]} · {matched["name"]}' if matched else None}
    status = narrative.status()
    if allow_model and status["bedrockConfigured"]:
        context = build_context(intel, trimmed)
        try:
            text = narrative.bedrock_text(system=SYSTEM_PROMPT, user=f"Report context:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\nQuestion: {trimmed}", max_tokens=500, temperature=0.15)
            if not text:
                raise ValueError("empty answer")
            invented = unsupported_figures(text, context)
            if invented:
                raise ValueError(f'answer quoted figures absent from the report: {", ".join(invented)}')
            return {"answer": text, "source": "bedrock", "model": status["model"], **grounding}
        except Exception as error:
            return {"answer": compose_answer(intel, trimmed), "source": "rules", "fallbackReason": str(error), **grounding}
    return {"answer": compose_answer(intel, trimmed), "source": "rules", **grounding}


def suggested_questions(intel):
    output = []
    failing = [trend for trend in intel["trends"] if not trend["parent"] and (trend["latest"] or {}).get("status") == "FAIL"]
    if failing:
        output.append(f'Why did {failing[0]["label"]} miss target in {intel["latestFull"]["label"]}?')
    headline = [trend for trend in intel["trends"] if not trend["parent"]]
    chronic = max(headline, key=lambda trend: trend["failMonths"], default=None)
    if chronic and chronic["failMonths"] and chronic["id"] != (failing[0]["id"] if failing else None):
        output.append(f'How often has {chronic["label"]} failed?')
    if intel["drivers"]:
        label = next((trend["label"] for trend in intel["trends"] if trend["id"] == intel["drivers"][0]["sla"]), "undefined")
        output.append(f"Where are the {label} failures concentrated?")
    if intel["headline"]["openPastDeadline"]:
        output.append("How many items are open past deadline?")
    return output[:4]
