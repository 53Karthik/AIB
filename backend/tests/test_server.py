import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

from backend.engine.engine import ROOT


class ServerTests(unittest.TestCase):
    def test_python_entrypoint_serves_api_and_built_react(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            process = subprocess.Popen([sys.executable, "-m", "backend.server"], cwd=ROOT,
                                       env={**os.environ, "HOST": "127.0.0.1", "PORT": str(port),
                                            "DATA_DIR": directory, "SKIP_BOOTSTRAP_DATA": "1"},
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 20
                response = None
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), "Python server exited before becoming ready")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/bootstrap", timeout=1) as stream:
                            response = json.load(stream)
                        break
                    except OSError:
                        time.sleep(0.1)
                self.assertIsNotNone(response, "Python server did not become ready")
                self.assertEqual(response["months"], [])
                self.assertEqual(len(response["slots"]), 5)
                if (ROOT / "dist/index.html").exists():
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as stream:
                        self.assertEqual(stream.read(), (ROOT / "dist/index.html").read_bytes())
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
