"""HTTP API + SSE. 노트북·휴대폰 관제 화면이 같은 서버 상태를 동시에 받는다.

GET  /api/state                현재 상태 전체
GET  /api/events?since=&limit= 이벤트 목록
GET  /api/stream               SSE: "state"(변경 시, 최대 4회/초)·"event"(즉시)
POST /api/events/<id>/ack      지휘관 확인      body: {"by": "..."} (선택)
POST /api/events/<id>/resolve  실제 해결
POST /api/virtual              가상 노드 시작/중지 body: {"enabled", "scenario", "nodes", "speed", "loop", "loss_rate"}
POST /api/cmd                  장치로 명령     body: {"port": "...", "cmd": "stats"}
GET  /                         디버그 화면(관제 UI 아님)

읽기(GET)는 어느 출처에서나 허용한다. 쓰기(POST)는 같은 출처, Origin 헤더가 없는 클라이언트(curl 등),
--allow-origin으로 지정한 출처만 받고, Content-Type은 application/json이어야 한다. 그래서 같은 Wi-Fi의
브라우저에서 열린 다른 웹페이지가 SOS 해결 처리나 장치 명령을 몰래 보낼 수 없다.
"""

import json
import math
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .virtual import SCENARIOS, VirtualRunner

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
STATE_MIN_GAP_S = 0.25
MAX_BODY_BYTES = 64 * 1024


class App:
    def __init__(self, hub, clock=time.time, allow_origins=()):
        self.hub = hub
        self.clock = clock
        self.allow_origins = {o.rstrip("/") for o in allow_origins}  # 쓰기를 허용할 다른 출처
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
                nodes = [int(n.strip(), 0) if isinstance(n, str) else int(n) for n in nodes]
            except (TypeError, ValueError, OverflowError):
                raise ValueError("nodes must be integers (e.g. 2 or \"0x31\")")
        try:
            speed = float(cfg.get("speed", 1.0))
            loss_rate = float(cfg.get("loss_rate", 0.0))
        except (TypeError, ValueError):
            raise ValueError("speed and loss_rate must be numbers")
        if not (math.isfinite(speed) and math.isfinite(loss_rate)):
            raise ValueError("speed and loss_rate must be finite")
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

        def _origin_ok(self):
            """쓰기 요청을 받아도 되는 출처인가. Origin이 없으면(브라우저 아님) 허용."""
            origin = self.headers.get("Origin")
            if not origin:
                return True
            origin = origin.rstrip("/")
            host = self.headers.get("Host", "")
            return origin in ("http://" + host, "https://" + host) or origin in app.allow_origins

        def _cors(self):
            if self.command == "GET":
                self.send_header("Access-Control-Allow-Origin", "*")
                return
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if origin and origin in app.allow_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

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
            """JSON 객체 본문. 형식이 틀리면 (None, 상태 코드, 메시지)."""
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return None, 415, "Content-Type must be application/json"
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None, 400, "bad Content-Length"
            if n > MAX_BODY_BYTES:
                return None, 413, "body too large"
            if n <= 0:
                return {}, 200, None
            try:
                obj = json.loads(self.rfile.read(n).decode("utf-8"))
            except ValueError:
                return None, 400, "invalid json"
            if not isinstance(obj, dict):
                return None, 400, "body must be a JSON object"
            return obj, 200, None

        def do_OPTIONS(self):
            method = (self.headers.get("Access-Control-Request-Method") or "").upper()
            origin = (self.headers.get("Origin") or "").rstrip("/")
            self.send_response(204)
            if method == "GET":
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET")
            elif origin and origin in app.allow_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Vary", "Origin")
            self.end_headers()  # 허용하지 않는 출처에는 CORS 헤더를 주지 않아 브라우저가 막는다

        def _guard(self, fn):
            """처리 중 예상 못 한 예외가 나도 연결을 끊지 않고 500을 돌려준다."""
            try:
                fn()
            except OSError:  # 클라이언트가 먼저 끊음
                pass
            except Exception as e:
                try:
                    self._json({"error": f"internal error: {type(e).__name__}"}, 500)
                except OSError:
                    pass

        def do_GET(self):
            self._guard(self._get)

        def do_POST(self):
            self._guard(self._post)

        def _get(self):
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

        def _post(self):
            url = urlparse(self.path)
            if not self._origin_ok():
                return self._json({"error": "origin not allowed"}, 403)
            body, status, msg = self._body()
            if body is None:
                return self._json({"error": msg}, status)
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
