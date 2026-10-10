"""HTTP API + SSE. 노트북·휴대폰 관제 화면이 같은 서버 상태를 동시에 받는다.

GET  /api/state                       현재 상태 전체(분대원·환경 노드·노드 진단·앵커 관측)
GET  /api/events?since=&limit=        사건 목록(since: 사건의 n)
GET  /api/stream                      SSE: "state"(변경 시, 최대 4회/초)·"event"(즉시)
GET  /api/roster                      분대원 배정
POST /api/roster                      배정 변경  body: {"soldier_id", "assigned_node_id"(null 가능), "name"(선택)}
POST /api/env_nodes                   환경 노드 설치 지점  body: {"node_id", "location_name"}
POST /api/events/<event_id>/ack       지휘관 확인  body: {"by"}(선택), ?source=device|simulation(같은 ID가 여럿일 때)
POST /api/events/<event_id>/resolve   조치 종료
POST /api/virtual                     가상 노드 시작/중지 body: {"enabled", "scenario", "nodes", "speed", "loop", "loss_rate"}
POST /api/cmd                         장치로 명령 body: {"port": "...", "cmd": "stats"}
GET  /                                디버그 화면(관제 UI 아님)

event_id에 들어가는 ":"는 그대로 써도 되고, "/"가 들어 있으면 퍼센트 인코딩한다.

읽기(GET)는 어느 출처에서나 허용한다. 쓰기(POST)는 같은 출처, Origin 헤더가 없는 클라이언트(curl 등),
--allow-origin으로 지정한 출처만 받고, Content-Type은 application/json이어야 한다. 그래서 같은 Wi-Fi의
브라우저에서 열린 다른 웹페이지가 SOS 해결 처리나 장치 명령을 몰래 보낼 수 없다. 같은 출처로 인정하는 Host는
IP 주소·localhost·*.local과 --allow-host로 지정한 이름뿐이다(DNS 리바인딩으로 남의 도메인이 이 서버를
가리키게 해 같은 출처처럼 보내는 것을 막는다).
"""

import ipaddress
import json
import math
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .ingest import has_surrogate
from .virtual import SCENARIOS, VirtualRunner

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
STATE_MIN_GAP_S = 0.25
MAX_BODY_BYTES = 64 * 1024


def host_name(host_header):
    """Host 헤더에서 포트를 뗀 이름(소문자). IPv6는 대괄호를 뗀다."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else ""
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def trusted_host(name, extra=()):
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return (name == "localhost" or name.endswith((".localhost", ".local")) or name in extra)


class App:
    def __init__(self, hub, allow_origins=(), allow_hosts=()):
        self.hub = hub
        self.allow_origins = {o.rstrip("/") for o in allow_origins}  # 쓰기를 허용할 다른 출처
        self.allow_hosts = {h.strip().lower() for h in allow_hosts if h.strip()}  # 같은 출처로 인정할 호스트 이름
        self.readers = {}  # port -> SerialReader
        self.replayer = None
        self.virtual = None
        self.forwarder = None  # 팀장 관제 서버 전달(LeadForwarder), --forward-lead
        self.stopping = False
        self._vlock = threading.Lock()
        self._slock = threading.Lock()
        self._state_cache = None  # (hub.version, 만든 시각 monotonic, JSON 문자열)

    def virtual_status(self):
        v = self.virtual
        return v.status() if v is not None and v.is_alive() else {"running": False}

    def state(self):
        s = self.hub.snapshot(self.virtual_status())
        s["inputs"] = [r.status() for r in self.readers.values()]
        if self.replayer is not None:
            s["replay"] = {"path": self.replayer.path, "done": self.replayer.done,
                           "error": self.replayer.error}
        logger = getattr(self.hub, "logger", None)
        if logger is not None:
            s["log"] = logger.status()
        if self.forwarder is not None:
            s["forward"] = self.forwarder.status()
        return s

    def state_json(self):
        """직렬화한 상태. 같은 hub 버전이면 STATE_MIN_GAP_S 동안 한 번 만든 문자열을 모든 연결이 같이 쓴다.

        SSE 연결이 여럿이어도 상태 스냅샷(허브 잠금)과 직렬화는 변경당 한 번만 일어난다.
        """
        with self._slock:
            now = time.monotonic()
            c = self._state_cache
            if c is not None and c[0] == self.hub.version and now - c[1] < STATE_MIN_GAP_S:
                return c[2]
            s = self.state()
            text = json.dumps(s, ensure_ascii=False, separators=(",", ":"))
            self._state_cache = (s["version"], now, text)
            return text

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
            status = self.virtual_status()
        self.hub.touch()  # 실행 여부는 허브 상태가 아니므로 직접 알린다
        return status

    def _build_virtual(self, cfg):
        nodes = cfg.get("nodes") or None
        if nodes is not None:
            if not isinstance(nodes, list) or not all(isinstance(n, str) for n in nodes):
                raise ValueError('nodes must be a list of node IDs (e.g. ["halo_02"])')
            nodes = [n.strip() for n in nodes if n.strip()]
        try:
            speed = float(cfg.get("speed", 1.0))
            loss_rate = float(cfg.get("loss_rate", 0.0))
        except (TypeError, ValueError):
            raise ValueError("speed and loss_rate must be numbers")
        if not (math.isfinite(speed) and math.isfinite(loss_rate)):
            raise ValueError("speed and loss_rate must be finite")
        return VirtualRunner(
            self.hub, speed=speed, scenario=cfg.get("scenario", "normal"),
            nodes=nodes, seed=cfg.get("seed"), loop=bool(cfg.get("loop", False)),
            loss_rate=loss_rate)

    def ticker(self):
        while not self.stopping:
            self.hub.tick()
            time.sleep(0.5)


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
            if origin in app.allow_origins:
                return True
            host = self.headers.get("Host", "")
            same = origin in ("http://" + host, "https://" + host)
            return same and trusted_host(host_name(host), app.allow_hosts)

        def _cors(self):
            if self.command == "GET":
                self.send_header("Access-Control-Allow-Origin", "*")
                return
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if origin and origin in app.allow_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _json(self, obj, status=200):
            self._json_text(json.dumps(obj, ensure_ascii=False), status)

        def _json_text(self, text, status=200):
            body = text.encode("utf-8")
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
            if self.headers.get("Transfer-Encoding"):  # 청크 본문은 읽지 않는다(빈 본문으로 오해하지 않게)
                return None, 411, "Content-Length required"
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
            if has_surrogate(obj):
                return None, 400, "invalid unicode (unpaired surrogate)"
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
                return self._json_text(app.state_json())
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
            if url.path == "/api/roster":
                return self._json(app.hub.roster_list())
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
            path = url.path
            for action in ("ack", "resolve"):
                suffix = "/" + action
                if path.startswith("/api/events/") and path.endswith(suffix):
                    event_id = unquote(path[len("/api/events/"):-len(suffix)])
                    source = parse_qs(url.query).get("source", [None])[0]
                    by = body.get("by")
                    if not event_id or (by is not None and not isinstance(by, str)):
                        return self._json({"error": "bad event_id or by"}, 400)
                    ev, err = app.hub.mark_event(event_id, action, by=by, source=source)
                    if err == "not found":
                        return self._json({"error": err}, 404)
                    if err:
                        return self._json({"error": err}, 409)
                    return self._json(ev)
            if path == "/api/roster":
                try:
                    return self._json(app.hub.set_assignment(
                        body.get("soldier_id"), body.get("assigned_node_id"), body.get("name")))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if path == "/api/env_nodes":
                try:
                    return self._json(app.hub.set_env_location(body.get("node_id"), body.get("location_name")))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
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
            self._send_sse_text(event, json.dumps(data, ensure_ascii=False, separators=(",", ":")))

        def _send_sse_text(self, event, payload):
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
                self._send_sse_text("state", app.state_json())
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
                        self._send_sse_text("state", app.state_json())
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
