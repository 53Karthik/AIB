from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .engine.engine import ROOT, load_schedule
from .insights import is_failure
from .pipeline import Pipeline
from .slots import EXTRACT_SLOTS
from .store import is_month_key
from .intelligence import build_intelligence
from .narrative import Narrative
from .assistant import ask_assistant, suggested_questions


def public_entry(entry):
    return {key: value for key, value in entry.items() if key != "stored"}


def create_app(pipeline=None, *, bootstrap=True, narrative=None):
    pipeline = pipeline if pipeline is not None else Pipeline()
    store = pipeline.store
    narrative = narrative if narrative is not None else Narrative(store)

    @asynccontextmanager
    async def lifespan(app):
        if bootstrap and os.environ.get("SKIP_BOOTSTRAP_DATA") != "1" and not (store.read_snapshot() and store.list_months()):
            try:
                await run_in_threadpool(pipeline.rebuild if store.read_extract_index() else pipeline.load_bundled)
            except Exception as error:
                logging.warning("could not load the extract set: %s", error)
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.pipeline = pipeline

    def fail(code, message):
        return JSONResponse({"error": message}, status_code=code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return fail(500, str(error))

    def snapshot_summary():
        snapshot = store.read_snapshot()
        if not snapshot:
            return None
        return {**{key: value for key, value in snapshot.items() if key not in ("totals", "sources")}, "sourceCount": len(snapshot["sources"])}

    def analysis_for(month):
        if not is_month_key(month):
            return None, fail(400, "Invalid reporting month")
        analysis = store.read_analysis(month)
        return (analysis, None) if analysis else (None, fail(404, "No pack for this period"))

    @app.get("/api/bootstrap")
    def get_bootstrap():
        months = []
        for month in store.list_months():
            analysis = store.read_analysis(month) or {}
            months.append({"month": month, "label": analysis.get("label", month), "partial": bool(analysis.get("partial")),
                           "generatedAt": analysis.get("generated_at"), "summary": analysis.get("summary"),
                           "qualityFlags": analysis.get("quality_summary")})
        return {"months": months, "snapshot": snapshot_summary(), "slas": load_schedule()["slas"], "slots": EXTRACT_SLOTS}

    @app.get("/api/extracts")
    def get_extracts():
        return {"extracts": list(map(public_entry, store.read_extract_index())), "slots": pipeline.slot_status(), "snapshot": snapshot_summary()}

    @app.post("/api/extracts")
    async def upload_extracts(request: Request):
        incoming = []
        async with request.form(max_files=12, max_fields=1000, max_part_size=50 * 1024 * 1024) as form:
            for field, file in form.multi_items():
                if not hasattr(file, "filename"):
                    continue
                if field != "files":
                    return fail(400, "Unexpected field")
                buffer = await file.read(50 * 1024 * 1024 + 1)
                if len(buffer) > 50 * 1024 * 1024:
                    return fail(413, "File too large")
                incoming.append({"originalName": file.filename, "buffer": buffer})
        if not incoming:
            return fail(400, "No files received")
        def import_and_rebuild():
            with pipeline.lock:
                result = pipeline.import_extracts(incoming)
                snapshot = pipeline.rebuild() if result["added"] else store.read_snapshot()
                return {**result, "added": list(map(public_entry, result["added"])), "rebuilt": bool(result["added"]), "snapshot": bool(snapshot)}
        return await run_in_threadpool(import_and_rebuild)

    @app.delete("/api/extracts/{identifier}")
    def delete_extract(identifier):
        with pipeline.lock:
            if not pipeline.remove_extract(identifier):
                return fail(404, "Extract not found")
            pipeline.rebuild()
        return {"ok": True}

    @app.post("/api/extracts/rebuild")
    def rebuild():
        snapshot = pipeline.rebuild()
        return {"ok": True, "months": len(snapshot["months"])} if snapshot else fail(400, "No extracts loaded")

    @app.post("/api/extracts/bundled")
    def bundled():
        snapshot = pipeline.load_bundled()
        return {"ok": True, "months": len(snapshot["months"])} if snapshot else fail(404, "No delivered extracts found in Claude_Data/")

    @app.get("/api/analysis/{month}")
    def get_analysis(month):
        analysis, error = analysis_for(month)
        if error is not None:
            return error
        return {**{key: value for key, value in analysis.items() if key != "items"},
                "exceptions": [item for item in analysis["items"] if is_failure(item)], "itemCount": len(analysis["items"])}

    @app.get("/api/items/{month}")
    def get_items(month, request: Request):
        analysis, error = analysis_for(month)
        if error is not None:
            return error
        sla, outcome = request.query_params.get("sla") or None, request.query_params.get("outcome") or None
        definition = next((definition for definition in load_schedule()["slas"] if definition["id"] == sla), {})
        sla_ids = definition.get("parts", [sla]) if sla else None
        items = [item for item in analysis["items"] if (sla_ids is None or item["sla"] in sla_ids) and (not outcome or item["outcome"] == outcome)]
        return {"month": month, "sla": sla, "outcome": outcome, "count": len(items), "items": items}

    @app.get("/api/intelligence")
    def get_intelligence(request: Request):
        scope = request.query_params.get("scope") or "all"
        if scope != "all" and not is_month_key(scope):
            return fail(400, "Invalid scope")
        intel = build_intelligence(store, scope)
        if intel["empty"]:
            return {**intel, "narrative": None, "narrativeStatus": narrative.status()}
        return {**intel, "narrative": narrative.generate(intel, refresh=request.query_params.get("refresh") == "1"),
                "narrativeStatus": narrative.status(), "suggestedQuestions": suggested_questions(intel)}

    @app.post("/api/intelligence/ask")
    async def ask(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return fail(400, "Invalid JSON")
        if not isinstance(body, dict):
            return fail(400, "Invalid JSON")
        scope = str(body.get("scope") or "all")
        question = str(body.get("question") or "")
        if scope != "all" and not is_month_key(scope):
            return fail(400, "Invalid scope")
        if not question.strip():
            return fail(400, "Ask a question about the report")
        if len(question) > 400:
            return fail(400, "Question is too long")
        def answer():
            intel = build_intelligence(store, scope)
            if intel["empty"]:
                return fail(400, "No history to answer from yet")
            return ask_assistant(intel, question, narrative)
        return await run_in_threadpool(answer)

    dist = ROOT / "dist"
    if dist.is_dir():
        static = StaticFiles(directory=dist)
        @app.get("/{path:path}")
        async def frontend(path, request: Request):
            if path.startswith("api/"):
                return fail(404, "Not found")
            try:
                return await static.get_response(path, request.scope)
            except Exception as error:
                if getattr(error, "status_code", None) != 404:
                    raise
                return FileResponse(dist / "index.html")
    return app
