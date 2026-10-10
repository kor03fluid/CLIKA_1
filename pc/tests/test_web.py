import http.client
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from helpers import event, status

from squadlink.hub import Hub
from squadlink.web import App, serve

SOS_ID = "halo_01:boot_a1:sos:1"
SOS_PATH = "/api/events/" + urllib.parse.quote(SOS_ID, safe="")


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

    def raw_post(self, path, body, headers):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        c.request("POST", path, body, headers)
        r = c.getresponse()
        data = r.read()
        hdrs = dict(r.getheaders())
        c.close()
        return r.status, (json.loads(data) if data else None), hdrs

    def test_state_and_event_ack_by_event_id(self):
        self.hub.ingest(status(seq=1), "serial", "p")
        self.hub.ingest(event(seq=2), "serial", "p")
        s = self.get("/api/state")
        self.assertEqual(s["soldiers"][0]["connection_state"], "connected")
        self.assertEqual(s["soldiers"][0]["active_event_ids"], [SOS_ID])
        code, body = self.post(SOS_PATH + "/ack", {"by": "cmd"})
        self.assertEqual((code, body["event_state"], body["acknowledged_by"]), (200, "acknowledged", "cmd"))
        # ":"를 인코딩하지 않아도 된다
        code, body = self.post(f"/api/events/{SOS_ID}/resolve", {})
        self.assertEqual((code, body["event_state"]), (200, "resolved"))
        self.assertEqual(self.post("/api/events/nope/ack", {})[0], 404)
        self.assertEqual(self.post(SOS_PATH + "/ack", {"by": 5})[0], 400)

    def test_roster_and_env_nodes(self):
        roster = self.get("/api/roster")
        self.assertEqual([r["assigned_node_id"] for r in roster[:3]], ["halo_01", "halo_02", None])
        code, body = self.post("/api/roster", {"soldier_id": "soldier_03", "assigned_node_id": "halo_03",
                                               "name": "3번"})
        self.assertEqual((code, body["assigned_node_id"]), (200, "halo_03"))
        self.assertEqual(self.post("/api/roster", {"soldier_id": "soldier_04", "assigned_node_id": "halo_03"})[0], 400)
        self.assertEqual(self.post("/api/roster", {"soldier_id": "nobody", "assigned_node_id": None})[0], 400)
        code, body = self.post("/api/env_nodes", {"node_id": "env_01", "location_name": "북쪽 출입구"})
        self.assertEqual(code, 200)
        self.assertEqual(self.get("/api/state")["environment_nodes"][0]["location_name"], "북쪽 출입구")

    def test_bad_virtual_config_keeps_running_virtual(self):
        code, body = self.post("/api/virtual", {"scenario": "normal", "speed": 50})
        self.assertEqual(code, 200)
        self.assertTrue(body["running"])
        for bad in ({"scenario": "nope"}, {"scenario": "normal", "nodes": ["halo_09"]},
                    {"scenario": "normal", "nodes": [2]}, {"scenario": "normal", "nodes": "halo_02"},
                    {"scenario": "normal", "speed": 0}, {"scenario": "normal", "speed": "fast"},
                    {"scenario": "normal", "loss_rate": 2}):
            code, body = self.post("/api/virtual", bad)
            self.assertEqual(code, 400, bad)
            self.assertTrue(self.app.virtual_status()["running"], bad)

    def test_virtual_start_stop_reaches_state_stream(self):
        # 가상 실행 여부는 허브 데이터가 아니므로, 시작·중지 때 버전이 올라야 SSE가 새 상태를 보낸다
        v0 = self.hub.version
        self.app.set_virtual({"scenario": "normal", "speed": 1})
        self.assertGreater(self.hub.version, v0)
        self.assertTrue(json.loads(self.app.state_json())["virtual"]["running"])
        v1 = self.hub.version
        self.app.set_virtual({"enabled": False})
        self.assertGreater(self.hub.version, v1)
        self.assertFalse(json.loads(self.app.state_json())["virtual"]["running"])

    def test_write_requests_need_json_and_allowed_origin(self):
        self.hub.ingest(event(seq=1), "serial", "p")
        host = "127.0.0.1:%d" % self.httpd.server_address[1]
        js = {"Content-Type": "application/json"}
        self.assertEqual(self.raw_post(SOS_PATH + "/resolve", "{}", {"Content-Type": "text/plain"})[0], 415)
        code, _, _ = self.raw_post(SOS_PATH + "/resolve", "{}", dict(js, Origin="http://evil.example"))
        self.assertEqual(code, 403)
        self.assertEqual(self.hub.list_events()[0]["event_state"], "open")
        self.assertEqual(self.raw_post(SOS_PATH + "/ack", "{}", dict(js, Origin="http://" + host))[0], 200)
        self.app.allow_origins = {"http://localhost:5173"}
        code, _, hdrs = self.raw_post(SOS_PATH + "/resolve", "{}", dict(js, Origin="http://localhost:5173"))
        self.assertEqual(code, 200)
        self.assertEqual(hdrs.get("Access-Control-Allow-Origin"), "http://localhost:5173")

    def test_dns_rebinding_host_is_not_same_origin(self):
        # 남의 도메인이 이 서버를 가리키게 해도(같은 Origin·Host) 쓰기는 막는다. IP·localhost·지정한 이름만 허용
        self.hub.ingest(event(seq=1), "serial", "p")
        port = self.httpd.server_address[1]
        js = {"Content-Type": "application/json"}
        for name in ("evil.example", "mylaptop"):
            host = "%s:%d" % (name, port)
            code, _, _ = self.raw_post(SOS_PATH + "/ack", "{}", dict(js, Origin="http://" + host, Host=host))
            self.assertEqual(code, 403, name)
        self.app.allow_hosts = {"mylaptop"}
        host = "mylaptop:%d" % port
        self.assertEqual(self.raw_post(SOS_PATH + "/ack", "{}", dict(js, Origin="http://" + host, Host=host))[0], 200)
        for host in ("localhost:%d" % port, "[::1]:%d" % port, "squad.local:%d" % port):
            code, _, _ = self.raw_post(SOS_PATH + "/ack", "{}", dict(js, Origin="http://" + host, Host=host))
            self.assertEqual(code, 200, host)

    def test_chunked_and_bad_unicode_bodies_are_rejected(self):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        c.putrequest("POST", "/api/virtual")
        c.putheader("Content-Type", "application/json")
        c.putheader("Transfer-Encoding", "chunked")
        c.endheaders()
        body = b'{"enabled": false}'
        c.send(b"%x\r\n%s\r\n0\r\n\r\n" % (len(body), body))
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(r.status, 411)
        self.assertFalse(self.app.virtual_status()["running"])  # 빈 본문(기본 enabled)으로 시작하지 않음
        raw = '{"soldier_id": "soldier_01", "assigned_node_id": "halo_01", "name": "\\ud83d"}'
        code, _, _ = self.raw_post("/api/roster", raw, {"Content-Type": "application/json"})
        self.assertEqual(code, 400)
        self.assertIsNone(self.hub.roster["soldier_01"].get("name"))
        self.assertEqual(self.get("/api/state")["schema_version"], "1.0")  # 상태 출력은 계속 된다

    def test_preflight_only_for_allowed_origins(self):
        def preflight(origin, method="POST"):
            req = urllib.request.Request(self.base + "/api/cmd", method="OPTIONS", headers={
                "Origin": origin, "Access-Control-Request-Method": method})
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.headers.get("Access-Control-Allow-Origin")
        self.assertIsNone(preflight("http://evil.example"))
        self.assertEqual(preflight("http://evil.example", "GET"), "*")
        self.app.allow_origins = {"http://localhost:5173"}
        self.assertEqual(preflight("http://localhost:5173"), "http://localhost:5173")

    def test_malformed_requests_get_error_responses(self):
        js = {"Content-Type": "application/json"}
        self.assertEqual(self.raw_post("/api/virtual", "{}", dict(js, **{"Content-Length": "abc"}))[0], 400)
        for body in ('{"scenario":"normal","speed":1e400}', '{"scenario":"normal","speed":Infinity}',
                     '[1,2]', '{bad'):
            self.assertEqual(self.raw_post("/api/virtual", body, js)[0], 400, body)
        self.assertFalse(self.app.virtual_status()["running"])

    def test_events_bad_query(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/events?limit=abc")
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(self.get("/api/events?limit=0"), [])

    def test_state_json_is_shared_until_hub_changes(self):
        a = self.app.state_json()
        self.assertIs(self.app.state_json(), a)
        self.hub.ingest(status(seq=1), "serial", "p")
        b = self.app.state_json()
        self.assertIsNot(b, a)
        self.assertIn('"halo_01"', b)
        version, built, text = self.app._state_cache
        self.app._state_cache = (version, built - 10, text)
        self.assertIsNot(self.app.state_json(), text)

    def test_stream_sends_initial_state(self):
        with urllib.request.urlopen(self.base + "/api/stream", timeout=5) as r:
            self.assertEqual(r.readline().decode().strip(), "event: state")
            data = r.readline().decode()
            self.assertTrue(data.startswith("data: "))
            self.assertEqual(len(json.loads(data[6:])["soldiers"]), 8)


if __name__ == "__main__":
    unittest.main()
