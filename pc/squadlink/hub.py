"""수신 데이터 허브: 정규화·중복 제거·누락 추적·노드 상태·이벤트 기록.

입력은 게이트웨이(팀원 B)와 환경 노드가 USB로 내보내는 JSON 한 줄이다.
패킷은 node·boot·seq를 반드시 가진다. 중복 제거 키는 node + boot + seq.
시간은 모두 호출자가 넘기는 값(초)을 쓰므로 시험에서 가짜 시계를 쓸 수 있다.
"""

import itertools
import math
import threading
from collections import OrderedDict, deque

SEQ_MOD = 0x10000
SEQ_WINDOW = 512        # 중복 판단에 기억하는 최근 seq 수
SEQ_RESYNC_GAP = 1000   # 이보다 크게 뛰면 누락으로 세지 않고 다시 맞춘다

# 통신 두절: 노드 종류별 최대 송신 간격 × 연속 누락 수 + 여유. 5초로 고정하지 않는다.
# 앵커 전용 노드는 볼 병사가 없으면 보고를 보내지 않으므로 두절을 판정하지 않는다.
MAX_INTERVAL_S = {"soldier": 30.0, "env": 30.0}
# 두절 판정이 없는 노드(앵커 전용)의 "최근 활동" 기준. 이전 boot 판정과 출처 우선순위에 쓴다.
ACTIVE_FALLBACK_S = 65.0
MAX_BOOTS_KEPT = 8
FIXED_INTERVAL_S = 5.0  # tx_mode == "fixed" 일 때
MISS_COUNT = 2
GRACE_S = 5.0

META_TYPES = {"boot", "stats", "warn", "log"}

# 서버 기본 분류. 최종 우선순위는 관제 쪽 판단 로직(팀장)이 정한다.
ENV_EVENT_LEVEL = {"flame": "warning", "heat": "warning", "sound": "info",
                   "shock": "info", "reed": "info"}


class SeqTracker:
    """(node, boot) 하나의 seq 중복·누락 추적. seq는 16bit 순환."""

    def __init__(self):
        self.seen = set()
        self.order = deque()
        self.max_seq = None
        self.missing = OrderedDict()
        self.missing_total = 0

    def add(self, seq):
        """중복이면 False, 지금까지 중 가장 앞선 seq면 "new", 그보다 뒤처진 seq면 "late"."""
        if seq in self.seen:
            return False
        self.seen.add(seq)
        self.order.append(seq)
        if len(self.order) > SEQ_WINDOW:
            self.seen.discard(self.order.popleft())

        if self.max_seq is None:
            self.max_seq = seq
            return "new"
        diff = (seq - self.max_seq) % SEQ_MOD
        if 0 < diff < SEQ_MOD // 2:  # 앞선 seq
            if diff <= SEQ_RESYNC_GAP:
                for k in range(1, diff):
                    self.missing[(self.max_seq + k) % SEQ_MOD] = True
                    self.missing_total += 1
                while len(self.missing) > SEQ_WINDOW:
                    self.missing.popitem(last=False)
            self.max_seq = seq
            return "new"
        if self.missing.pop(seq, None):  # 늦게 도착: 누락에서 뺀다
            self.missing_total -= 1
        return "late"


class NodeState:
    def __init__(self, node):
        self.node = node
        self.types = set()
        self.boot = None
        self.trackers = {}      # boot -> SeqTracker (최근 MAX_BOOTS_KEPT개)
        self.boot_last_rx = {}  # boot -> 그 boot로 마지막 정상 수신한 시각
        self.last_rx = None
        self.last_seq = None
        self.online = False
        self.source = None
        self.virtual = False
        self.via = None
        self.latest = {}  # type -> 마지막 패킷(정규화)
        self.rx = 0
        self.dup = 0
        self.relayed = 0
        self.reboots = 0
        self.stale_boot = 0
        self.late = 0
        self.shadowed = 0
        # SOS 구간 기록(현재 boot). 늦게 온 sos 패킷이 이미 알린 구간에 속하는지 판단한다.
        # seq 16bit 순환은 고려하지 않는다(10초 주기로 약 7일).
        self.sos_starts = deque(maxlen=32)
        self.sos_releases = deque(maxlen=32)

    def reset_stream(self):
        """출처가 바뀔 때 boot·seq 기록과 최신 패킷을 비운다. 누적 카운터는 남긴다."""
        self.boot = None
        self.trackers.clear()
        self.boot_last_rx.clear()
        self.latest.clear()
        self.last_seq = None
        self.via = None
        self.sos_starts.clear()
        self.sos_releases.clear()

    @property
    def kind(self):
        for k in ("soldier", "env"):
            if k in self.types:
                return k
        return "anchor" if "anchor" in self.types else "unknown"

    def timeout_s(self):
        """통신 두절 판정 시간(초). 앵커 전용 노드는 판정하지 않으므로 None."""
        if self.kind == "anchor":
            return None
        interval = MAX_INTERVAL_S.get(self.kind, 30.0)
        if any(p.get("tx_mode") == "fixed" for p in self.latest.values()):
            interval = FIXED_INTERVAL_S
        return interval * MISS_COUNT + GRACE_S

    def window_s(self):
        """이 노드가 '최근 활동 중'이라고 보는 시간. 두절 판정 시간과 같다."""
        return self.timeout_s() or ACTIVE_FALLBACK_S

    def active(self, now):
        return self.last_rx is not None and now - self.last_rx <= self.window_s()

    def missing_total(self):
        return sum(t.missing_total for t in self.trackers.values())

    def snapshot(self, now):
        return {
            "node": self.node,
            "kind": self.kind,
            "boot": self.boot,
            "last_seq": self.last_seq,
            "last_rx": self.last_rx,
            "age_s": None if self.last_rx is None else round(now - self.last_rx, 1),
            "online": self.online,
            "timeout_s": self.timeout_s(),
            "source": self.source,
            "virtual": self.virtual,
            "via": self.via,
            "latest": dict(self.latest),  # 패킷 dict는 만든 뒤 바꾸지 않으므로 얕은 복사로 충분
            "counters": {
                "rx": self.rx, "dup": self.dup, "missing": self.missing_total(),
                "relayed": self.relayed, "reboots": self.reboots, "stale_boot": self.stale_boot,
                "late": self.late, "shadowed": self.shadowed,
            },
        }


def _as_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v, 0)
        except ValueError:
            return None
    return None


class Hub:
    def __init__(self, logger=None, max_events=2000):
        self.lock = threading.RLock()
        self.logger = logger
        self.nodes = {}
        self.anchors = {}       # anchor_id -> soldier_id -> 관측
        self.device_stats = {}  # node -> 마지막 stats JSON
        self.events = deque(maxlen=max_events)
        self.events_by_id = {}
        self._ids = itertools.count(1)
        self.totals = {"lines": 0, "packets": 0, "dup": 0, "invalid": 0, "meta": 0, "error": 0,
                       "late": 0, "shadowed": 0}
        self.listeners = []
        self.version = 0  # 상태가 바뀔 때마다 증가

    # ----- 구독 (SSE 등) -----
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

    # ----- 입력 -----
    def ingest(self, obj, source, port, now):
        """JSON 객체 하나를 처리하고 결과 문자열을 돌려준다.

        source: "real" | "virtual" | "replay"
        결과: ok | late | dup | stale_boot | shadowed | meta | invalid | error
        예외를 밖으로 내보내지 않는다. 형식이 이상한 줄 하나가 입력 스레드를 멈추면 안 된다.
        """
        with self.lock:
            self.totals["lines"] += 1
            error = None
            try:
                result = self._ingest(obj, source, port, now)
            except Exception as e:  # 검사에서 빠진 형식 오류의 마지막 방어선
                result, error = "error", f"{type(e).__name__}: {e}"
                self.totals["error"] += 1
            if result == "invalid":
                self.totals["invalid"] += 1
            if self.logger:
                self.logger.rx(now, source, port, result, obj, error)
            if result in ("ok", "late", "meta", "error"):
                self._changed()
            return result

    def _ingest(self, obj, source, port, now):
        if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
            return "invalid"
        ptype = obj["type"]
        if ptype in META_TYPES:
            self.totals["meta"] += 1
            node = _as_int(obj.get("node"))
            if ptype == "stats" and node is not None:
                self.device_stats[node] = dict(obj, rx_ts=now, source=source)
            return "meta"

        node_id, boot, seq = (_as_int(obj.get(k)) for k in ("node", "boot", "seq"))
        if node_id is None or boot is None or seq is None:
            return "invalid"

        n = self.nodes.get(node_id)
        if n is None:
            n = self.nodes[node_id] = NodeState(node_id)

        # 출처 우선순위: 실측 > (먼저 들어와 활동 중인) 가상·재생.
        # 같은 ID를 두 출처가 동시에 보내면 boot가 서로 달라 상태가 번갈아 바뀌므로 한쪽만 받는다.
        switched = False
        if n.source is not None and source != n.source:
            if source != "real" and n.active(now):
                n.shadowed += 1
                self.totals["shadowed"] += 1
                return "shadowed"
            self._event(now, node_id, "source_change", "info", {"from": n.source, "to": source},
                        source, obj)
            n.reset_stream()
            switched = True

        if boot != n.boot:
            last = n.boot_last_rx.get(boot)
            if last is not None and (now - last <= n.window_s() or n.active(now)):
                # 이전 부팅의 늦은 패킷: 중복만 거르고 현재 상태는 바꾸지 않는다.
                # 수신 시각을 갱신하지 않으므로, 번호가 재사용된 경우(플래시 초기화·카운터 순환)에도
                # 현재 boot가 두절 판정 시간만큼 조용해지면 새 부팅으로 받아들인다.
                if not n.trackers[boot].add(seq):
                    n.dup += 1
                    self.totals["dup"] += 1
                    return "dup"
                n.stale_boot += 1
                return "stale_boot"
            if n.boot is not None:
                n.reboots += 1
                self._event(now, node_id, "reboot", "info", {"old_boot": n.boot, "new_boot": boot},
                            source, obj)
            n.boot = boot
            n.trackers.pop(boot, None)  # 재사용된 번호면 이전 seq 기록을 버린다
            n.boot_last_rx.pop(boot, None)
            n.trackers[boot] = SeqTracker()
            n.sos_starts.clear()
            n.sos_releases.clear()
            while len(n.trackers) > MAX_BOOTS_KEPT:
                old = next(iter(n.trackers))
                n.trackers.pop(old)
                n.boot_last_rx.pop(old, None)

        order = n.trackers[boot].add(seq)
        if not order:
            n.dup += 1
            self.totals["dup"] += 1
            return "dup"

        self.totals["packets"] += 1
        n.boot_last_rx[boot] = now
        n.rx += 1
        n.types.add(ptype)
        n.last_rx = now
        n.source = source
        relayed = obj.get("via") == "relay" or bool(obj.get("relayed"))
        if relayed:
            n.relayed += 1
        if not n.online:
            if n.rx > 1 and not switched:
                self._event(now, node_id, "comm_restored", "info", {}, source, obj)
            n.online = True

        packet = dict(obj, rx_ts=now, source=source, port=port)
        if order == "late":
            # 더 새 패킷을 이미 받았다: 최신 상태는 덮지 않고 한 번만 일어나는 사건만 반영한다.
            n.late += 1
            self.totals["late"] += 1
            if ptype == "soldier":
                self._late_soldier_sos(now, n, packet, source)
            elif ptype == "env":
                self._env_events(now, n, packet, source)
            elif ptype == "anchor":
                self._anchor_obs(now, node_id, packet)  # 관측 시각으로 최신 여부를 따로 판단
            return "late"

        n.last_seq = seq
        n.virtual = bool(obj.get("virtual")) or source == "virtual"
        n.via = "relay" if relayed else "direct"
        prev = n.latest.get(ptype)
        n.latest[ptype] = packet

        if ptype == "soldier":
            self._soldier_events(now, n, prev, packet, source)
        elif ptype == "env":
            self._env_events(now, n, packet, source)
        elif ptype == "anchor":
            self._anchor_obs(now, node_id, packet)
        return "ok"

    def _soldier_events(self, now, n, prev, p, source):
        prev = prev or {}
        if p.get("sos") and not prev.get("sos"):
            n.sos_starts.append(p["seq"])
            self._event(now, n.node, "sos", "critical", {"seq": p.get("seq")}, source, p)
        elif prev.get("sos") and not p.get("sos"):
            n.sos_releases.append(p["seq"])
        alert = str(p.get("alert") or "none")
        if alert != "none" and alert != str(prev.get("alert") or "none"):
            level = "critical" if alert == "priority" else "warning"
            self._event(now, n.node, "alert:" + alert, level, {"reasons": p.get("reasons", [])},
                        source, p)
        if p.get("hr_valid") is False and prev.get("hr_valid") is not False:
            self._event(now, n.node, "hr_contact", "info", {}, source, p)
        gps = p.get("gps")
        prev_gps = prev.get("gps")
        if isinstance(gps, dict) and isinstance(prev_gps, dict):
            if prev_gps.get("valid") and not gps.get("valid"):
                self._event(now, n.node, "gps_lost", "info", {}, source, p)

    def _late_soldier_sos(self, now, n, p, source):
        """늦게 온 sos 패킷이 아직 알리지 않은 SOS 구간이면 이벤트를 만든다.

        직전 해제(seq < 이 패킷) 이후 시작된 SOS 이벤트가 이미 있으면 같은 구간이라 알리지 않는다.
        """
        if not p.get("sos"):
            return
        seq = p["seq"]
        prior = [r for r in n.sos_releases if r < seq]
        since = max(prior) if prior else None
        if any(st <= seq and (since is None or st > since) for st in n.sos_starts):
            return
        n.sos_starts.append(seq)
        self._event(now, n.node, "sos", "critical", {"seq": seq, "late": True}, source, p)

    def _env_events(self, now, n, p, source):
        events = p.get("events")
        if not isinstance(events, list):
            return
        for name in events:
            if not isinstance(name, str):
                continue
            self._event(now, n.node, "env:" + name, ENV_EVENT_LEVEL.get(name, "info"),
                        {"temp": p.get("temp")}, source, p)

    def _anchor_obs(self, now, anchor_id, p):
        obs = p.get("obs")
        if not isinstance(obs, list):
            return
        table = self.anchors.setdefault(anchor_id, {})
        for o in obs:
            if not isinstance(o, dict):
                continue
            sid = _as_int(o.get("soldier"))
            if sid is None:
                continue
            age_ms = o.get("age_ms")
            if (not isinstance(age_ms, (int, float)) or isinstance(age_ms, bool)
                    or not math.isfinite(age_ms) or age_ms < 0):
                age_ms = 0
            seen_ts = now - age_ms / 1000.0
            cur = table.get(sid)
            if cur is not None and cur["seen_ts"] > seen_ts:
                continue
            table[sid] = {
                "rssi": o.get("rssi"), "rssi_avg": o.get("rssi_avg"), "n": o.get("n"),
                "last_seq": o.get("last_seq"), "seen_ts": seen_ts, "report_rx": now,
                "virtual": p.get("virtual", False) or p.get("source") == "virtual",
            }

    # ----- 이벤트 -----
    def _event(self, now, node, kind, level, detail, source, pkt):
        ev = {
            "id": next(self._ids), "ts": now, "node": node, "kind": kind, "level": level,
            "detail": detail, "source": source,
            "virtual": bool(pkt.get("virtual")) or source == "virtual",
            "boot": pkt.get("boot"), "seq": pkt.get("seq"),
            "acked_at": None, "resolved_at": None,
        }
        if len(self.events) == self.events.maxlen:
            self.events_by_id.pop(self.events[0]["id"], None)
        self.events.append(ev)
        self.events_by_id[ev["id"]] = ev
        if self.logger:
            self.logger.event(ev)
        self._notify("event", ev)
        return ev

    def mark_event(self, event_id, action, now, by=None):
        """action: "ack"(지휘관 확인) | "resolve"(실제 해결). 확인과 해결은 따로 기록한다."""
        with self.lock:
            ev = self.events_by_id.get(event_id)
            if ev is None or action not in ("ack", "resolve"):
                return None
            key = "acked_at" if action == "ack" else "resolved_at"
            if ev[key] is None:
                ev[key] = now
                if by:
                    ev[action + "_by"] = by
                if self.logger:
                    self.logger.event_update(now, event_id, action, by)
                self._notify("event", ev)
                self._changed()
            return dict(ev)

    # ----- 주기 점검 -----
    def tick(self, now):
        with self.lock:
            changed = False
            for n in self.nodes.values():
                timeout = n.timeout_s()
                if timeout is None:  # 앵커 전용: 판정하지 않음
                    continue
                if n.online and n.last_rx is not None and now - n.last_rx > timeout:
                    n.online = False
                    changed = True
                    self._event(now, n.node, "comm_lost", "warning",
                                {"last_rx": n.last_rx, "timeout_s": timeout},
                                n.source, {"virtual": n.virtual, "boot": n.boot, "seq": n.last_seq})
            if changed:
                self._changed()

    # ----- 조회 -----
    def snapshot(self, now, virtual_status=None):
        with self.lock:
            return {
                "server_time": now,
                "version": self.version,
                "nodes": {str(k): v.snapshot(now) for k, v in sorted(self.nodes.items())},
                "anchors": {str(a): {str(s): dict(o, age_s=round(now - o["seen_ts"], 1))
                                     for s, o in sorted(t.items())}
                            for a, t in sorted(self.anchors.items())},
                "device_stats": {str(k): v for k, v in self.device_stats.items()},
                "totals": dict(self.totals),
                "virtual": virtual_status,
            }

    def list_events(self, since_id=0, limit=200):
        """since_id보다 새 이벤트 중 최근 limit개(복사본). limit <= 0이면 빈 목록."""
        with self.lock:
            if limit <= 0:
                return []
            out = [dict(e) for e in self.events if e["id"] > since_id]
            return out[-limit:]
