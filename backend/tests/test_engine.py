import json
import shutil
import subprocess
import unittest
from datetime import datetime

from backend.engine.engine import ROOT, evaluate, empty_counts, load_schedule, score_counts
from backend.engine.extracts import read_extract
from backend.engine.rules import build_mapping
from backend.engine.workflows import by_policy, latest_before, derive_as_of


NODE_REFERENCE = """
import fs from 'node:fs';
import path from 'node:path';
import { readExtract } from './server/engine/extracts.js';
import { evaluate } from './server/engine/engine.js';
const ext = process.argv[2];
const files = fs.readdirSync('Claude_Data').filter(name =>
  name.endsWith('.' + ext) && !name.startsWith('SLA_Expected'));
const extracts = await Promise.all(files.map(name =>
  readExtract(fs.readFileSync(path.join('Claude_Data', name)), name)));
process.stdout.write(JSON.stringify({extracts, result: evaluate(extracts)}));
"""


class EngineTests(unittest.TestCase):
    def test_mapping_normalization_and_conflict(self):
        rows = [{"product": " Plan ", "transaction": " Alter  Policy ", "code": "Ul"},
                {"product": "plan", "transaction": "alter policy", "code": "UL"}]
        self.assertEqual(build_mapping(rows), {"plan|alter policy": {"code": "UL", "dependency": None}})
        rows.append({"product": "plan", "transaction": "alter policy", "code": "NUL"})
        with self.assertRaisesRegex(ValueError, "two codes"):
            build_mapping(rows)

    def test_latest_workflow_excludes_future_and_supersedes_earlier(self):
        workflows = [{"policy": "1", "type": " Approval ", "created": datetime(2026, 9, day)} for day in (3, 1, 2)]
        grouped = by_policy(workflows, "approval")
        self.assertEqual(latest_before(grouped["1"], datetime(2026, 9, 2))["created"], datetime(2026, 9, 2))
        self.assertIsNone(latest_before(grouped["1"], datetime(2026, 8, 31)))
        self.assertIsNone(latest_before(grouped["1"], None))

    def test_as_of_majority_and_fallback(self):
        workflows = [{"open": True, "pendingDays": pending, "created": datetime(2026, 9, day)}
                     for day, pending in ((1, 23), (2, 22), (3, 10))]
        self.assertEqual(derive_as_of(workflows, [])["day"], "2026-09-24")
        self.assertEqual(derive_as_of([], [{"records": [{"date": "02/09/2026 10:00:00"}]}])["day"], "2026-09-03")

    def test_rates_exclude_uncompleted_and_unmatched(self):
        definition = load_schedule()["slas"][0]
        counts = {**empty_counts(), "met": 97, "missed": 3, "openPastDeadline": 10, "excluded": 5, "noMatch": 4}
        score = score_counts(definition, counts)
        self.assertEqual(score["status"], "PASS")
        self.assertEqual(score["rateCompleted"], 0.97)
        self.assertEqual(score["rateInclOpen"], 97 / 110)
        self.assertEqual(score_counts(definition, empty_counts())["status"], "NO_DATA")

    def test_empty_set_requires_date(self):
        with self.assertRaisesRegex(ValueError, "extract date"):
            evaluate([])
        result = evaluate([], as_of="2026-09-24")
        self.assertEqual(result["monthly"], [])
        self.assertTrue(all(score["status"] == "NO_DATA" for score in result["totals"]))


class ExtractTests(unittest.TestCase):
    def test_rejects_unknown_columns_and_extension(self):
        with self.assertRaisesRegex(ValueError, "do not match"):
            read_extract(b"a,b,c\n1,2,3\n", "other.csv")
        with self.assertRaisesRegex(ValueError, "Unsupported file type"):
            read_extract(b"", "other.txt")

    def test_bom_quotes_newlines_and_row_numbers(self):
        source = '\ufeffProduct,Policy Number,Transaction Reference,Transaction Type,Status,Transaction Start Date,Transaction Merged Date\r\n"Plan, A",123,"ref""quoted","alter\npolicy",MERGED,01/09/2026,02/09/2026\r\n'
        parsed = read_extract(source.encode("utf-8"), "test.csv")
        self.assertEqual(parsed["headerRow"], 1)
        self.assertEqual(parsed["records"][0]["_row"], 2)
        self.assertEqual(parsed["records"][0]["product"], "Plan, A")
        self.assertEqual(parsed["records"][0]["transaction reference"], 'ref"quoted')
        self.assertEqual(parsed["records"][0]["transaction type"], "alter\npolicy")

    def test_reference_workbook_is_not_an_extract(self):
        workbook = ROOT / "Claude_Data/SLA_Expected_Results.xlsx"
        with self.assertRaisesRegex(ValueError, "expected-results workbook"):
            read_extract(workbook.read_bytes(), workbook.name)


@unittest.skipUnless(shutil.which("node") and (ROOT / "node_modules/exceljs").exists(), "Node and installed JS dependencies required for parity checks")
class FullEngineParityTests(unittest.TestCase):
    def compare_format(self, extension):
        reference = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-", extension],
            input=NODE_REFERENCE, text=True, encoding="utf-8", capture_output=True,
            cwd=ROOT, timeout=120,
        )
        self.assertEqual(reference.returncode, 0, reference.stderr)
        reference = json.loads(reference.stdout)
        extracts = [read_extract(file.read_bytes(), file.name) for file in sorted((ROOT / "Claude_Data").glob(f"*.{extension}"))
                    if not file.name.startswith("SLA_Expected")]
        actual = evaluate(extracts)
        serializable = json.loads(json.dumps(actual, default=lambda value: value.isoformat(timespec="milliseconds") + "Z"))
        self.assertEqual(len(actual["items"]), len(reference["result"]["items"]))
        for index, (result, expected) in enumerate(zip(serializable["items"], reference["result"]["items"])):
            with self.subTest(extension=extension, index=index, sla=result["sla"], key=result["key"]):
                self.assertEqual(result, expected)
        self.assertEqual(serializable, reference["result"])
        self.assertEqual(json.loads(json.dumps(extracts, default=lambda value: value.isoformat(timespec="milliseconds") + "Z")), reference["extracts"])

    def test_csv_matches_javascript(self):
        self.compare_format("csv")

    def test_xlsx_matches_javascript(self):
        self.compare_format("xlsx")
