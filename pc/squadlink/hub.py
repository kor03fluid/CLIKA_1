"""수신 데이터 허브 (규격 v1, docs/data_spec_v1.md).

- 입력: 게이트웨이(B)·환경 노드가 USB로 내보내는 NDJSON 한 줄, 가상 노드, 로그 재생.
- 검사: schema.validate. 오류가 있으면 받지 않고 이유를 남긴다.
- 중복 제거 키: source + node_id + boot_id + seq.
- 지연 패킷(이전 boot 또는 이미 받은 것보다 작은 seq)은 최신 상태를 덮지 않는다. 사건은 event_id로 따로 기록한다.
- 분대원(soldier_01~08)과 배정 노드, 통신 상태(unassigned·waiting·connected·lost), 사건 상태(open·acknowledged·resolved).
- 두절 기준: max(15000, 3 × heartbeat_interval_ms + 2000) ms. 서버 단조 시계로 잰다.

시각은 clock 객체(wall=UTC epoch 초, mono=단조 초)로 받아 시험에서 가짜 시계를 쓸 수 있다.
"""

import itertools
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone

from .schema import SCHEMA_VERSION, timeout_ms, validate

SEQ_WINDOW = 512        # 중복 판단에 기억하는 최근 seq 수
SEQ_RESYNC_GAP = 1000   # 이보다 크게 뛰면 누락으로 세지 않는다
STALE_BOOT_FALLBACK_S = 65.0  # 보고 주기를 모를 때 이전 boot 판정·출처 활동 판정에 쓰는 시간
MAX_BOOTS_KEPT = 8
RECENT_ISSUES = 30


def iso(ts):
    """UTC ISO 8601 (밀리초). 예: 2026-10-10T01:49:00.000Z"""
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SystemClock:
    @staticmethod
    def wall():
        return time.time()

    @staticmethod
    def mono():
        return time.monotonic()


def default_roster():
    """규격 1장: 분대원 8명, 병사 01·02에만 헤일로팟 배정."""
    return [{"soldier_id": f"soldier_{i:02d}",
             "assigned_node_id": f"halo_{i:02d}" if i <= 2 else None} for i in range(1, 9)]


DEFAULT_ENV_NODES = [{"node_id": "env_01", "location_name": None}]


class SeqTracker:
    """(source, node, boot) 하나의 seq 중복·누락 추적."""

    def __init__(self):
        self.seen = set()
        self.order = deque()
        self.max_seq = None
        self.missing = OrderedDict()
        self.missing_total = 0

    def add(self, seq):
        """중복이면 False, 가장 앞선 seq면 "new", 이미 받은 것보다 작으면 "late"."""
        if seq in self.seen:
            return False
        self.seen.add(seq)
        self.order.append(seq)
        if len(self.order) > SEQ_WINDOW:
            self.seen.discard(self.order.popleft())
        if self.max_seq is None:
            self.max_seq = seq
            return "new"
        if seq > self.max_seq:
            gap = seq - self.max_seq
            if gap <= SEQ_RESYNC_GAP:
                for s in range(self.max_seq + 1, seq):
                    self.missing[s] = True
                    self.missing_total += 1
                while len(self.missing) > SEQ_WINDOW:
                    self.missing.popitem(last=False)
            self.max_seq = seq
            return "new"
        if self.missing.pop(seq, None):  # 늦게 도착: 누락에서 뺀다
            self.missing_total -= 1
        return "late"


class Stream:
    """한 노드의 한 출처(device 또는 simulation). 중복 제거 키에 source가 들어간다."""

    def __init__(self, source):
        self.source = source
        self.boot_id = None
        self.trackers = OrderedDict()   # boot_id -> SeqTracker
        self.boot_last = {}             # boot_id -> 그 boot로 마지막 새 패킷을 받은 단조 시각
        self.last_new = None
        self.reboots = 0

    def missing(self):
        return sum(t.missing_total for t in self.trackers.values())


class NodeState:
    def __init__(self, node_id):
        self.node_id = node_id
        self.kinds = set()
        self.streams = {}
        self.active = None        # 표시 중인 출처
        self.active_port = None
        self.active_input = None
        self.latest = {}          # packet_type -> {"packet", "received_at", "input", "port"}
        self.last_fix = None      # 마지막 유효 GPS
        self.heartbeat_interval_ms = None
        self.last_seen = None     # 단조 시각
        self.last_seen_at = None  # ISO
        self.state = "waiting"
        self.lost_count = 0
        self.c = {"rx": 0, "dup": 0, "late": 0, "stale_boot": 0, "shadowed": 0, "relayed": 0,
                  "source_changes": 0}

    def timeout_ms(self):
        hb = self.heartbeat_interval_ms
        return timeout_ms(hb) if hb else None

    def window_s(self):
        t = self.timeout_ms()
        return t / 1000.0 if t else STALE_BOOT_FALLBACK_S

    def stream_alive(self, stream, now):
        return stream is not None and stream.last_new is not None and now - stream.last_new <= self.window_s()

    def switch_to(self, source, port, input_):
        """표시 출처를 바꾼다. 이전 출처의 최신값·주기·연결 상태는 이어받지 않는다."""
        self.active, self.active_port, self.active_input = source, port, input_
        self.latest = {}
        self.last_fix = None
        self.heartbeat_interval_ms = None
        self.last_seen = None
        self.last_seen_at = None
        self.state = "waiting"
        self.c["source_changes"] += 1


class Hub:
    def __init__(self, logger=None, clock=None, roster=None, env_nodes=None, max_events=2000):
        self.lock = threading.RLock()
        self.logger = logger
        self.clock = clock or SystemClock()
        self.roster = OrderedDict()
        for r in (roster if roster is not None else default_roster()):
            if not isinstance(r, dict) or not isinstance(r.get("soldier_id"), str):
                raise ValueError(f"분대원 항목에 soldier_id 문자열이 필요함: {r!r}")
            node = r.get("assigned_node_id")
            if node is not None and not isinstance(node, str):
                raise ValueError(f"assigned_node_id는 문자열 또는 null: {r!r}")
            if node is not None and any(s["assigned_node_id"] == node for s in self.roster.values()):
                raise ValueError(f"{node}가 두 분대원에 배정됨")
            self.roster[r["soldier_id"]] = {"soldier_id": r["soldier_id"], "assigned_node_id": node,
                                            "name": r.get("name")}
        self.env_registry = OrderedDict()
        for e in (env_nodes if env_nodes is not None else DEFAULT_ENV_NODES):
            if not isinstance(e, dict) or not isinstance(e.get("node_id"), str):
                raise ValueError(f"환경 노드 항목에 node_id 문자열이 필요함: {e!r}")
            self.env_registry[e["node_id"]] = {"location_name": e.get("location_name")}
        self.nodes = {}
        self.anchors = {}            # (anchor_id, observed_node_id) -> 관측
        self.events = OrderedDict()  # (source, event_id) -> 사건
        self.max_events = max_events
        self._event_n = itertools.count(1)
        self.device_stats = {}
        self.totals = {"lines": 0, "accepted": 0, "late": 0, "stale_boot": 0, "dup": 0,
                       "shadowed": 0, "invalid": 0, "warnings": 0, "error": 0, "diag": 0}
        self.recent_invalid = deque(maxlen=RECENT_ISSUES)
        self.recent_warnings = deque(maxlen=RECENT_ISSUES)
        self.listeners = []
        self.version = 0

    # ----- 구독 -----
    def subscribe(self, fn):
        with self.lock:
            self.listeners.append(fn)

    def unsubscribe(self, fn):
        with self.lock:
            if fn in self.listeners:
                self.listeners.remove(fn)

    def _notify(self, kind, payload):
        for fn in list(self.listeners):
            try:
                fn(kind, payload)
            except Exception:
                pass

    def _changed(self):
        self.version += 1
        self._notify("changed", self.version)

    def touch(self):
        """허브 밖 상태(가상 노드 실행, 시리얼 연결, 재생 종료)가 바뀌었을 때 SSE가 새 상태를 보내게 한다."""
        with self.lock:
            self._changed()

    # ----- 분대원·환경 노드 등록 -----
    def soldier_for(self, node_id):
        for s in self.roster.values():
            if s["assigned_node_id"] == node_id:
                return s["soldier_id"]
        return None

    def monitored(self, node_id):
        """두절 사건을 만들 노드: 분대원에 배정됐거나 환경 노드."""
        n = self.nodes.get(node_id)
        return (self.soldier_for(node_id) is not None or node_id in self.env_registry
                or (n is not None and "environment" in n.kinds))

    def set_assignment(self, soldier_id, node_id, name=None):
        """분대원에 노드를 배정(None이면 해제). 한 노드는 한 분대원에게만. 실패하면 ValueError."""
        with self.lock:
            if soldier_id not in self.roster:
                raise ValueError(f"등록되지 않은 분대원: {soldier_id}")
            if node_id is not None:
                if not isinstance(node_id, str) or not node_id:
                    raise ValueError("assigned_node_id는 문자열 또는 null")
                other = self.soldier_for(node_id)
                if other is not None and other != soldier_id:
                    raise ValueError(f"{node_id}는 이미 {other}에 배정됨")
            if name is not None and not isinstance(name, str):
                raise ValueError("name은 문자열")
            entry = self.roster[soldier_id]
            entry["assigned_node_id"] = node_id
            if name is not None:
                entry["name"] = name
            self._changed()
            return dict(entry)

    def set_env_location(self, node_id, location_name):
        with self.lock:
            if not isinstance(node_id, str) or not node_id:
                raise ValueError("node_id는 문자열")
            if location_name is not None and not isinstance(location_name, str):
                raise ValueError("location_name은 문자열 또는 null")
            self.env_registry.setdefault(node_id, {})["location_name"] = location_name
            self._changed()
            return {"node_id": node_id, "location_name": location_name}

    # ----- 입력 -----
    def ingest(self, obj, input_, port):
        """JSON 객체 하나 처리. input_: "serial" | "sim" | "replay".

        결과: ok | late | stale_boot | dup | shadowed | invalid | error
        예외를 밖으로 내보내지 않는다.
        """
        with self.lock:
            now, wall = self.clock.mono(), self.clock.wall()
            self.totals["lines"] += 1
            errors, warnings = [], []
            try:
                result, errors, warnings = self._ingest(obj, input_, port, now, wall)
            except Exception as e:  # 검사에서 빠진 경우의 마지막 방어선
                result, errors = "error", [f"{type(e).__name__}: {e}"]
                self.totals["error"] += 1
            if self.logger:
                self.logger.rx(wall, input_, port, result, obj, errors, warnings)
            if result not in ("dup", "invalid"):
                self._changed()
            return result

    def ingest_diag(self, obj, input_, port):
        """장치 진단 줄("# {...}"). 데이터 스트림이 아니며 stats만 보관한다."""
        with self.lock:
            wall = self.clock.wall()
            self.totals["diag"] += 1
            if isinstance(obj, dict) and obj.get("type") == "stats":
                key = obj.get("node_id") or port
                self.device_stats[str(key)] = dict(obj, received_at=iso(wall), input=input_)
                self._changed()
            if self.logger:
                self.logger.diag(wall, input_, port, obj)

    def _ingest(self, obj, input_, port, now, wall):
        pkt, errors, warnings = validate(obj)
        node_id = obj.get("node_id") if isinstance(obj, dict) else None
        if errors:
            self.totals["invalid"] += 1
            self.recent_invalid.append({"received_at": iso(wall), "input": input_, "port": port,
                                        "node_id": node_id if isinstance(node_id, str) else None,
                                        "errors": errors[:8]})
            return "invalid", errors, warnings
        if warnings:
            self.totals["warnings"] += 1
            self.recent_warnings.append({"received_at": iso(wall), "input": input_, "port": port,
                                         "node_id": node_id, "warnings": warnings[:8]})

        ptype, source = pkt["packet_type"], pkt["source"]
        n = self.nodes.get(node_id)
        if n is None:
            n = self.nodes[node_id] = NodeState(node_id)
        stream = n.streams.get(source)
        if stream is None:
            stream = n.streams[source] = Stream(source)

        # 앵커 관측은 노드의 표시 상태를 바꾸지 않으므로 출처 선택과 무관하게 받는다.
        # (환경 노드가 vtemp 시험으로 환경 패킷만 simulation으로 보내도 실제 관측은 device로 온다)
        if ptype == "anchor_observation" and n.active is not None and source != n.active:
            order = self._sequence(n, stream, pkt, now)
            if order == "dup":
                n.c["dup"] += 1
                self.totals["dup"] += 1
                return "dup", errors, warnings
            self.totals["accepted" if order == "new" else order] += 1
            n.kinds.add(ptype)
            self._anchor(pkt, input_, now, wall)
            return ("ok" if order == "new" else order), errors, warnings

        # 출처 선택: 실제(device) 우선. 표시 중인 출처가 활동 중이면 다른 출처는 가린다.
        # 같은 입력 포트에서 출처가 바뀌면(예: 환경 노드 vtemp 시험) 장치 자신이 바꾼 것으로 보고 따른다.
        if n.active is None:
            n.active, n.active_port, n.active_input = source, port, input_
        elif source != n.active:
            if (source == "device" or port == n.active_port
                    or not n.stream_alive(n.streams.get(n.active), now)):
                n.switch_to(source, port, input_)
            else:
                n.c["shadowed"] += 1
                self.totals["shadowed"] += 1
                # 가려진 출처도 번호는 추적한다. 반복 광고 중복이 사건 보고 수를 부풀리지 않고,
                # 나중에 이 출처가 표시 출처가 되어도 가려졌던 동안의 번호가 누락으로 잡히지 않는다.
                # 중복이어도 결과는 "shadowed"로 둔다(재생은 가려진 줄을 다시 흘리지 않는다).
                order = self._sequence(n, stream, pkt, now)
                if ptype == "event" and order != "dup":  # 사건은 출처 라벨을 달고 계속 기록한다
                    self._record_event(pkt, input_, wall, late=order != "new")
                return "shadowed", errors, warnings

        order = self._sequence(n, stream, pkt, now)
        if order == "dup":
            n.c["dup"] += 1
            self.totals["dup"] += 1
            return "dup", errors, warnings

        n.kinds.add(ptype)
        if pkt["transport"]["route"] == "relay":
            n.c["relayed"] += 1
        record = {"packet": pkt, "received_at": iso(wall), "input": input_, "port": port}

        if order == "new":
            self.totals["accepted"] += 1
            n.c["rx"] += 1
            n.last_seen, n.last_seen_at = now, iso(wall)
            n.active_port, n.active_input = port, input_
            if ptype in ("soldier_status", "environment"):
                n.heartbeat_interval_ms = pkt["payload"]["heartbeat_interval_ms"]
            if ptype in ("soldier_status", "environment", "gps"):
                n.latest[ptype] = record
                if ptype == "gps" and pkt["payload"]["fix_valid"]:
                    n.last_fix = record
            if n.heartbeat_interval_ms:
                n.state = "connected"
        else:
            key = "late" if order == "late" else "stale_boot"
            n.c[key] += 1
            self.totals[key] += 1

        if ptype == "event":
            self._record_event(pkt, input_, wall, late=order != "new")
        elif ptype == "anchor_observation":
            self._anchor(pkt, input_, now, wall)
        return ("ok" if order == "new" else order), errors, warnings

    def _sequence(self, n, stream, pkt, now):
        boot, seq = pkt["boot_id"], pkt["seq"]
        if boot != stream.boot_id:
            last = stream.boot_last.get(boot)
            if last is not None and (now - last <= n.window_s() or n.stream_alive(stream, now)):
                # 이전 부팅의 지연 패킷: 중복만 거르고 상태는 바꾸지 않는다
                return "stale_boot" if stream.trackers[boot].add(seq) else "dup"
            if stream.boot_id is not None:
                stream.reboots += 1
            stream.boot_id = boot
            stream.trackers.pop(boot, None)
            stream.boot_last.pop(boot, None)
            stream.trackers[boot] = SeqTracker()
            while len(stream.trackers) > MAX_BOOTS_KEPT:
                old, _ = stream.trackers.popitem(last=False)
                stream.boot_last.pop(old, None)
        r = stream.trackers[boot].add(seq)
        if not r:
            return "dup"
        if r == "new":
            stream.boot_last[boot] = now
            stream.last_new = now
        return r

    def _anchor(self, pkt, input_, now, wall):
        p = pkt["payload"]
        age_s = p["observation_age_ms"] / 1000.0
        key = (pkt["node_id"], p["observed_node_id"])
        cur = self.anchors.get(key)
        observed = now - age_s
        if cur is not None and cur["_observed"] > observed:
            return  # 더 최근 관측이 이미 있다
        self.anchors[key] = {
            "_observed": observed,
            "anchor_id": pkt["node_id"], "observed_node_id": p["observed_node_id"],
            "observed_boot_id": p["observed_boot_id"], "observed_seq": p["observed_seq"],
            "rssi_dbm": p["rssi_dbm"], "observed_at": iso(wall - age_s), "received_at": iso(wall),
            "source": pkt["source"], "route": pkt["transport"]["route"], "input": input_,
        }

    # ----- 사건 -----
    def _store_event(self, rec):
        self.events[(rec["source"], rec["event_id"])] = rec
        while len(self.events) > self.max_events:
            self.events.popitem(last=False)
        if self.logger:
            self.logger.event(dict(rec))
        self._notify("event", dict(rec))

    def _record_event(self, pkt, input_, wall, late):
        p = pkt["payload"]
        rec = self.events.get((pkt["source"], p["event_id"]))
        if rec is not None:
            # 같은 사건의 재보고: 확인·해결 상태는 유지한다
            rec["report_count"] += 1
            rec["last_received_at"] = iso(wall)
            self._notify("event", dict(rec))
            return
        self._store_event({
            "n": next(self._event_n), "event_id": p["event_id"], "event_type": p["event_type"],
            "origin": "node", "node_id": pkt["node_id"], "soldier_id": self.soldier_for(pkt["node_id"]),
            "source": pkt["source"], "mode": p["mode"], "boot_id": pkt["boot_id"], "seq": pkt["seq"],
            "uptime_ms": pkt["uptime_ms"], "route": pkt["transport"]["route"], "input": input_,
            "late": late, "event_state": "open", "first_received_at": iso(wall),
            "last_received_at": iso(wall), "report_count": 1,
            "acknowledged_at": None, "acknowledged_by": None, "resolved_at": None, "resolved_by": None,
        })

    def _server_event(self, n, event_type, wall):
        n.lost_count += 1
        self._store_event({
            "n": next(self._event_n),
            "event_id": f"server:{n.node_id}:{event_type}:{n.lost_count}", "event_type": event_type,
            "origin": "server", "node_id": n.node_id, "soldier_id": self.soldier_for(n.node_id),
            "source": n.active, "mode": None, "boot_id": None, "seq": None, "uptime_ms": None,
            "route": None, "input": n.active_input, "late": False, "event_state": "open",
            "first_received_at": iso(wall), "last_received_at": iso(wall), "report_count": 1,
            "acknowledged_at": None, "acknowledged_by": None, "resolved_at": None, "resolved_by": None,
        })

    def find_events(self, event_id, source=None):
        with self.lock:
            return [r for (s, e), r in self.events.items()
                    if e == event_id and (source is None or s == source)]

    def mark_event(self, event_id, action, by=None, source=None):
        """action: "ack"(지휘관 확인) | "resolve"(조치 종료).

        돌려주는 값: (사건 복사본 또는 None, 오류 문자열 또는 None).
        이미 확인·해결된 사건은 바꾸지 않는다. 해결은 확인 없이도 할 수 있다.
        """
        with self.lock:
            if action not in ("ack", "resolve"):
                return None, "action은 ack 또는 resolve"
            found = self.find_events(event_id, source)
            if not found:
                return None, "not found"
            if len(found) > 1:
                return None, "같은 event_id가 여러 출처에 있음: source를 지정"
            rec = found[0]
            wall = self.clock.wall()
            changed = False
            if action == "ack" and rec["event_state"] == "open":
                rec.update(event_state="acknowledged", acknowledged_at=iso(wall), acknowledged_by=by)
                changed = True
            elif action == "resolve" and rec["event_state"] != "resolved":
                rec.update(event_state="resolved", resolved_at=iso(wall), resolved_by=by)
                changed = True
            if changed:
                if self.logger:
                    self.logger.event_update(wall, rec["source"], event_id, action, by)
                self._notify("event", dict(rec))
                self._changed()
            return dict(rec), None

    def list_events(self, since_n=0, limit=200):
        """since_n보다 나중에 생긴 사건 중 최근 limit개(복사본)."""
        with self.lock:
            if limit <= 0:
                return []
            out = [dict(r) for r in self.events.values() if r["n"] > since_n]
            return out[-limit:]

    # ----- 주기 점검 -----
    def tick(self):
        with self.lock:
            now, wall = self.clock.mono(), self.clock.wall()
            changed = False
            for n in self.nodes.values():
                t = n.timeout_ms()
                if n.state == "connected" and t is not None and now - n.last_seen > t / 1000.0:
                    n.state = "lost"
                    changed = True
                    if self.monitored(n.node_id):  # 두절 전환마다 한 번
                        self._server_event(n, "connection_lost", wall)
            if changed:
                self._changed()

    # ----- 조회 -----
    def _active_event_ids(self, node_id):
        return [r["event_id"] for r in self.events.values()
                if r["node_id"] == node_id and r["event_state"] != "resolved"]

    def _soldier_view(self, s):
        node_id = s["assigned_node_id"]
        n = self.nodes.get(node_id) if node_id else None
        if node_id is None:
            state = "unassigned"
        elif n is None:
            state = "waiting"
        else:
            state = n.state
        status = n.latest.get("soldier_status") if n else None
        gps = n.latest.get("gps") if n else None
        location = None
        if gps is not None or (n is not None and n.last_fix is not None):
            fix = n.last_fix["packet"]["payload"] if n.last_fix else {}
            current_valid = bool(gps and gps["packet"]["payload"]["fix_valid"])
            location = {
                "fix_valid": current_valid,
                "latitude_deg": fix.get("latitude_deg"), "longitude_deg": fix.get("longitude_deg"),
                "hdop": fix.get("hdop"),
                "location_updated_at": n.last_fix["received_at"] if n.last_fix else None,
                "location_stale": not current_valid or state != "connected",
            }
        return {
            "soldier_id": s["soldier_id"], "name": s.get("name"), "assigned_node_id": node_id,
            "connection_state": state, "data_stale": state != "connected",
            "source": n.active if n else None, "input": n.active_input if n else None,
            "last_seen_at": n.last_seen_at if n else None,
            "received_at": status["received_at"] if status else None,
            "heartbeat_interval_ms": n.heartbeat_interval_ms if n else None,
            "timeout_ms": n.timeout_ms() if n else None,
            "status": status["packet"]["payload"] if status else None,
            "status_seq": status["packet"]["seq"] if status else None,
            "status_boot_id": status["packet"]["boot_id"] if status else None,
            "route": status["packet"]["transport"]["route"] if status else None,
            "location": location,
            "estimated_zone_id": None,  # 앵커 구역 추정은 검증 후 적용(규격 1장)
            "active_event_ids": self._active_event_ids(node_id) if node_id else [],
        }

    def _env_view(self, node_id):
        n = self.nodes.get(node_id)
        env = n.latest.get("environment") if n else None
        state = n.state if n else "waiting"
        return {
            "node_id": node_id, "location_name": self.env_registry.get(node_id, {}).get("location_name"),
            "connection_state": state, "data_stale": state != "connected",
            "source": n.active if n else None, "input": n.active_input if n else None,
            "last_seen_at": n.last_seen_at if n else None,
            "received_at": env["received_at"] if env else None,
            "heartbeat_interval_ms": n.heartbeat_interval_ms if n else None,
            "timeout_ms": n.timeout_ms() if n else None,
            "environment": env["packet"]["payload"] if env else None,
            "active_event_ids": self._active_event_ids(node_id),
        }

    def _node_diag(self, n):
        return {
            "node_id": n.node_id, "kinds": sorted(n.kinds), "active_source": n.active,
            "input": n.active_input, "connection_state": n.state, "last_seen_at": n.last_seen_at,
            "heartbeat_interval_ms": n.heartbeat_interval_ms, "timeout_ms": n.timeout_ms(),
            "counters": dict(n.c, missing=sum(s.missing() for s in n.streams.values()),
                             reboots=sum(s.reboots for s in n.streams.values())),
            "streams": {src: {"boot_id": s.boot_id, "missing": s.missing(), "reboots": s.reboots}
                        for src, s in n.streams.items()},
        }

    def roster_list(self):
        with self.lock:
            return [dict(s) for s in self.roster.values()]

    def snapshot(self, virtual_status=None):
        with self.lock:
            now, wall = self.clock.mono(), self.clock.wall()
            env_ids = list(self.env_registry) + sorted(
                nid for nid, n in self.nodes.items()
                if "environment" in n.kinds and nid not in self.env_registry)
            anchors = []
            for rec in sorted(self.anchors.values(), key=lambda r: (r["anchor_id"], r["observed_node_id"])):
                a = {k: v for k, v in rec.items() if not k.startswith("_")}
                a["age_ms"] = max(0, int((now - rec["_observed"]) * 1000))
                anchors.append(a)
            counts = {"open": 0, "acknowledged": 0, "resolved": 0}
            for r in self.events.values():
                counts[r["event_state"]] += 1
            return {
                "schema_version": SCHEMA_VERSION,
                "server_time": iso(wall),
                "version": self.version,
                "soldiers": [self._soldier_view(s) for s in self.roster.values()],
                "environment_nodes": [self._env_view(nid) for nid in env_ids],
                "nodes": {nid: self._node_diag(n) for nid, n in sorted(self.nodes.items())},
                "anchor_observations": anchors,
                "event_counts": counts,
                "totals": dict(self.totals),
                "recent_invalid": list(self.recent_invalid),
                "recent_warnings": list(self.recent_warnings),
                "device_stats": dict(self.device_stats),
                "virtual": virtual_status,
            }
