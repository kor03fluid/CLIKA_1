"""HTTP API + SSE. 노트북·휴대폰 관제 화면이 같은 서버 상태를 동시에 받는다.

GET  /api/state                현재 상태 전체
GET  /api/events?since=&limit= 이벤트 목록
GET  /api/stream               SSE: "state"(변경 시, 최대 4회/초)·"event"(즉시)
POST /api/events/<id>/ack      지휘관 확인      body: {"by": "..."} (선택)
POST /api/events/<id>/resolve  실제 해결
POST /api/virtual              가상 노드 시작/중지 body: {"enabled", "scenario", "nodes", "speed", "loop", "loss_rate"}
POST /api/cmd                  장치로 명령     body: {"port": "...", "cmd": "stats"}
GET  /                         디버그 화면(관제 UI 아님)
"""

import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .virtual import SCENARIOS, VirtualRunner

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
STATE_MIN_GAP_S = 0.25


class App:
    def __init__(self, hub, clock=time.time):
        self.hub = hub
        self.clock = clock
        self.readers = {}  # port -> SerialReader
        self.replayer = None
        self.virtual = None
        self.stopping = False
        self._vlock = threading.Lock()

    def virtual_status(self):
        v = self.virtual
        return v.status() if v is not None and v.is_alive() else {"running": False}

    def state(self):
        s = self.hub.snapshot(self.clock(), self.virtual_status())
        s["inputs"] = [r.status() for r in self.readers.values()]
        if self.replayer is not None:
            s["replay"] = {"path": self.replayer.path, "done": self.replayer.done,
                           "error": self.replayer.error}
        return s

    def set_virtual(self, cfg):
        """가상 노드 시작/교체/중지. 값이 잘못되면 ValueError를 내고 실행 중인 것은 그대로 둔다."""
        enabled = bool(cfg.get("enabled", True))
        runner = self._build_virtual(cfg) if enabled else None  # 검사·생성 먼저
        with self._vlock:
            if self.virtual is not None:
                self.virtual.stop()
                self.virtual.join(timeout=2)
                self.virtual = None
            if runner is not None:
                self.virtual = runner
                runner.start()
            return self.virtual_status()

    def _build_virtual(self, cfg):
        nodes = cfg.get("nodes") or None
        if nodes is not None:
            if not isinstance(nodes, list):
                raise ValueError("nodes must be a list")
            try:
                nodes = [int(n, 0) if isinstance(n, str) else int(n) for n in nodes]
            except (TypeError, ValueError):
                raise ValueError("nodes must be integers (e.g. 2 or \"0x31\")")
        try:
            speed = float(cfg.get("speed", 1.0))
            loss_rate = float(cfg.get("loss_rate", 0.0))
        except (TypeError, ValueError):
            raise ValueError("speed and loss_rate must be numbers")
        return VirtualRunner(
            self.hub, clock=self.clock, speed=speed, scenario=cfg.get("scenario", "normal"),
            nodes=nodes, seed=cfg.get("seed"), loop=bool(cfg.get("loop", False)),
            loss_rate=loss_rate)

    def ticker(self):
        while not self.stopping:
            self.hub.tick(self.clock())
            time.sleep(1.0)


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SquadLinkPC/0.1"

        def log_message(self, fmt, *args):  # 접속 로그는 끈다
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            try:
                obj = json.loads(self.rfile.read(n).decode("utf-8"))
            except ValueError:
                return None
            return obj if isinstance(obj, dict) else None

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/api/state":
                return self._json(app.state())
            if url.path == "/api/events":
                q = parse_qs(url.query)
                try:
                    since = int(q.get("since", ["0"])[0])
                    limit = int(q.get("limit", ["200"])[0])
                except ValueError:
                    return self._json({"error": "since/limit must be integers"}, 400)
                return self._json(app.hub.list_events(since, limit))
            if url.path == "/api/scenarios":
                return self._json(sorted(SCENARIOS))
            if url.path == "/api/stream":
                return self._sse()
            if url.path in ("/", "/index.html"):
                return self._static("index.html", "text/html; charset=utf-8")
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            url = urlparse(self.path)
            body = self._body()
            if body is None:
                return self._json({"error": "invalid json"}, 400)
            parts = url.path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "events"] and parts[3] in ("ack", "resolve"):
                try:
                    eid = int(parts[2])
                except ValueError:
                    return self._json({"error": "bad id"}, 400)
                ev = app.hub.mark_event(eid, parts[3], app.clock(), body.get("by"))
                return self._json(ev) if ev else self._json({"error": "not found"}, 404)
            if url.path == "/api/virtual":
                try:
                    return self._json(app.set_virtual(body))
                except (ValueError, TypeError) as e:
                    return self._json({"error": str(e)}, 400)
            if url.path == "/api/cmd":
                r = app.readers.get(body.get("port"))
                if r is None or not body.get("cmd"):
                    return self._json({"error": "unknown port or empty cmd"}, 400)
                return self._json({"sent": r.write_line(str(body["cmd"]))})
            self._json({"error": "not found"}, 404)

        def _static(self, name, ctype):
            try:
                with open(os.path.join(STATIC_DIR, name), "rb") as f:
                    body = f.read()
            except OSError:
                return self._json({"error": "not found"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_sse(self, event, data):
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

        def _sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()

            events = queue.Queue(maxsize=500)
            dirty = threading.Event()

            def listener(kind, payload):
                if kind == "changed":
                    dirty.set()
                elif kind == "event":
                    try:
                        events.put_nowait(dict(payload))
                    except queue.Full:
                        pass

            app.hub.subscribe(listener)
            try:
                self._send_sse("state", app.state())
                last_state = last_ping = time.monotonic()
                while not app.stopping:
                    try:
                        self._send_sse("event", events.get(timeout=STATE_MIN_GAP_S))
                    except queue.Empty:
                        pass
                    now = time.monotonic()
                    if dirty.is_set() and now - last_state >= STATE_MIN_GAP_S:
                        dirty.clear()
                        last_state = now
                        self._send_sse("state", app.state())
                    if now - last_ping >= 15:
                        last_ping = now
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except OSError:  # 클라이언트 연결 끊김
                pass
            finally:
                app.hub.unsubscribe(listener)

    return Handler


def serve(app, host, port):
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd
