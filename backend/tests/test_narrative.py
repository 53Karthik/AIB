import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.assistant import compose_answer, suggested_questions, ask_assistant
from backend.engine.engine import ROOT
from backend.intelligence import build_intelligence
from backend.narrative import Narrative, brief, compose_narrative, unsupported_figures, contradicted_claims
from backend.pipeline import Pipeline
from backend.store import Store


class NarrativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        cls.store = Store(cls.temporary.name)
        Pipeline(cls.store).load_bundled()
        cls.intel = build_intelligence(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def service(self, configured=False, text_call=None):
        service = Narrative(self.store, text_call=text_call)
        service.status = Mock(return_value={"bedrockConfigured": configured, "credentialSource": "none",
                                           "model": "amazon.nova-pro-v1:0", "region": "us-east-1"})
        return service

    def test_figure_and_claim_guards(self):
        self.assertEqual(unsupported_figures("23E ran at 94.29% with 855 overdue", {"rate": "94.29%", "count": 855, "sla": "23E"}), [])
        self.assertEqual(unsupported_figures("23E ran at 93.10%", {"rate": "94.29%", "sla": "23E"}), ["93.10"])
        august = build_intelligence(self.store, "2026-08")
        self.assertTrue(contradicted_claims("23C failed in August 2026.", august))
        self.assertEqual(contradicted_claims("23C met target while 23E missed it.", august), [])

    def test_cache_refresh_and_provider_change(self):
        service = self.service()
        first = service.generate(self.intel, refresh=True)
        self.assertEqual(first["source"], "rules")
        self.assertTrue(service.generate(self.intel)["cached"])
        model = self.service(True, lambda **kwargs: "23C met target.")
        self.assertEqual(model.generate(self.intel, refresh=True)["source"], "bedrock")
        self.assertTrue(model.generate(self.intel)["cached"])

    def test_model_guard_failure_and_network_fallback(self):
        for text in ("23C failed.", "There were 987654321 missed items.", ""):
            with self.subTest(text=text):
                result = self.service(True, lambda **kwargs: text).generate(self.intel, refresh=True)
                self.assertEqual(result["source"], "rules")
                self.assertIn("fallbackReason", result)
        service = self.service(True, Mock(side_effect=RuntimeError("model unavailable")))
        self.assertEqual(service.generate(self.intel, refresh=True)["fallbackReason"], "model unavailable")

    def test_question_guard_and_success(self):
        service = self.service(True, lambda **kwargs: "23C met target.")
        self.assertEqual(ask_assistant(self.intel, "How did 23C perform?", service)["source"], "bedrock")
        service.text_call = lambda **kwargs: "987654321 missed items."
        result = ask_assistant(self.intel, "How did 23C perform?", service)
        self.assertEqual(result["source"], "rules")
        self.assertIn("fallbackReason", result)
        self.assertIn("23C", result["matchedSla"])

    def test_bedrock_nova_and_anthropic_adapters(self):
        service = self.service(True)
        client = Mock()
        client.converse.return_value = {"output": {"message": {"content": [{"text": " Nova answer "}]}}}
        with patch("boto3.client", return_value=client):
            self.assertEqual(service.bedrock_text(system="rules", user="facts"), "Nova answer")
        self.assertEqual(client.converse.call_args.kwargs["modelId"], "amazon.nova-pro-v1:0")
        self.assertEqual(client.converse.call_args.kwargs["inferenceConfig"]["maxTokens"], 1400)
        service.status.return_value["model"] = "anthropic.claude-test"
        client.invoke_model.return_value = {"body": Mock(read=lambda: json.dumps({"content": [{"type": "text", "text": "Claude answer"}]}))}
        with patch("boto3.client", return_value=client):
            self.assertEqual(service.bedrock_text(system="rules", user="facts", max_tokens=500), "Claude answer")
        body = json.loads(client.invoke_model.call_args.kwargs["body"])
        self.assertEqual(body["anthropic_version"], "bedrock-2023-05-31")
        self.assertEqual(body["max_tokens"], 500)

    def test_intelligence_endpoints(self):
        client = TestClient(create_app(Pipeline(self.store), bootstrap=False, narrative=self.service()))
        with client:
            response = client.get("/api/intelligence")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["narrative"]["source"], "rules")
            self.assertEqual(response.json()["suggestedQuestions"], suggested_questions(self.intel))
            response = client.post("/api/intelligence/ask", json={"question": "How did 23C perform?"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["answer"], compose_answer(self.intel, "How did 23C perform?"))
            for body, message in (({"question": ""}, "Ask a question about the report"),
                                  ({"question": "x" * 401}, "Question is too long"),
                                  ({"scope": "invalid", "question": "hi"}, "Invalid scope"),
                                  ({"scope": "2024-01", "question": "hi"}, "No history to answer from yet")):
                result = client.post("/api/intelligence/ask", json=body)
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json(), {"error": message})
            self.assertEqual(client.get("/api/intelligence?scope=invalid").status_code, 400)
            self.assertIsNone(client.get("/api/intelligence?scope=2024-01").json()["narrative"])

    @unittest.skipUnless(shutil.which("node") and (ROOT / "node_modules/exceljs").exists(), "Node and npm dependencies required")
    def test_rules_text_and_facts_match_javascript(self):
        questions = ["Why did 23C fail?", "How did 23A perform?", "Explain withdrawals", "What about EFT?", "How many items are open past deadline?", "Explain step 1", "Explain step 3", "Explain non-unit-linked alterations"]
        script = """
import { buildIntelligence } from './server/intelligence.js';
import { brief, composeNarrative } from './server/narrative.js';
import { composeAnswer, suggestedQuestions } from './server/assistant.js';
const input = JSON.parse(process.argv[2]);
const results = ['all', '2026-08', '2025-01'].map(scope => {
  const intel = buildIntelligence({scope});
  return {brief: brief(intel), narrative: composeNarrative(intel),
    questions: suggestedQuestions(intel), answers: input.map(q => composeAnswer(intel, q))};
});
process.stdout.write(JSON.stringify(results));
"""
        reference = subprocess.run([shutil.which("node"), "--input-type=module", "-", json.dumps(questions)], input=script,
                                   text=True, encoding="utf-8", capture_output=True, cwd=ROOT,
                                   env={**os.environ, "DATA_DIR": str(self.store.data_dir)}, timeout=120)
        self.assertEqual(reference.returncode, 0, reference.stderr)
        for scope, expected in zip(("all", "2026-08", "2025-01"), json.loads(reference.stdout)):
            intel = build_intelligence(self.store, scope)
            with self.subTest(scope=scope):
                self.assertEqual(brief(intel), expected["brief"])
                self.assertEqual(compose_narrative(intel), expected["narrative"])
                self.assertEqual(suggested_questions(intel), expected["questions"])
                self.assertEqual([compose_answer(intel, question) for question in questions], expected["answers"])
