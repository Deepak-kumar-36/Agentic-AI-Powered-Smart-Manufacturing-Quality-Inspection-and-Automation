import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from app.api import InspectionApi, create_server
from app.policy import DecisionPolicy
from app.persistence import InspectionStore


class _Evidence:
    model_version = "efficientad-s-native-v1"
    score = 0.1


class _Scorer:
    def score(self, _category: str, _image: str | Path) -> _Evidence:
        return _Evidence()


class HttpSmokeTests(unittest.TestCase):
    def test_live_health_and_model_backed_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "sample.png"
            image.write_bytes(b"placeholder")
            store = InspectionStore()
            api = InspectionApi(
                store,
                model=_Scorer(),
                policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
                image_root=directory,
            )
            server = create_server(api, host="127.0.0.1", port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(f"{base}/health/live") as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response)["status"], "ok")
                body = json.dumps({"category": "bottle", "image_path": "sample.png"}).encode()
                request = Request(f"{base}/api/v1/inspections", data=body, method="POST", headers={"Content-Type": "application/json", "Idempotency-Key": "http-smoke"})
                with urlopen(request) as response:
                    payload = json.load(response)
                self.assertEqual(response.status, 201)
                self.assertEqual(payload["outcome"], "PASS")
                self.assertEqual(payload["reason_codes"], ["ACCEPTED_BY_POLICY"])
            finally:
                server.shutdown()
                server.server_close()
                store.close()

    def test_missing_record_returns_json_404(self) -> None:
        store = InspectionStore()
        api = InspectionApi(store)
        server = create_server(api, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with self.assertRaises(Exception) as context:
                urlopen(f"{base}/api/v1/inspections/ins_missing")
            response = context.exception
            self.assertEqual(getattr(response, "status", None), 404)
            self.assertEqual(json.load(response)["error"]["code"], "INSPECTION_NOT_FOUND")
        finally:
            server.shutdown()
            server.server_close()
            store.close()


if __name__ == "__main__":
    unittest.main()
