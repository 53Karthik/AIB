import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from backend.engine.engine import ROOT
from backend.pipeline import Pipeline
from backend.slots import slots_of
from backend.store import Store


NODE_PIPELINE = """
import { rebuild } from './server/pipeline.js';
import { listMonths, readAnalysis } from './server/store.js';
const snapshot = await rebuild();
process.stdout.write(JSON.stringify({ snapshot, analyses: listMonths().map(readAnalysis) }));
"""


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)

    def test_round_trip_and_clear(self):
        self.assertEqual(self.store.read_extract_index(), [])
        self.assertIsNone(self.store.read_snapshot())
        self.store.write_extract_index([{"id": "sample"}])
        self.assertEqual(self.store.read_extract_index(), [{"id": "sample"}])
        stored = self.store.save_extract_file("sample", "source.csv", b"source")
        self.assertEqual(self.store.read_extract_file(stored), b"source")
        self.store.delete_extract_file(stored)
        self.store.write_analysis("2026-09", {"label": "September"})
        self.store.write_analysis("2026-08", {"label": "August"})
        self.assertEqual(self.store.list_months(), ["2026-09", "2026-08"])
        self.assertEqual(self.store.read_analysis("2026-09"), {"label": "September"})
        self.store.write_snapshot({"as_of": "2026-09-24"})
        self.assertEqual(self.store.read_snapshot(), {"as_of": "2026-09-24"})
        self.store.clear_analyses()
        self.store.clear_snapshot()
        self.assertEqual(self.store.list_months(), [])
        self.assertIsNone(self.store.read_snapshot())

    def test_rejects_path_traversal(self):
        for name in ("../outside.csv", "..\\outside.csv", "C:\\outside.csv", "..", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.read_extract_file(name)
        with self.assertRaises(ValueError):
            self.store.write_analysis("../outside", {})

    def test_bad_json_falls_back(self):
        self.store.extracts_dir.mkdir()
        (self.store.extracts_dir / "_index.json").write_text("invalid", encoding="utf-8")
        self.assertEqual(self.store.read_extract_index(), [])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name) / "python")
        self.pipeline = Pipeline(self.store, clock=lambda: "2026-10-06T00:00:00.000Z")

    def file(self, extension="csv"):
        path = next((ROOT / "Claude_Data").glob(f"EBQ*.{extension}"))
        return {"originalName": path.name, "buffer": path.read_bytes()}

    def test_upload_replacement_skip_and_removal(self):
        first = self.pipeline.import_extracts([self.file()])
        old = first["added"][0]
        second = self.pipeline.import_extracts([self.file("xlsx"), {"originalName": "bad.txt", "buffer": b"bad"}])
        self.assertEqual(second["replaced"], [old["filename"]])
        self.assertEqual(len(second["skipped"]), 1)
        self.assertEqual(len(self.store.read_extract_index()), 1)
        self.assertFalse((self.store.extracts_dir / old["stored"]).exists())
        self.assertTrue(self.pipeline.slot_status()[0]["present"])
        self.assertTrue(self.pipeline.remove_extract(second["added"][0]["id"]))
        self.assertFalse(self.pipeline.remove_extract("missing"))
        self.assertIsNone(self.pipeline.rebuild())
        self.assertEqual(self.store.list_months(), [])

    def test_mixed_workflow_slots(self):
        self.assertEqual(slots_of({"kind": "workflow", "records": [{"close date": "nan"}, {"close date": "01/09/2026"}]}),
                         ["workflow-open", "workflow-closed"])
        self.assertEqual(slots_of({"kind": "workflow", "records": []}), ["workflow-open"])

    def test_failed_rebuild_preserves_existing_packs(self):
        self.pipeline.import_extracts([self.file()])
        self.pipeline.rebuild()
        before = self.store.read_analysis("2026-08")
        entry = self.store.read_extract_index()[0]
        (self.store.extracts_dir / entry["stored"]).write_bytes(b"bad")
        with self.assertRaises(ValueError):
            self.pipeline.rebuild()
        self.assertEqual(self.store.read_analysis("2026-08"), before)

    @unittest.skipUnless(shutil.which("node") and (ROOT / "node_modules/exceljs").exists(), "Node and npm dependencies required")
    def test_all_packs_and_snapshot_match_javascript(self):
        snapshot = self.pipeline.load_bundled()
        javascript_dir = Path(self.temporary.name) / "javascript"
        javascript_dir.mkdir()
        shutil.copytree(self.store.extracts_dir, javascript_dir / "extracts")
        reference = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=NODE_PIPELINE,
                                   text=True, encoding="utf-8", capture_output=True, cwd=ROOT,
                                   env={**os.environ, "DATA_DIR": str(javascript_dir)}, timeout=120)
        self.assertEqual(reference.returncode, 0, reference.stderr)
        expected = json.loads(reference.stdout)
        actual = {"snapshot": snapshot, "analyses": [self.store.read_analysis(month) for month in self.store.list_months()]}
        for document in [expected["snapshot"], *expected["analyses"], actual["snapshot"], *actual["analyses"]]:
            document.pop("generated_at")
        self.assertEqual(actual["snapshot"], expected["snapshot"])
        self.assertEqual(len(actual["analyses"]), 22)
        for analysis, oracle in zip(actual["analyses"], expected["analyses"]):
            with self.subTest(month=analysis["reporting_month"]):
                self.assertEqual(analysis, oracle)
