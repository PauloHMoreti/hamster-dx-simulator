"""Testes de ponta a ponta da API (somente biblioteca padrão).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hamster_sim.config import AppConfig  # noqa: E402
from hamster_sim.server import SimulatorServer  # noqa: E402
from hamster_sim.service import BiometricService  # noqa: E402

T1 = "AAAAAZCXZDSfe34t4fSIMULATED_FINGERPRINT_TEMPLATE_USER_01_RIGHT_THUMB"
T2 = "AAAAAZCXZDSfe34t4fSIMULATED_FINGERPRINT_TEMPLATE_USER_01_RIGHT_INDEX"


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = AppConfig(capture_delay_ms=10, timeout_delay_ms=50, port=0)
        self.svc = BiometricService(self.cfg)
        self.server = SimulatorServer(self.svc)
        self.server.start("127.0.0.1", 0)
        host, port = self.server.address
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.stop()

    def call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read()), resp.headers
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read()), err.headers

    # ------------------------------------------------------------------ rotas
    def test_root(self):
        status, body, headers = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"name": "Hamster DX Simulator", "status": "running", "success": True})
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_capture_hash(self):
        status, body, _ = self.call("GET", "/apiservice/capture-hash")
        self.assertEqual(status, 200)
        self.assertEqual(body["template"], T1)
        self.assertEqual(body["fingers-id"], [1])
        self.assertEqual(body["quality-FIR"], 95)
        self.assertNotIn("images", body)

        status, body, _ = self.call("GET", "/apiservice/capture-hash?img=true")
        self.assertTrue(body["images"][0].startswith("iVBORw0KGgo"))  # PNG em base64

    def test_scenarios(self):
        status, body, _ = self.call("GET", "/apiservice/capture-hash?scenario=lowQuality")
        self.assertEqual((status, body["quality-FIR"]), (200, 18))
        status, body, _ = self.call("GET", "/apiservice/capture-hash?scenario=disconnected")
        self.assertEqual((status, body["message"]), (400, "Error on Capture: DEVICE_NOT_FOUND"))
        started = time.monotonic()
        status, body, _ = self.call("GET", "/apiservice/capture-for-verify?scenario=timeout")
        self.assertEqual((status, body["message"]), (400, "Timeout"))
        self.assertGreaterEqual(time.monotonic() - started, 0.04)
        status, body, _ = self.call("GET", "/apiservice/capture-hash?scenario=naoexiste")
        self.assertEqual(status, 200)  # cai no cenário padrão

    def test_force_scenario(self):
        self.cfg.default_scenario = "sdkError"
        self.cfg.force_scenario = True
        status, body, _ = self.call("GET", "/apiservice/capture-hash?scenario=success")
        self.assertEqual((status, body["message"]), (400, "Error on Capture: SDK_NOT_INITIALIZED"))

    def test_match_one_on_one(self):
        status, body, _ = self.call("POST", "/apiservice/match-one-on-one", {"template": T1})
        self.assertEqual(body, {"message": "Fingerprint matches", "success": True})
        status, body, _ = self.call("POST", "/apiservice/match-one-on-one?img=1", {"template": T2})
        self.assertEqual((status, body["success"]), (200, False))
        self.assertIn("image", body)
        status, body, _ = self.call("POST", "/apiservice/match-one-on-one", {})
        self.assertEqual((status, body["message"]), (400, "Template is required"))

    def test_memory_and_identification(self):
        status, body, _ = self.call("GET", "/apiservice/identification")
        self.assertEqual(body, {"message": "Fingerprint match not found", "id": 0, "success": False})
        status, body, _ = self.call("POST", "/apiservice/load-to-memory", [{"id": 7, "template": T1}, {"id": 8, "template": T2}])
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/apiservice/total-in-memory")[1], {"total": 2, "success": True})
        status, body, _ = self.call("GET", "/apiservice/identification")
        self.assertEqual(body, {"message": "Fingerprint match found", "id": 7, "success": True})
        self.call("GET", "/apiservice/delete-all-from-memory")
        self.assertEqual(self.call("GET", "/apiservice/total-in-memory")[1]["total"], 0)
        status, body, _ = self.call("POST", "/apiservice/load-to-memory", [{"id": 1}])
        self.assertEqual((status, body["message"]), (400, "Error on AddFIR: invalid template"))
        status, body, _ = self.call("POST", "/apiservice/load-to-memory", {"x": 1})
        self.assertEqual((status, body["message"]), (400, "Invalid templates array"))

    def test_device_and_join(self):
        self.assertEqual(self.call("GET", "/apiservice/device-unique-id")[1]["serial"], "MOCK-HAMSTER-DX-000001")
        self.assertEqual(self.call("GET", "/apiservice/device-unique-id?scenario=disconnected")[0], 400)
        status, body, _ = self.call("POST", "/apiservice/join-templates", [{"template": "a"}, {"template": "b"}])
        # mesmo resultado do Node: crypto.createHash("sha256").update("a|b").digest("base64")
        self.assertEqual(body["template"], "MOCK_JOINED_" + "DquKCjOAq/TH0fsLQ7Zqr7tkpLlT5OstzMpXlGGRLQw=")
        self.assertEqual(self.call("POST", "/apiservice/join-templates", [{"template": "a"}])[0], 400)

    def test_mock_endpoints(self):
        status, body, _ = self.call("GET", "/apiservice/mock/fingerprints")
        self.assertEqual(len(body["fingerprints"]), 3)
        self.assertNotIn("template", body["fingerprints"][0])
        status, body, _ = self.call("POST", "/apiservice/mock/fingerprints/2/select")
        self.assertEqual(body, {"message": "Mock fingerprint 2 selected", "success": True})
        self.assertEqual(self.call("GET", "/apiservice/capture-hash")[1]["template"], T2)
        self.assertEqual(self.call("POST", "/apiservice/mock/fingerprints/99/select")[0], 404)

    def test_404_and_bad_json(self):
        self.assertEqual(self.call("GET", "/apiservice/nada")[1], {"message": "Endpoint not found", "success": False})
        req = urllib.request.Request(self.base + "/apiservice/load-to-memory", data=b"{oops", method="POST")
        req.add_header("Content-Type", "application/json")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)

    def test_cors_preflight(self):
        req = urllib.request.Request(self.base + "/apiservice/match-one-on-one", method="OPTIONS")
        req.add_header("Access-Control-Request-Headers", "content-type")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers["Access-Control-Allow-Headers"], "content-type")

    # ------------------------------------------------------------- modo manual
    def test_manual_mode_release_and_cancel(self):
        self.cfg.capture_mode = "manual"
        self.cfg.manual_timeout_ms = 5000
        results = []

        def worker():
            results.append(self.call("GET", "/apiservice/capture-hash"))

        t = threading.Thread(target=worker)
        t.start()
        self._wait_pending(1)
        self.svc.release_finger()
        t.join(5)
        self.assertEqual(results[0][0], 200)

        t = threading.Thread(target=worker)
        t.start()
        self._wait_pending(1)
        self.svc.cancel_pending()
        t.join(5)
        self.assertEqual(results[1][1]["message"], "Capture cancelled")

        self.cfg.manual_timeout_ms = 50
        self.assertEqual(self.call("GET", "/apiservice/capture-hash")[1]["message"], "Timeout")
        # desconectado responde na hora, sem esperar o dedo
        self.cfg.manual_timeout_ms = 5000
        started = time.monotonic()
        self.assertEqual(self.call("GET", "/apiservice/capture-hash?scenario=disconnected")[0], 400)
        self.assertLess(time.monotonic() - started, 1)

    def test_auto_mode_release_early(self):
        self.cfg.capture_delay_ms = 10000
        results = []
        t = threading.Thread(target=lambda: results.append(self.call("GET", "/apiservice/capture-hash")))
        started = time.monotonic()
        t.start()
        self._wait_pending(1)
        self.svc.release_finger()
        t.join(5)
        self.assertEqual(results[0][0], 200)
        self.assertLess(time.monotonic() - started, 3)

    def _wait_pending(self, n: int) -> None:
        deadline = time.monotonic() + 5
        while self.svc.pending_captures < n and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.svc.pending_captures, n)


if __name__ == "__main__":
    unittest.main()
