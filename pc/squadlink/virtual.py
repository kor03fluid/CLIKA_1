"""가상 노드: 병사 2명·환경 노드·게이트웨이 앵커를 흉내 내 실제와 같은 JSON 줄을 만든다.

모든 패킷에 "virtual": true가 붙고 허브에는 source="virtual"로 들어가므로 실측과 섞이지 않는다.
시나리오는 (시각 초, 노드, 동작, 값) 목록이다. step(t)에 모의 시각을 넘겨 진행하므로 시험에서도 쓴다.
"""

import math
import random
import threading
import time

SOLDIERS = (1, 2)
ENV_NODE = 0x31
GW_ANCHOR = 0x20
RELAY_ID = 0x21
ALL_NODES = SOLDIERS + (ENV_NODE, GW_ANCHOR)

# 구역별 앵커 RSSI 기준값(dBm). 구역 A = 환경 노드 근처, B = 게이트웨이 근처
ZONE_RSSI = {"A": {ENV_NODE: -55, GW_ANCHOR: -80}, "B": {ENV_NODE: -80, GW_ANCHOR: -57}}

SCENARIOS = {
    "normal": [],
    "sos": [(10, 2, "sos", True), (40, 2, "sos", False)],
    "fall": [(10, 1, "fall", None), (60, 1, "recover", None)],
    "loss": [(10, 2, "drop", True), (90, 2, "drop", False)],
    "reboot": [(10, 1, "reboot", None)],
    "dup": [(5, 1, "dup", True), (35, 1, "dup", False)],
    "gps_fail": [(10, 1, "gps", False), (50, 1, "gps", True)],
    "relay": [(10, 1, "relay", True), (40, 1, "relay", False)],
    "heat": [(10, None, "heat", 37.0), (60, None, "heat", 24.0)],
    "move": [(10, 1, "zone", "B"), (40, 1, "zone", "A")],
    "hr_contact": [(10, 2, "hr_valid", False), (30, 2, "hr_valid", True)],
    "env_events": [(5, None, "env_event", "sound"), (15, None, "env_event", "shock"),
                   (25, None, "env_event", "reed")],
    # 90초 시연 흐름: 쓰러짐(충격 후 무움직임) → SOS → 중계 경유 → 복귀
    "demo": [(15, 1, "fall", None), (25, 2, "sos", True), (40, 1, "relay", True),
             (60, 1, "relay", False), (70, 2, "sos", False), (75, 1, "recover", None)],
}


def _build_all():
    order = ["sos", "fall", "loss", "reboot", "dup", "gps_fail", "relay", "heat", "move",
             "hr_contact", "env_events"]
    out, offset = [], 0
    for name in order:
        steps = SCENARIOS[name]
        out += [(offset + t, n, a, v) for t, n, a, v in steps]
        offset += max(t for t, *_ in steps) + 20
    return out


SCENARIOS["all"] = _build_all()  # 도착 전 통합 시험: 노드 2개·환경·SOS·중복·누락·재부팅·위치 실패 등


def scenario_length(name):
    steps = SCENARIOS[name]
    return (max(t for t, *_ in steps) + 20) if steps else 60


class _Seq:
    def __init__(self, rng):
        self.rng = rng
        self.boot = rng.randint(1000, 60000)
        self.seq = 0

    def next(self):
        self.seq = (self.seq + 1) % 0x10000
        return self.seq

    def reboot(self):
        self.boot = (self.boot + 1) % 0x10000
        self.seq = 0


class VSoldier:
    NORMAL_S = 10.0
    ALERT_S = 3.0

    def __init__(self, node, rng):
        self.node = node
        self.rng = rng
        self.id = _Seq(rng)
        self.hr = rng.randint(70, 85)
        self.hr_valid = True
        self.motion = "active"
        self.alert = "none"
        self.reasons = []
        self.sos = False
        self.op_mode = "normal"
        self.gps_valid = True
        self.lat = 37.5000 + node * 0.0003
        self.lon = 127.0000 + node * 0.0003
        self.zone = "A" if node == 1 else "B"
        self.drop = False
        self.dup = False
        self.relay = False
        self.silent_until = 0.0
        self.fall_t = None
        self.next_tx = 0.0

    def interval(self):
        return self.ALERT_S if (self.sos or self.alert != "none") else self.NORMAL_S

    def update(self, t):
        if self.fall_t is not None:
            dt = t - self.fall_t
            if dt >= 2 and self.motion == "impact":
                self.motion, self.alert, self.reasons = "still", "check", ["impact_then_still"]
                self.next_tx = t
            if dt >= 17 and self.alert == "check":
                self.alert = "priority"
                self.next_tx = t
        if self.motion == "active":
            self.hr = max(55, min(110, self.hr + self.rng.randint(-2, 2)))

    def packet(self):
        p = {
            "type": "soldier", "node": self.node, "boot": self.id.boot, "seq": self.id.next(),
            "via": "relay" if self.relay else "direct",
            "op_mode": self.op_mode, "tx_mode": "adaptive",
            "hr": self.hr if self.hr_valid else None, "hr_valid": self.hr_valid,
            "motion": self.motion, "sos": self.sos, "alert": self.alert, "reasons": list(self.reasons),
            "body_temp": 36.6, "body_temp_virtual": True,  # 체온 실측 미구현: 항상 가상 필드
            "gps": ({"valid": True, "lat": round(self.lat, 6), "lon": round(self.lon, 6)}
                    if self.gps_valid else {"valid": False}),
            "virtual": True,
        }
        if self.relay:
            p["relay_id"] = RELAY_ID
        return p


class VEnv:
    HEARTBEAT_S = 30.0
    ALERT_S = 10.0

    def __init__(self, rng):
        self.rng = rng
        self.id = _Seq(rng)
        self.temp = 24.0
        self.target = 24.0
        self.hum = 40
        self.light = 60
        self.heat = False
        self.pending = []
        self.next_tx = 0.0

    def update(self, t, dt):
        if abs(self.target - self.temp) > 0.05:
            step = 1.5 * dt  # 초당 1.5°C
            self.temp += max(-step, min(step, self.target - self.temp))
        if not self.heat and self.temp >= 35.0:
            self.heat = True
            self.pending.append("heat")
            self.next_tx = t
        elif self.heat and self.temp <= 34.0:
            self.heat = False
            self.next_tx = t

    def interval(self):
        return self.ALERT_S if self.heat else self.HEARTBEAT_S

    def packet(self):
        events, self.pending = self.pending, []
        return {
            "type": "env", "node": ENV_NODE, "boot": self.id.boot, "seq": self.id.next(),
            "reason": "event" if events else "heartbeat", "tx_mode": "adaptive",
            "temp": round(self.temp, 1), "hum": self.hum, "light": self.light, "valid": 63,
            "events": events, "state": ["heat"] if self.heat else [], "virtual": True,
        }


class VAnchor:
    MAX_S = 15.0

    def __init__(self, node, seq):
        self.node = node
        self.id = seq  # 환경 노드 앵커는 환경 패킷과 seq를 같이 쓴다
        self.next_tx = 5.0
        self.reported_zone = {}

    def packet(self, obs):
        return {"type": "anchor", "node": self.node, "boot": self.id.boot, "seq": self.id.next(),
                "obs": obs, "virtual": True}


class Simulator:
    def __init__(self, emit, scenario="normal", nodes=None, seed=None, loop=False, loss_rate=0.0):
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario: " + str(scenario))
        if not 0.0 <= loss_rate <= 1.0:
            raise ValueError("loss_rate must be between 0 and 1")
        self.emit = emit
        self.scenario = scenario
        self.nodes = tuple(nodes) if nodes else ALL_NODES
        self.loop = loop
        self.loss_rate = loss_rate
        self.rng = random.Random(seed)
        self.length = scenario_length(scenario)
        self._reset()

    def _reset(self):
        rng = self.rng
        self.soldiers = {n: VSoldier(n, rng) for n in SOLDIERS if n in self.nodes}
        self.env = VEnv(rng) if ENV_NODE in self.nodes else None
        self.anchors = {}
        if ENV_NODE in self.nodes:
            self.anchors[ENV_NODE] = VAnchor(ENV_NODE, self.env.id)
        if GW_ANCHOR in self.nodes:
            self.anchors[GW_ANCHOR] = VAnchor(GW_ANCHOR, _Seq(rng))
        self.steps = sorted(SCENARIOS[self.scenario], key=lambda s: s[0])
        self.step_idx = 0
        self.t = 0.0
        self.base = 0.0  # loop 시 시나리오 시작 시각

    def status(self):
        return {"scenario": self.scenario, "nodes": list(self.nodes), "t": round(self.t, 1),
                "length_s": self.length, "loop": self.loop}

    # ----- 시나리오 동작 -----
    def _apply(self, node, action, value):
        t = self.t
        if action in ("heat", "env_event"):
            if self.env is None:
                return
            if action == "heat":
                self.env.target = value
            else:
                self.env.pending.append(value)
                self.env.next_tx = t
            return
        s = self.soldiers.get(node)
        if s is None:
            return
        if action == "sos":
            s.sos = value
            s.next_tx = t
        elif action == "fall":
            s.motion, s.fall_t = "impact", t
            s.next_tx = t
        elif action == "recover":
            s.motion, s.alert, s.reasons, s.fall_t = "active", "none", [], None
            s.next_tx = t
        elif action == "drop":
            s.drop = value
        elif action == "dup":
            s.dup = value
        elif action == "reboot":
            s.id.reboot()
            s.silent_until = t + 3.0
            s.next_tx = t + 3.0
        elif action == "gps":
            s.gps_valid = value
            s.next_tx = t
        elif action == "relay":
            s.relay = value
            s.next_tx = t
        elif action == "zone":
            s.zone = value
        elif action == "hr_valid":
            s.hr_valid = value
            s.next_tx = t

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
            s.update(t)
            if t >= s.next_tx and t >= s.silent_until:
                s.next_tx = t + s.interval()
                p = s.packet()
                if s.drop or (self.loss_rate and self.rng.random() < self.loss_rate):
                    continue  # 무선 누락: seq는 올라가고 PC는 못 받는다
                self.emit(p)
                if s.dup:
                    self.emit(dict(p))

        if self.env is not None:
            self.env.update(t, dt)
            if t >= self.env.next_tx:
                self.env.next_tx = t + self.env.interval()
                self.emit(self.env.packet())

        for a in self.anchors.values():
            self._anchor_step(a, t)

    def _anchor_step(self, a, t):
        obs, zone_changed = [], False
        for s in self.soldiers.values():
            if s.drop or t < s.silent_until:
                continue
            if a.node == GW_ANCHOR and s.relay:
                continue  # 직접 경로 차단: 게이트웨이 앵커는 직접 방송을 못 받음
            base = ZONE_RSSI[s.zone][a.node]
            obs.append({"soldier": s.node, "last_seq": s.id.seq, "rssi": base + self.rng.randint(-3, 3),
                        "rssi_avg": base, "n": 3, "age_ms": self.rng.randint(0, 900)})
            if a.reported_zone.get(s.node) != s.zone:
                zone_changed = True
        if not obs or (t < a.next_tx and not zone_changed):
            return
        if zone_changed and t < a.next_tx - a.MAX_S + 2.0:
            return  # 최소 보고 간격 2초
        a.next_tx = t + a.MAX_S
        for s in self.soldiers.values():
            a.reported_zone[s.node] = s.zone
        for i in range(0, len(obs), 2):  # 패킷당 2명
            self.emit(a.packet(obs[i:i + 2]))


class VirtualRunner(threading.Thread):
    """Simulator를 실시간(speed 배속)으로 돌려 허브에 넣는다."""

    def __init__(self, hub, clock=time.time, speed=1.0, **sim_kwargs):
        if not (speed > 0 and math.isfinite(speed)):
            raise ValueError("virtual speed must be a finite number > 0")
        super().__init__(daemon=True, name="virtual")
        self.hub = hub
        self.clock = clock
        self.speed = speed
        self.sim = Simulator(self._emit, **sim_kwargs)
        self._stop_evt = threading.Event()

    def _emit(self, obj):
        self.hub.ingest(obj, "virtual", "sim", self.clock())

    def run(self):
        start = time.monotonic()
        while not self._stop_evt.wait(0.1):
            self.sim.step((time.monotonic() - start) * self.speed)

    def status(self):
        return dict(self.sim.status(), running=self.is_alive(), speed=self.speed)

    def stop(self):
        self._stop_evt.set()
