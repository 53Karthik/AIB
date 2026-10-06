import hashlib
import json
import os
from pathlib import Path
import re

from .insights import rounded
from .pipeline import utc_now


SYSTEM_PROMPT = """You write the executive summary of an Irish life assurance Schedule 23 SLA governance pack from ALREADY COMPUTED figures. Phrase them; never compute or infer new figures.
Never state numbers absent from the input, re-round, estimate, forecast or predict. Pass/fail is rateCompleted against target; overdue open items are separate. Never use only, sole or the single about a count unless it is exactly 1.
Write 3 to 4 short paragraphs, separated by blank lines, without headings, bullets or preamble, in British/Irish English.
Paragraph 1: latestCompleteMonth; name exactly the codes in metTarget as meeting target and missedTarget as missing it, with their rates. Never move codes between lists.
Paragraph 2: missedTargetInMostCompleteMonths and which meet target across the whole window.
Paragraph 3: failure concentration, naming group, dimension and SLA. Paragraph 4: overdue items at the extract date."""


def pct(value):
    return "no data" if value is None else f"{rounded(value * 100, 100):.2f}%"


def numeric(value):
    return str(int(value)) if float(value).is_integer() else str(value)


def sla_facts(trend):
    words = {"PASS": "MET TARGET", "FAIL": "MISSED TARGET", "NO_DATA": "NO COMPLETED ITEMS"}
    latest, window, worst = trend["latest"], trend["window"], trend["worst"]
    return {
        "sla": trend["label"], "name": trend["name"], "target": pct(trend["target"]),
        "inLatestCompleteMonth": {"result": words.get(latest["status"], words["NO_DATA"]),
                                  "rateCompleted": pct(latest["rateCompleted"]), "itemsMet": latest["met"], "itemsMissed": latest["missed"]} if latest else None,
        "acrossWholeWindow": {"result": words.get(window["status"], words["NO_DATA"]), "rateCompleted": pct(window["rateCompleted"]),
                              "rateIncludingOverdueOpenItems": pct(window["rateInclOpen"]),
                              **{key: window[key] for key in ("met", "missed", "openPastDeadline")}},
        "completeMonthsScored": trend["observations"], "completeMonthsFailed": trend["failMonths"],
        "consecutiveCompleteMonthsFailingUpToLatest": trend["failStreak"],
        "worstCompleteMonth": {"month": worst["label"], "rateCompleted": pct(worst["rateCompleted"]),
                               "completedItemsThatMonth": worst["met"] + worst["missed"]} if worst else None,
    }


def driver_facts(driver, intel):
    return {
        "sla": next((trend["label"] for trend in intel["trends"] if trend["id"] == driver["sla"]), driver["sla"]),
        "dimension": driver["dimensionLabel"], "group": driver["key"],
        **{key: driver[key] for key in ("failures", "missed", "openPastDeadline")},
        **{output: f"{numeric(driver[key])}%" for output, key in
           (("groupFailRate", "failRatePct"), ("slaFailRate", "slaFailRatePct"), ("shareOfSlaFailures", "sharePct"), ("shareOfSlaVolume", "volumeSharePct"))},
    }


def failed_most_often(headline):
    maximum = max([0, *[trend["failMonths"] for trend in headline]])
    return [{"sla": trend["label"], "completeMonthsMissed": trend["failMonths"], "completeMonthsScored": trend["observations"]}
            for trend in headline if maximum and trend["failMonths"] == maximum]


def brief(intel):
    headline = [trend for trend in intel["trends"] if not trend["parent"]]
    def in_latest(status):
        return [{"sla": trend["label"], "rateCompleted": pct(trend["latest"]["rateCompleted"]), "target": pct(trend["target"])}
                for trend in headline if (trend["latest"] or {}).get("status") == status]
    return {
        "window": f'{intel["months"][0]["label"]} to {intel["focusLabel"]}', "periodsAnalysed": intel["headline"]["monthsAnalysed"],
        "extractTakenOn": intel["asOfLabel"], "latestMonthIsIncomplete": intel["focusLabel"] if intel["focusPartial"] else None,
        "slaCount": len(headline), "latestCompleteMonth": {"month": intel["latestFull"]["label"],
        "metTarget": in_latest("PASS"), "missedTarget": in_latest("FAIL"),
        "noCompletedItems": [trend["label"] for trend in headline if not trend["latest"] or trend["latest"]["status"] == "NO_DATA"]},
        "missedTargetInMostCompleteMonths": failed_most_often(headline), "slas": list(map(sla_facts, headline)),
        "unitLinkedSteps": [sla_facts(trend) for trend in intel["trends"] if trend["parent"]],
        "whereFailuresConcentrate": [driver_facts(driver, intel) for driver in intel["drivers"][:4]],
        "openPastDeadlineAtExtractDate": {"total": intel["headline"]["openPastDeadline"],
        "bySla": [{"sla": backlog["label"], "items": backlog["count"], "oldestDeadline": backlog["oldestDeadlineLabel"]} for backlog in intel["backlog"][:4]]},
    }


def compose_narrative(intel):
    headline = [trend for trend in intel["trends"] if not trend["parent"]]
    latest = intel["latestFull"]["label"]
    failing = [trend for trend in headline if (trend["latest"] or {}).get("status") == "FAIL"]
    passing = [trend for trend in headline if (trend["latest"] or {}).get("status") == "PASS"]
    first = f"In {latest}, {len(passing)} of {len(headline)} Schedule 23 service levels met target"
    if failing:
        details = "; ".join(f'{trend["label"]} at {pct(trend["latest"]["rateCompleted"])} against {pct(trend["target"])}' for trend in failing)
        first += f". {len(failing)} fell short: {details}."
    else:
        first += ", with none below target."
    if intel["focusPartial"]:
        first += f' {intel["focusLabel"]} is still incomplete at the extract date ({intel["asOfLabel"]}) and is read separately.'
    paragraphs = [first]
    chronic = sorted((trend for trend in headline if trend["failMonths"] > 0), key=lambda trend: -trend["failMonths"])
    if chronic:
        top = chronic[0]
        steady = [trend for trend in headline if trend["window"]["status"] == "PASS"]
        paragraph = f'Across {intel["headline"]["monthsAnalysed"]} periods ({intel["months"][0]["label"]} to {intel["focusLabel"]}), {top["label"]} missed target in {top["failMonths"]} of {top["observations"]} complete months'
        if top["failStreak"] > 1:
            paragraph += f', including the last {top["failStreak"]} in a row'
        paragraph += f', for {pct(top["window"]["rateCompleted"])} overall against {pct(top["target"])}. '
        paragraph += f'{", ".join(trend["label"] for trend in steady)} {"meets" if len(steady) == 1 else "meet"} target over the window as a whole.' if steady else "No service level meets target over the window as a whole."
        paragraphs.append(paragraph)
    labels = {trend["id"]: trend["label"] for trend in intel["trends"]}
    if intel["drivers"]:
        driver = intel["drivers"][0]
        second = next((other for other in intel["drivers"] if other["sla"] != driver["sla"] or other["dimension"] != driver["dimension"]), None)
        paragraph = f'Failures are concentrated rather than spread evenly: on {labels.get(driver["sla"], driver["sla"])}, {driver["dimensionLabel"].lower()} {driver["key"]} accounts for {driver["failures"]:,} failures, a {numeric(driver["failRatePct"])}% failure rate against {numeric(driver["slaFailRatePct"])}% for the service level as a whole'
        paragraph += f'. {second["key"]} ({second["dimensionLabel"].lower()}, {labels.get(second["sla"], second["sla"])}) follows with {second["failures"]:,} at {numeric(second["failRatePct"])}%.' if second else "."
        paragraphs.append(paragraph)
    if intel["headline"]["openPastDeadline"] > 0:
        details = ", ".join(f'{backlog["count"]:,} on {backlog["label"]}' for backlog in intel["backlog"][:3])
        paragraphs.append(f'At the extract date ({intel["asOfLabel"]}), {intel["headline"]["openPastDeadline"]:,} items were still open past their deadline — {details}. They sit outside the completed-item rate that decides pass or fail, but each is a miss in waiting.')
    return "\n\n".join(paragraphs)


def unsupported_figures(text, payload):
    known = set()
    for token in re.findall(r"-?\d+(?:\.\d+)?", json.dumps(payload, ensure_ascii=False)):
        known.update((token, numeric(float(token))))
    return list(dict.fromkeys(token for token in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text)
                             if token.replace(",", "") not in known and numeric(float(token.replace(",", ""))) not in known))


SLA_CODE = re.compile(r"23B UL Step [123]|23B NUL|23B UL|23A|23C|23E")
CLAUSE_BREAK = re.compile(r"[.;:]|\bwhile\b|\bwhereas\b|\bbut\b|\balthough\b|\bhowever\b", re.I)


def contradicted_claims(text, intel):
    latest = {trend["label"]: (trend.get("latest") or {}).get("status") for trend in intel["trends"]}
    most_often = [entry["sla"] for entry in failed_most_often([trend for trend in intel["trends"] if not trend.get("parent")])]
    bad = []
    opening = re.split(r"\n\s*\n", text)[0]
    for clause in CLAUSE_BREAK.split(opening):
        missed = bool(re.search(r"\b(fail\w*|miss\w*|fell short|short of|below|breach\w*|did not meet|not met)\b", clause, re.I))
        met = bool(re.search(r"\b(met|meet|meets|meeting|pass\w*|achieved|above|on target)\b", clause, re.I))
        if missed == met:
            continue
        for code in SLA_CODE.findall(clause):
            if missed and latest.get(code) == "PASS":
                bad.append(f'{code} said to miss target in {intel["latestFull"]["label"]} but met it')
            if met and latest.get(code) == "FAIL":
                bad.append(f'{code} said to meet target in {intel["latestFull"]["label"]} but missed it')
    for clause in CLAUSE_BREAK.split(text):
        if re.search(r"\bmost (often|frequently)\b", clause, re.I):
            for code in SLA_CODE.findall(clause):
                if code not in most_often:
                    bad.append(f'{code} said to fail most often, but {", ".join(most_often)} {"does" if len(most_often) == 1 else "do"}')
    return list(dict.fromkeys(bad))


class Narrative:
    def __init__(self, store, *, text_call=None, clock=utc_now):
        self.store = store
        self.text_call = text_call
        self.clock = clock

    def status(self):
        credentials = Path(os.environ.get("AWS_SHARED_CREDENTIALS_FILE") or str(Path.home() / ".aws/credentials"))
        configured = bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("AWS_PROFILE") or os.environ.get("AWS_ROLE_ARN") or credentials.exists())
        source = "environment" if os.environ.get("AWS_ACCESS_KEY_ID") else f'profile:{os.environ["AWS_PROFILE"]}' if os.environ.get("AWS_PROFILE") else "shared credentials file" if credentials.exists() else "none"
        return {"bedrockConfigured": configured, "credentialSource": source,
                "model": os.environ.get("BEDROCK_MODEL_ID") or "amazon.nova-pro-v1:0",
                "region": os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"}

    def bedrock_text(self, *, system, user, max_tokens=1400, temperature=0.2):
        if self.text_call:
            return self.text_call(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
        import boto3
        from botocore.config import Config

        status = self.status()
        client = boto3.client("bedrock-runtime", region_name=status["region"],
                              config=Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 2}))
        if re.search(r"(^|\.)amazon\.nova", status["model"]):
            response = client.converse(modelId=status["model"], system=[{"text": system}],
                                       messages=[{"role": "user", "content": [{"text": user}]}],
                                       inferenceConfig={"maxTokens": max_tokens, "temperature": temperature, "topP": 0.9})
            return "".join(block.get("text", "") for block in response.get("output", {}).get("message", {}).get("content", [])).strip()
        response = client.invoke_model(modelId=status["model"], contentType="application/json", accept="application/json",
                                       body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": max_tokens,
                                                        "system": system, "messages": [{"role": "user", "content": user}]}))
        payload = json.loads(response["body"].read())
        return "".join(block["text"] for block in payload.get("content", []) if block.get("type") == "text").strip()

    def generate(self, intel, refresh=False):
        status = self.status()
        payload = brief(intel)
        configured = status["bedrockConfigured"]
        key_payload = {"brief": payload, "provider": "bedrock" if configured else "rules",
                       "model": status["model"] if configured else None, "region": status["region"] if configured else None}
        key = hashlib.sha256(json.dumps(key_payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:16]
        path = self.store.data_dir / "narratives" / f"python-{key}.json"
        if not refresh:
            cached = self.store._read_json(path, None)
            if cached:
                return {**cached, "cached": True}
        if configured:
            try:
                text = self.bedrock_text(system=SYSTEM_PROMPT, user=f"Write the executive insight summary from these computed figures:\n\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
                if not text:
                    raise ValueError("Bedrock returned no text")
                invented = unsupported_figures(text, payload)
                if invented:
                    raise ValueError(f'narrative quoted figures absent from its input: {", ".join(invented)}')
                wrong = contradicted_claims(text, intel)
                if wrong:
                    raise ValueError(f'narrative contradicted the computed results: {"; ".join(wrong)}')
                return self.store._write_json(path, {"text": text, "source": "bedrock", "model": status["model"], "generatedAt": self.clock()})
            except Exception as error:
                return {"text": compose_narrative(intel), "source": "rules", "fallbackReason": str(error), "generatedAt": self.clock(), "cached": False}
        return self.store._write_json(path, {"text": compose_narrative(intel), "source": "rules", "generatedAt": self.clock()})
