import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.engine.engine import ROOT
from backend.intelligence import build_intelligence
from backend.pipeline import Pipeline
from backend.store import Store


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)
        self.pipeline = Pipeline(self.store)
        self.client = TestClient(create_app(self.pipeline, bootstrap=False), raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def test_empty_bootstrap_and_extracts(self):
        response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["months"], [])
        self.assertIsNone(response.json()["snapshot"])
        self.assertEqual(len(response.json()["slots"]), 5)
        self.assertEqual(self.client.get("/api/extracts").json()["extracts"], [])
        self.assertEqual(build_intelligence(self.store)["empty"], True)

    def test_errors_keep_error_field(self):
        for route, status, message in (("/api/analysis/invalid", 400, "Invalid reporting month"),
                                       ("/api/items/2026-13", 400, "Invalid reporting month"),
                                       ("/api/analysis/2026-09", 404, "No pack for this period")):
            response = self.client.get(route)
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json(), {"error": message})
        self.assertEqual(self.client.post("/api/extracts").json(), {"error": "No files received"})
        self.assertEqual(self.client.post("/api/extracts/rebuild").status_code, 400)
        self.assertEqual(self.client.delete("/api/extracts/missing").status_code, 404)

    def test_upload_skip_and_public_metadata(self):
        skipped = self.client.post("/api/extracts", files=[("files", ("bad.txt", b"bad"))]).json()
        self.assertFalse(skipped["rebuilt"])
        self.assertEqual(len(skipped["skipped"]), 1)
        file = next((ROOT / "Claude_Data").glob("EBQ*.csv"))
        response = self.client.post("/api/extracts", files=[("files", (file.name, file.read_bytes()))])
        self.assertEqual(response.status_code, 200, response.text)
        uploaded = response.json()
        self.assertTrue(uploaded["rebuilt"])
        self.assertNotIn("stored", uploaded["added"][0])
        self.assertNotIn("stored", self.client.get("/api/extracts").json()["extracts"][0])
        self.assertEqual(self.client.delete(f'/api/extracts/{uploaded["added"][0]["id"]}').json(), {"ok": True})

    def test_items_and_exceptions(self):
        items = [{"sla": sla, "outcome": outcome} for sla, outcome in
                 (("23B_UL_S1", "MET"), ("23B_UL_S2", "MISSED"), ("23A", "OPEN - PAST DEADLINE"))]
        self.store.write_analysis("2026-09", {"items": items, "label": "September 2026"})
        analysis = self.client.get("/api/analysis/2026-09").json()
        self.assertNotIn("items", analysis)
        self.assertEqual(analysis["itemCount"], 3)
        self.assertEqual(len(analysis["exceptions"]), 2)
        response = self.client.get("/api/items/2026-09?sla=23B_UL&outcome=MISSED").json()
        self.assertEqual(response["items"], [items[1]])
        self.assertEqual(response["count"], 1)


@unittest.skipUnless(shutil.which("node") and (ROOT / "node_modules/exceljs").exists(), "Node and npm dependencies required")
class IntelligenceParityTests(unittest.TestCase):
    def test_all_and_scoped_history_match_javascript(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            store = Store(directory)
            Pipeline(store).load_bundled()
            scopes = ["all", "2026-08", "2025-01", "2024-01"]
            script = """
import { buildIntelligence } from './server/intelligence.js';
const scopes = ['all', '2026-08', '2025-01', '2024-01'];
process.stdout.write(JSON.stringify(scopes.map(scope => buildIntelligence({scope}))));
"""
            reference = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=script,
                                       text=True, encoding="utf-8", capture_output=True, cwd=ROOT,
                                       env={**os.environ, "DATA_DIR": directory}, timeout=120)
            self.assertEqual(reference.returncode, 0, reference.stderr)
            for scope, expected in zip(scopes, json.loads(reference.stdout)):
                with self.subTest(scope=scope):
                    self.assertEqual(build_intelligence(store, scope), expected)
