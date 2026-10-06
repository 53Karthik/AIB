from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from .engine.engine import evaluate
from .engine.extracts import read_extract
from .engine.outcome import OUTCOME
from .insights import is_measured, miss_drivers
from .quality import set_findings, month_findings, summarise
from .slots import EXTRACT_SLOTS, slots_of
from .store import Store, month_label, day_label


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def summary_of(results, items):
    headline = [result for result in results if not result["parent"]]
    return {
        "total": len(headline), "pass": sum(result["status"] == "PASS" for result in headline),
        "fail": sum(result["status"] == "FAIL" for result in headline),
        "noData": sum(result["status"] == "NO_DATA" for result in headline),
        "failing": [result["id"] for result in headline if result["status"] == "FAIL"],
        "measured": sum(map(is_measured, items)),
        **{key: sum(item["outcome"] == OUTCOME[outcome] for item in items)
           for key, outcome in (("met", "MET"), ("missed", "MISSED"), ("openPastDeadline", "OPEN_PAST"), ("openNotYetDue", "OPEN_DUE"))},
    }


class Pipeline:
    def __init__(self, store=None, *, clock=utc_now):
        self.store = store if store is not None else Store()
        self.clock = clock
        self.lock = RLock()

    def import_extracts(self, incoming):
        with self.lock:
            index = self.store.read_extract_index()
            added, replaced, skipped = [], [], []
            for file in incoming:
                try:
                    parsed = read_extract(file["buffer"], file["originalName"])
                except Exception as error:
                    skipped.append({"filename": file["originalName"], "error": str(error)})
                    continue
                covers = slots_of(parsed)
                identifier = str(uuid4())[:8]
                entry = {
                    "id": identifier, "stored": self.store.save_extract_file(identifier, file["originalName"], file["buffer"]),
                    "filename": file["originalName"], "ext": parsed["ext"], "bytes": len(file["buffer"]),
                    "uploadedAt": self.clock(), "kind": parsed["kind"], "label": parsed["label"],
                    "covers": covers, "title": " · ".join(parsed["title"]), "headerRow": parsed["headerRow"],
                    "columns": len(parsed["columns"]), "records": len(parsed["records"]),
                }
                old_entries = [old for old in index if set(old["covers"]) & set(covers)]
                index = [old for old in index if old not in old_entries] + [entry]
                self.store.write_extract_index(index)
                for old in old_entries:
                    self.store.delete_extract_file(old["stored"])
                    replaced.append(old["filename"])
                added.append(entry)
            self.store.write_extract_index(index)
            return {"added": added, "replaced": replaced, "skipped": skipped}

    def remove_extract(self, identifier):
        with self.lock:
            index = self.store.read_extract_index()
            entry = next((entry for entry in index if entry["id"] == identifier), None)
            self.store.write_extract_index([entry for entry in index if entry["id"] != identifier])
            if entry:
                self.store.delete_extract_file(entry["stored"])
            return entry is not None

    def slot_status(self, index=None):
        index = self.store.read_extract_index() if index is None else index
        output = []
        for slot in EXTRACT_SLOTS:
            file = next((entry for entry in index if slot["id"] in entry["covers"]), None)
            output.append({**slot, "present": file is not None, "filename": file["filename"] if file else None,
                           "records": file["records"] if file else None})
        return output

    def rebuild(self):
        with self.lock:
            index = self.store.read_extract_index()
            if not index:
                self.store.clear_analyses()
                self.store.clear_snapshot()
                return None
            extracts = [read_extract(self.store.read_extract_file(entry["stored"]), entry["filename"]) for entry in index]
            result = evaluate(extracts)
            generated_at = self.clock()
            as_of_label = day_label(result["asOf"])
            sources = [{key: value for key, value in entry.items() if key != "stored"} for entry in index]
            set_flags = [{**finding, "scope": "set"} for finding in set_findings(
                sources=sources, mapping_rows=result["mappingRows"], extracts=extracts, schedule=result["schedule"])]
            step_two_matched = {item["workflowNumber"] for item in result["items"]
                                if item["sla"] == "23B_UL_S2" and item.get("workflowNumber")}
            analyses = {}
            for month in result["monthly"]:
                items = [item for item in result["items"] if item["month"] == month["month"]]
                quality = [{**finding, "scope": "month"} for finding in month_findings(
                    month=month["month"], items=items, results=month["results"], as_of=result["asOf"], as_of_label=as_of_label,
                    unmapped=result["unmapped23B"], workflows=result["workflows"], schedule=result["schedule"],
                    step_two_matched=step_two_matched)] + set_flags
                analyses[month["month"]] = {
                    "reporting_month": month["month"], "label": month_label(month["month"]), "generated_at": generated_at,
                    "as_of": result["asOf"], "as_of_label": as_of_label, "partial": result["asOf"][:7] == month["month"],
                    "results": month["results"], "summary": summary_of(month["results"], items), "quality": quality,
                    "quality_summary": summarise(quality), "drivers": miss_drivers(items, min_items=3, min_failures=2, limit=8),
                    "sources": sources, "items": items,
                }
            for month, analysis in analyses.items():
                self.store.write_analysis(month, analysis)
            for month in set(self.store.list_months()) - analyses.keys():
                self.store._analysis_path(month).unlink()
            return self.store.write_snapshot({
                "generated_at": generated_at, "as_of": result["asOf"], "as_of_label": as_of_label,
                "as_of_source": result["asOfSource"], "sources": sources, "slots": self.slot_status(index), "quality": set_flags,
                "totals": result["totals"], "out_of_scope": result["outOfScope"], "months": list(analyses),
                "records": sum(source["records"] for source in sources), "measured": sum(map(is_measured, result["items"])),
            })

    def load_bundled(self, log=lambda message: None):
        with self.lock:
            files = self.store.list_bundled_extracts("csv")
            if not files:
                return None
            imported = self.import_extracts([{"originalName": file["name"], "buffer": file["absolute"].read_bytes()} for file in files])
            for entry in imported["added"]:
                log(f'  ok {entry["filename"]} → {entry["label"]} ({entry["records"]:,} records)')
            for skipped in imported["skipped"]:
                log(f'  !  {skipped["filename"]}: {skipped["error"]}')
            return self.rebuild()
