"""가상 노드 (규격 v1). 하드웨어 도착 전 시험용.

병사 halo_01·halo_02, 환경 노드 env_01(앵커 겸용), 게이트웨이 앵커 gateway_01을 흉내 내
게이트웨이가 USB로 내보낼 NDJSON과 같은 패킷을 만든다.
모든 패킷은 source="simulation", transport.route="simulation"(중계 시험은 "relay")이다.

시나리오는 (시각 초, 노드, 동작, 값) 목록이다. step(t)에 모의 시각을 넘겨 진행하므로 시험에서도 쓴다.
"""

import math
import random
import threading
import time

from .schema import SCHEMA_VERSION

SOLDIERS = ("halo_01", "halo_02")
ENV_NODE = "env_01"
GATEWAY = "gateway_01"
RELAY = "relay_01"
ALL_NODES = SOLDIERS + (ENV_NODE, GATEWAY)

SOLDIER_HB_MS = 10000  # 두절 기준 max(15000, 3×10000+2000) = 32초
ENV_HB_MS = 10000
ANCHOR_REPORT_S = 15.0

# 구역별 앵커 RSSI 기준값(dBm). 구역 A = 환경 노드 근처, B = 게이트웨이 근처
ZONE_RSSI = {"A": {ENV_NODE: -55, GATEWAY: -80}, "B": {ENV_NODE: -80, GATEWAY: -57}}

SCENARIOS = {
    "normal": [],
    # 규격 11장 시연: 정상 → 병사 01 SOS → (지휘관 확인) → 병사 02 두절 → 복구 → (조치 종료)
    "demo": [(15, "halo_01", "sos", None), (35, "halo_02", "drop", True),
             (85, "halo_02", "drop", False)],
    # SOS, 같은 사건의 새 패킷 재보고(같은 event_id·새 seq), 같은 패킷 중복, 새로 누른 SOS(새 event_id)
    "sos": [(10, "halo_01", "sos", None), (13, "halo_01", "sos_repeat", None),
            (16, "halo_01", "dup_next", None), (30, "halo_01", "sos", None)],
    "impact": [(10, "halo_01", "impact", None), (35, "halo_01", "prolonged_still", None),
               (60, "halo_01", "recover", None)],
    "loss": [(10, "halo_02", "drop", True), (70, "halo_02", "drop", False)],
    "reboot": [(10, "halo_01", "reboot", None)],
    "dup": [(5, "halo_01", "dup", True), (35, "halo_01", "dup", False)],
    "late": [(10, "halo_01", "late", None)],
    "hr_contact": [(10, "halo_02", "hr_quality", "no_contact"), (30, "halo_02", "hr_quality", "good")],
    "gps": [(5, "halo_01", "gps", "on"), (25, "halo_01", "gps", "lost"),
            (45, "halo_01", "gps", "on"), (65, "halo_01", "gps", "off")],
    "relay": [(10, "halo_01", "relay", True), (40, "halo_01", "relay", False)],
    "covert": [(10, "halo_01", "mode", "covert"), (40, "halo_01", "mode", "normal")],
    "heat": [(10, ENV_NODE, "heat", 37.0), (60, ENV_NODE, "heat", 24.0)],
    "env_sensors": [(5, ENV_NODE, "detect", "sound"), (15, ENV_NODE, "detect", "shock"),
                    (25, ENV_NODE, "reed", False), (35, ENV_NODE, "reed", True)],
    "move": [(10, "halo_01", "zone", "B"), (40, "halo_01", "zone", "A")],
}


def _build_all():
    order = ["sos", "impact", "loss", "reboot", "dup", "late", "hr_contact", "gps", "relay",
             "covert", "heat", "env_sensors", "move"]
    out, offset = [], 0
    for name in order:
        steps = SCENARIOS[name]
        out += [(offset + t, n, a, v) for t, n, a, v in steps]
        offset += max(t for t, *_ in steps) + 40  # 두절이 풀리고 상태가 안정될 시간
    return out


SCENARIOS["all"] = _build_all()  # 도착 전 통합 시험


def scenario_length(name):
    steps = SCENARIOS[name]
    return (max(t for t, *_ in steps) + 20) if steps else 60


def transport(route="simulation", relay_id=None, gateway_id=GATEWAY):
    return {"gateway_id": gateway_id, "route": route, "hop_count": 1 if route == "relay" else 0,
            "relay_id": relay_id, "rssi_dbm": None}


class _Node:
    def __init__(self, node_id, rng, t):
        self.node_id = node_id
        self.rng = rng
        self.new_boot(t)

    def new_boot(self, t):
        self.boot_id = f"boot_{self.rng.randrange(16 ** 4):04x}"
        self.boot_t = t
        self.seq = 0
        self.counters = {}

    def packet(self, ptype, t, payload, route="simulation", relay_id=None):
        self.seq += 1
        return {
            "schema_version": SCHEMA_VERSION, "packet_type": ptype, "node_id": self.node_id,
            "boot_id": self.boot_id, "seq": self.seq, "source": "simulation",
            "uptime_ms": int((t - self.boot_t) * 1000), "payload": payload,
            "transport": transport(route, relay_id),
        }

    def next_event_id(self, event_type):
        k = self.counters.get(event_type, 0) + 1
        self.counters[event_type] = k
        return f"{self.node_id}:{self.boot_id}:{event_type}:{k}"


class VSoldier(_Node):
    def __init__(self, node_id, rng, t):
        super().__init__(node_id, rng, t)
        self.mode = "normal"
        self.hr = rng.randint(70, 85)
        self.hr_quality = "good"
        self.motion = "moving"
        self.gps_enabled = False
        self.gps_fix = True
        self.lat = 37.5000 + int(node_id[-2:]) * 0.0003
        self.lon = 127.0000 + int(node_id[-2:]) * 0.0003
        self.zone = "A" if node_id == "halo_01" else "B"
        self.drop = False
        self.dup = False
        self.dup_next = False
        self.relay = False
        self.late_pending = False
        self.held = None
        self.silent_until = 0.0
        self.next_tx = 0.0
        self.last_sos = None  # 재보고용 (event_id, mode)

    def route(self):
        return ("relay", RELAY) if self.relay else ("simulation", None)

    def status_payload(self):
        return {
            "mode": self.mode,
            "heart_rate_bpm": self.hr if self.hr_quality == "good" else None,
            "heart_rate_quality": self.hr_quality,
            "motion_state": self.motion,
            "heartbeat_interval_ms": SOLDIER_HB_MS,
            "sensor_status": {"heart_rate": "ok", "imu": "ok", "body_temperature": "not_implemented",
                              "gps": "ok" if self.gps_enabled else "disabled"},
            "body_temperature_c": None,  # 체온 실측 미구현
        }

    def gps_payload(self):
        if self.gps_fix:
            return {"fix_valid": True, "latitude_deg": round(self.lat, 6),
                    "longitude_deg": round(self.lon, 6), "hdop": 1.2}
        return {"fix_valid": False, "latitude_deg": None, "longitude_deg": None, "hdop": None}

    def event_payload(self, event_type, event_id=None):
        return {"event_id": event_id or self.next_event_id(event_type), "event_type": event_type,
                "mode": self.mode}


class VEnv(_Node):
    def __init__(self, rng, t):
        super().__init__(ENV_NODE, rng, t)
        self.temp = 24.0
        self.target = 24.0
        self.hum = 45
        self.light = 1700
        self.heat = False
        self.detected = {"sound": False, "flame": False, "shock": False}
        self.reed_closed = True
        self.next_tx = 0.0
        self.pending_events = []

    def update(self, t, dt):
        if abs(self.target - self.temp) > 0.05:
            step = 1.5 * dt  # 초당 1.5°C
            self.temp += max(-step, min(step, self.target - self.temp))
        if not self.heat and self.temp >= 35.0:
            self.heat = True
            self.pending_events.append("heat_exposure")
            self.next_tx = t
        elif self.heat and self.temp <= 34.0:
            self.heat = False
            self.next_tx = t

    def env_payload(self):
        detected, self.detected = self.detected, {k: False for k in self.detected}
        return {
            "air_temperature_c": round(self.temp, 1), "humidity_pct": self.hum,
            "light_raw": self.light + self.rng.randint(-30, 30), "heartbeat_interval_ms": ENV_HB_MS,
            "sensor_status": {"dht11": "ok", "light": "ok", "sound": "ok", "flame": "ok",
                              "shock": "ok", "reed": "ok"},
            "sound_detected": detected["sound"], "flame_detected": detected["flame"],
            "shock_detected": detected["shock"], "reed_closed": self.reed_closed,
        }


class VAnchor:
    def __init__(self, node):
        self.node = node  # 앵커 노드(환경 노드면 환경 패킷과 seq를 같이 쓴다)
        self.next_tx = 5.0
        self.reported_zone = {}


class Simulator:
    def __init__(self, emit, scenario="normal", nodes=None, seed=None, loop=False, loss_rate=0.0):
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario: " + str(scenario))
        if not 0.0 <= loss_rate <= 1.0:
            raise ValueError("loss_rate must be between 0 and 1")
        nodes = tuple(nodes) if nodes else ALL_NODES
        unknown = [n for n in nodes if n not in ALL_NODES]
        if unknown:
            raise ValueError(f"unknown virtual nodes: {unknown} (가능: {list(ALL_NODES)})")
        self.emit = emit
        self.scenario = scenario
        self.nodes = nodes
        self.loop = loop
        self.loss_rate = loss_rate
        self.rng = random.Random(seed)
        self.length = scenario_length(scenario)
        self.t = 0.0
        self.base = 0.0
        self.soldiers = {n: VSoldier(n, self.rng, 0.0) for n in SOLDIERS if n in nodes}
        self.env = VEnv(self.rng, 0.0) if ENV_NODE in nodes else None
        self.anchors = []
        if self.env is not None:
            self.anchors.append(VAnchor(self.env))
        if GATEWAY in nodes:
            self.anchors.append(VAnchor(_Node(GATEWAY, self.rng, 0.0)))
        self.steps = sorted(SCENARIOS[scenario], key=lambda s: s[0])
        self.step_idx = 0

    def status(self):
        return {"scenario": self.scenario, "nodes": list(self.nodes), "t": round(self.t, 1),
                "length_s": self.length, "loop": self.loop}

    # ----- 내보내기 -----
    def _send(self, s, pkt):
        """병사 패킷 하나. 누락(drop·loss_rate)·중복·순서 바꿈 시험을 여기서 적용한다."""
        if s.drop or (self.loss_rate and self.rng.random() < self.loss_rate):
            return  # 무선 누락: seq는 올라가고 PC는 못 받는다
        if s.late_pending and pkt["packet_type"] == "soldier_status":
            if s.held is None:
                s.held = pkt  # 이 패킷을 붙잡아 두었다가 다음 패킷 뒤에 보낸다
                return
            self.emit(pkt)
            late = dict(s.held, transport=transport("relay", RELAY))  # 중계로 늦게 도착한 것처럼
            s.held, s.late_pending = None, False
            self.emit(late)
            return
        self.emit(pkt)
        if s.dup or s.dup_next:
            self.emit(dict(pkt))
            s.dup_next = False

    def _soldier_event(self, s, event_type, t, event_id=None):
        route, relay_id = s.route()
        self._send(s, s.packet("event", t, s.event_payload(event_type, event_id), route, relay_id))

    # ----- 시나리오 동작 -----
    def _apply(self, node, action, value):
        t = self.t
        if node == ENV_NODE:
            e = self.env
            if e is None:
                return
            if action == "heat":
                e.target = value
            elif action == "detect":
                e.detected[value] = True
                e.next_tx = t
            elif action == "reed":
                e.reed_closed = value
                e.next_tx = t
            return
        s = self.soldiers.get(node)
        if s is None:
            return
        if action == "sos":
            payload = s.event_payload("sos")
            s.last_sos = payload["event_id"]
            route, relay_id = s.route()
            self._send(s, s.packet("event", t, payload, route, relay_id))
        elif action == "sos_repeat" and s.last_sos:
            self._soldier_event(s, "sos", t, event_id=s.last_sos)
        elif action == "dup_next":
            s.dup_next = True
            s.next_tx = t
        elif action == "impact":
            s.motion = "still"
            self._soldier_event(s, "impact", t)
            s.next_tx = t
        elif action == "prolonged_still":
            self._soldier_event(s, "prolonged_still", t)
        elif action == "recover":
            s.motion = "moving"
            s.next_tx = t
        elif action == "drop":
            s.drop = value
        elif action == "dup":
            s.dup = value
        elif action == "late":
            s.late_pending = True
        elif action == "reboot":
            s.new_boot(t)
            s.silent_until = t + 3.0
            s.next_tx = t + 3.0
        elif action == "hr_quality":
            s.hr_quality = value
            s.next_tx = t
        elif action == "gps":
            s.gps_enabled = value != "off"
            s.gps_fix = value == "on"
            s.next_tx = t
        elif action == "relay":
            s.relay = value
            s.next_tx = t
        elif action == "mode":
            s.mode = value
            s.next_tx = t
        elif action == "zone":
            s.zone = value

    # ----- 진행 -----
    def step(self, t):
        dt = max(0.0, t - self.t)
        self.t = t
        rel = t - self.base
        while self.step_idx < len(self.steps) and self.steps[self.step_idx][0] <= rel:
            _, node, action, value = self.steps[self.step_idx]
            self._apply(node, action, value)
            self.step_idx += 1
        if self.loop and rel >= self.length:
            self.base = t
            self.step_idx = 0

        for s in self.soldiers.values():
            if s.motion == "moving" and s.hr_quality == "good":
                s.hr = max(55, min(110, s.hr + self.rng.randint(-2, 2)))
            if t >= s.next_tx and t >= s.silent_until:
                s.next_tx = t + SOLDIER_HB_MS / 1000.0
                route, relay_id = s.route()
                self._send(s, s.packet("soldier_status", t, s.status_payload(), route, relay_id))
                if s.gps_enabled:
                    self._send(s, s.packet("gps", t, s.gps_payload(), route, relay_id))

        e = self.env
        if e is not None:
            e.update(t, dt)
            for event_type in e.pending_events:
                self.emit(e.packet("event", t, {"event_id": e.next_event_id(event_type),
                                                "event_type": event_type, "mode": "normal"}))
            e.pending_events = []
            if t >= e.next_tx:
                e.next_tx = t + ENV_HB_MS / 1000.0
                self.emit(e.packet("environment", t, e.env_payload()))

        for a in self.anchors:
            self._anchor_step(a, t)

    def _anchor_step(self, a, t):
        visible = []
        for s in self.soldiers.values():
            if s.drop or t < s.silent_until or s.seq == 0:
                continue
            if a.node.node_id == GATEWAY and s.relay:
                continue  # 직접 경로 차단: 게이트웨이 앵커는 직접 방송을 못 받음
            visible.append(s)
        zone_changed = any(a.reported_zone.get(s.node_id) != s.zone for s in visible)
        if not visible or (t < a.next_tx and not zone_changed):
            return
        if zone_changed and t < a.next_tx - ANCHOR_REPORT_S + 2.0:
            return  # 최소 보고 간격 2초
        a.next_tx = t + ANCHOR_REPORT_S
        for s in visible:
            a.reported_zone[s.node_id] = s.zone
            base = ZONE_RSSI[s.zone][a.node.node_id]
            self.emit(a.node.packet("anchor_observation", t, {
                "anchor_id": a.node.node_id, "observed_node_id": s.node_id,
                "observed_boot_id": s.boot_id, "observed_seq": s.seq,
                "rssi_dbm": base + self.rng.randint(-3, 3),
                "observation_age_ms": self.rng.randint(0, 900),
            }))


class VirtualRunner(threading.Thread):
    """Simulator를 실시간(speed 배속)으로 돌려 허브에 넣는다."""

    def __init__(self, hub, speed=1.0, **sim_kwargs):
        if not (speed > 0 and math.isfinite(speed)):
            raise ValueError("virtual speed must be a finite number > 0")
        super().__init__(daemon=True, name="virtual")
        self.hub = hub
        self.speed = speed
        self.sim = Simulator(self._emit, **sim_kwargs)
        self._stop_evt = threading.Event()

    def _emit(self, obj):
        self.hub.ingest(obj, "sim", "sim")

    def run(self):
        start = time.monotonic()
        while not self._stop_evt.wait(0.1):
            self.sim.step((time.monotonic() - start) * self.speed)

    def status(self):
        return dict(self.sim.status(), running=self.is_alive(), speed=self.speed)

    def stop(self):
        self._stop_evt.set()
