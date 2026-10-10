import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from squadlink.hub import Hub  # noqa: E402
from squadlink.web import App, serve  # noqa: E402


class WebTest(unittest.TestCase):
    def setUp(self):
        self.hub = Hub()
        self.app = App(self.hub)
        self.httpd = serve(self.app, "127.0.0.1", 0)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.app.stopping = True
        self.app.set_virtual({"enabled": False})
        self.httpd.shutdown()
        self.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return json.loads(r.read())

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_state_and_ack(self):
        self.hub.ingest({"type": "soldier", "node": 2, "boot": 1, "seq": 1, "sos": True}, "real", "p", 0)
        s = self.get("/api/state")
        self.assertIn("2", s["nodes"])
        ev = self.get("/api/events")[0]
        status, body = self.post("/api/events/%d/ack" % ev["id"], {"by": "cmd"})
        self.assertEqual(status, 200)
        self.assertIsNotNone(body["acked_at"])
        self.assertIsNone(body["resolved_at"])
        self.assertEqual(self.post("/api/events/999/ack", {})[0], 404)

    def test_bad_scenario_keeps_running_virtual(self):
        status, body = self.post("/api/virtual", {"scenario": "normal", "speed": 50})
        self.assertEqual(status, 200)
        self.assertTrue(body["running"])
        for bad in ({"scenario": "nope"}, {"scenario": "normal", "nodes": ["x"]},
                    {"scenario": "normal", "nodes": "2"}, {"scenario": "normal", "speed": 0},
                    {"scenario": "normal", "speed": "fast"}, {"scenario": "normal", "loss_rate": 2}):
            status, body = self.post("/api/virtual", bad)
            self.assertEqual(status, 400, bad)
            self.assertTrue(self.app.virtual_status()["running"], bad)

    def test_events_bad_query(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/events?limit=abc")
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(self.get("/api/events?limit=0"), [])

    def test_stream_sends_initial_state(self):
        with urllib.request.urlopen(self.base + "/api/stream", timeout=5) as r:
            self.assertEqual(r.readline().decode().strip(), "event: state")
            data = r.readline().decode()
            self.assertTrue(data.startswith("data: "))
            self.assertIn("nodes", json.loads(data[6:]))


if __name__ == "__main__":
    unittest.main()
