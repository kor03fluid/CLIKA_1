"""C 검증 → 팀장 관제 서버 전달(squadlink/forward.py): 넘기는 조건과 결과 세기."""

import json
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

from helpers import environment, new_hub

from squadlink.forward import LeadForwarder


def sim_env(seq, **kw):
    return environment(seq=seq, source="simulation", **kw)


def dev_env(seq, **kw):
    return environment(seq=seq, source="device", **kw)


class ForwardRuleTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.fwd = LeadForwarder("http://lead/api/ingest", post=self.post)
        self.hub, self.clock = new_hub()
        self.hub.ingest_hooks.append(self.fwd.offer)

    def post(self, obj):
        self.sent.append(obj)
        return 200, json.dumps({"accepted": True})

    def flush(self):
        while not self.fwd._q.empty():
            self.fwd.send_one(self.fwd._q.get_nowait())

    def test_only_new_valid_virtual_serial_packets_are_forwarded(self):
        self.hub.ingest(sim_env(1), "serial", "COM5")
        self.hub.ingest(sim_env(1), "serial", "COM5")                  # 중복
        self.hub.ingest(dev_env(2), "serial", "COM5")                  # 실측(device)
        self.hub.ingest(sim_env(3), "sim", "virtual")                  # C 서버 가상 노드
        bad = sim_env(4)
        bad["payload"]["humidity_pct"] = 120
        self.hub.ingest(bad, "serial", "COM5")                          # 규격 위반
        self.clock.t += 1
        self.hub.ingest(sim_env(5), "serial", "COM5")
        self.flush()
        self.assertEqual([p["seq"] for p in self.sent], [1, 5])
        st = self.fwd.status()
        self.assertEqual(st["counts"]["accepted"], 2)
        self.assertEqual(st["skipped"]["result:dup"], 1)
        self.assertEqual(st["skipped"]["result:invalid"], 1)
        self.assertEqual(st["skipped"]["input"], 1)
        self.assertGreaterEqual(st["skipped"]["source"], 1)

    def test_warnings_are_not_forwarded(self):
        self.assertEqual(self.fwd.reason_to_skip(sim_env(1), "ok", [], ["고친 값"], "serial"), "spec_warning")

    def test_device_source_can_be_enabled(self):
        f = LeadForwarder("http://x", sources=("simulation", "device"), post=self.post)
        self.assertIsNone(f.reason_to_skip(dev_env(1), "ok", [], [], "serial"))

    def test_rejected_and_failed_are_counted(self):
        answers = iter([(200, json.dumps({"accepted": False, "reason": "out_of_order"})),
                        (400, json.dumps({"error": "미등록 병사 노드"}))])
        f = LeadForwarder("http://x", post=lambda obj: next(answers))
        self.assertEqual(f.send_one(sim_env(1)), "rejected")
        self.assertEqual(f.send_one(sim_env(2)), "rejected")

        def down(obj):
            raise urllib.error.URLError("connection refused")
        g = LeadForwarder("http://x", post=down)
        self.assertEqual(g.send_one(sim_env(3)), "failed")
        st = f.status()
        self.assertEqual(st["counts"]["rejected"], 2)
        self.assertEqual(set(st["rejected"]), {"out_of_order", "미등록 병사 노드"})
        self.assertEqual(g.status()["counts"]["failed"], 1)

    def test_queue_full_does_not_block(self):
        f = LeadForwarder("http://x", queue_max=1, post=self.post)
        self.assertTrue(f.offer(sim_env(1), "ok", [], [], "serial", "COM5"))
        self.assertFalse(f.offer(sim_env(2), "ok", [], [], "serial", "COM5"))
        self.assertEqual(f.status()["counts"]["queue_full"], 1)


class ForwardHttpTest(unittest.TestCase):
    """실제 HTTP로 원래 줄을 그대로 POST하는지."""

    def test_posts_original_json(self):
        got = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers["Content-Length"])
                got.append((self.path, self.headers["Content-Type"], json.loads(self.rfile.read(n))))
                body = b'{"accepted":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            f = LeadForwarder(f"http://127.0.0.1:{httpd.server_address[1]}/api/ingest").start()
            pkt = sim_env(7)
            self.assertTrue(f.offer(pkt, "ok", [], [], "serial", "COM5"))
            self.assertTrue(f.drain(5))
            f.stop()
        finally:
            httpd.shutdown()
        self.assertEqual(got, [("/api/ingest", "application/json", pkt)])
        self.assertEqual(f.status()["counts"]["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
