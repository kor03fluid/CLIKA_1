"""SQUAD LINK 공통 데이터 규격 v1 검사 (docs/data_spec_v1.md).

validate(obj)는 (정규화한 패킷, 오류 목록, 경고 목록)을 돌려준다.
- 오류: 필수 필드 누락, 자료형·enum·범위 위반. 이런 패킷은 받지 않는다.
- 경고: 규칙 위반이지만 안전하게 고칠 수 있는 경우. 고친 값으로 받고 경고를 남긴다
  (예: 심박 품질이 good이 아닌데 bpm이 있음 → bpm을 null로).
정규화한 패킷은 원본을 바꾸지 않은 복사본이다.
"""

import math

SCHEMA_VERSION = "1.0"

PACKET_TYPES = ("soldier_status", "event", "environment", "gps", "anchor_observation")
SOURCES = ("device", "simulation")
ROUTES = ("direct", "relay", "simulation")
MODES = ("normal", "covert")
HEART_RATE_QUALITY = ("good", "poor", "no_contact", "unavailable")
MOTION_STATES = ("moving", "still", "unknown")
SENSOR_STATES = ("ok", "unavailable", "not_implemented", "disabled")
EVENT_TYPES = ("sos", "impact", "prolonged_still", "heat_exposure")

SOLDIER_SENSORS = ("heart_rate", "imu", "body_temperature", "gps")
ENV_SENSORS = ("dht11", "light")
# 선택 필드 -> sensor_status에 함께 넣어야 하는 키
ENV_OPTIONAL = {"sound_detected": "sound", "flame_detected": "flame",
                "shock_detected": "shock", "reed_closed": "reed"}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def _join(path, key):
    return path + "." + key if path else key


class _Checker:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def err(self, path, msg):
        self.errors.append(f"{path}: {msg}")

    def warn(self, path, msg):
        self.warnings.append(f"{path}: {msg}")

    def required(self, d, key, path):
        if key not in d:
            self.err(_join(path, key), "필수 필드 없음")
            return False
        return True

    def string(self, d, key, path, nonempty=True):
        if not self.required(d, key, path):
            return
        v = d[key]
        if not isinstance(v, str) or (nonempty and not v):
            self.err(_join(path, key), "비어 있지 않은 문자열이어야 함")

    def enum(self, d, key, path, allowed):
        if not self.required(d, key, path):
            return
        if d[key] not in allowed:
            self.err(_join(path, key), f"허용값 {list(allowed)} 중 하나여야 함 (받은 값 {d[key]!r})")

    def integer(self, d, key, path, minimum=None, positive=False):
        if not self.required(d, key, path):
            return
        v = d[key]
        if not is_int(v):
            self.err(_join(path, key), "정수여야 함")
        elif positive and v <= 0:
            self.err(_join(path, key), "양수여야 함")
        elif minimum is not None and v < minimum:
            self.err(_join(path, key), f"{minimum} 이상이어야 함")

    def number_or_null(self, d, key, path, lo=None, hi=None, required=True):
        if key not in d:
            if required:
                self.err(_join(path, key), "필수 필드 없음(측정 불가면 null)")
            return
        v = d[key]
        if v is None:
            return
        if not is_num(v):
            self.err(_join(path, key), "숫자 또는 null이어야 함")
        elif (lo is not None and v < lo) or (hi is not None and v > hi):
            self.err(_join(path, key), f"범위 {lo}~{hi}를 벗어남 ({v})")

    def bool_or_null(self, d, key, path):
        v = d[key]
        if v is not None and not isinstance(v, bool):
            self.err(_join(path, key), "true/false 또는 null이어야 함")

    def obj(self, d, key, path):
        if not self.required(d, key, path):
            return None
        if not isinstance(d[key], dict):
            self.err(_join(path, key), "객체여야 함")
            return None
        return d[key]

    def sensor_status(self, payload, path, keys):
        st = self.obj(payload, "sensor_status", path)
        if st is None:
            return None
        for k in keys:
            self.enum(st, k, f"{path}.sensor_status", SENSOR_STATES)
        for k, v in st.items():
            if k not in keys and v not in SENSOR_STATES:
                self.err(f"{path}.sensor_status.{k}", f"허용값 {list(SENSOR_STATES)} 중 하나여야 함")
        return st


def _soldier_status(c, p, pkt):
    path = "payload"
    c.enum(p, "mode", path, MODES)
    c.number_or_null(p, "heart_rate_bpm", path, lo=0)
    c.enum(p, "heart_rate_quality", path, HEART_RATE_QUALITY)
    c.enum(p, "motion_state", path, MOTION_STATES)
    c.integer(p, "heartbeat_interval_ms", path, positive=True)
    st = c.sensor_status(p, path, SOLDIER_SENSORS)
    c.number_or_null(p, "body_temperature_c", path)
    c.number_or_null(p, "battery_voltage_v", path, lo=0, required=False)
    if c.errors:
        return
    if p["heart_rate_quality"] != "good" and p["heart_rate_bpm"] is not None:
        c.warn(f"{path}.heart_rate_bpm", "심박 품질이 good이 아니면 null이어야 함 → null로 바꿈")
        p["heart_rate_bpm"] = None
    if (pkt["source"] == "device" and st.get("body_temperature") == "not_implemented"
            and p["body_temperature_c"] is not None):
        c.warn(f"{path}.body_temperature_c", "체온 센서 미구현인 실제 노드는 null이어야 함 → null로 바꿈")
        p["body_temperature_c"] = None


def _event(c, p, pkt):
    path = "payload"
    c.string(p, "event_id", path)
    c.enum(p, "event_type", path, EVENT_TYPES)
    c.enum(p, "mode", path, MODES)


def _environment(c, p, pkt):
    path = "payload"
    c.number_or_null(p, "air_temperature_c", path)
    c.number_or_null(p, "humidity_pct", path, lo=0, hi=100)
    if c.required(p, "light_raw", path):
        v = p["light_raw"]
        if v is not None and (not is_int(v) or v < 0):
            c.err(f"{path}.light_raw", "0 이상 정수 또는 null이어야 함")
    c.integer(p, "heartbeat_interval_ms", path, positive=True)
    st = c.sensor_status(p, path, ENV_SENSORS)
    for key, sensor in ENV_OPTIONAL.items():
        if key in p:
            c.bool_or_null(p, key, path)
            if st is not None and sensor not in st:
                c.warn(f"{path}.sensor_status", f"{key}를 쓰면 sensor_status.{sensor}도 넣어야 함")


def _gps(c, p, pkt):
    path = "payload"
    if c.required(p, "fix_valid", path) and not isinstance(p["fix_valid"], bool):
        c.err(f"{path}.fix_valid", "true/false여야 함")
    c.number_or_null(p, "latitude_deg", path, lo=-90, hi=90)
    c.number_or_null(p, "longitude_deg", path, lo=-180, hi=180)
    c.number_or_null(p, "hdop", path, lo=0)
    if c.errors:
        return
    if p["fix_valid"]:
        if p["latitude_deg"] is None or p["longitude_deg"] is None:
            c.err(path, "fix_valid가 true면 위도·경도가 있어야 함")
    elif any(p[k] is not None for k in ("latitude_deg", "longitude_deg", "hdop")):
        c.warn(path, "fix_valid가 false면 좌표·hdop은 null이어야 함 → null로 바꿈")
        for k in ("latitude_deg", "longitude_deg", "hdop"):
            p[k] = None


def _anchor_observation(c, p, pkt):
    path = "payload"
    c.string(p, "anchor_id", path)
    c.string(p, "observed_node_id", path)
    c.string(p, "observed_boot_id", path)
    c.integer(p, "observed_seq", path, minimum=0)
    if c.required(p, "rssi_dbm", path) and not is_num(p["rssi_dbm"]):
        c.err(f"{path}.rssi_dbm", "숫자여야 함")
    c.integer(p, "observation_age_ms", path, minimum=0)
    if not c.errors and p["anchor_id"] != pkt["node_id"]:
        c.warn(f"{path}.anchor_id", "원본 node_id와 같아야 함")


_PAYLOAD_CHECKS = {
    "soldier_status": _soldier_status,
    "event": _event,
    "environment": _environment,
    "gps": _gps,
    "anchor_observation": _anchor_observation,
}


def validate(obj):
    """(정규화한 패킷 또는 None, 오류 목록, 경고 목록)."""
    c = _Checker()
    if not isinstance(obj, dict):
        return None, ["JSON 객체가 아님"], []
    if obj.get("schema_version") != SCHEMA_VERSION:
        c.err("schema_version", f'"{SCHEMA_VERSION}"이어야 함 (받은 값 {obj.get("schema_version")!r})')
    c.enum(obj, "packet_type", "", PACKET_TYPES)
    c.string(obj, "node_id", "")
    c.string(obj, "boot_id", "")
    c.integer(obj, "seq", "", minimum=0)
    c.enum(obj, "source", "", SOURCES)
    c.integer(obj, "uptime_ms", "", minimum=0)
    payload = c.obj(obj, "payload", "")
    transport = c.obj(obj, "transport", "")
    if transport is not None:
        tp = "transport"
        c.string(transport, "gateway_id", tp)
        c.enum(transport, "route", tp, ROUTES)
        c.integer(transport, "hop_count", tp, minimum=0)
        if c.required(transport, "relay_id", tp):
            rid = transport["relay_id"]
            if rid is not None and (not isinstance(rid, str) or not rid):
                c.err(f"{tp}.relay_id", "문자열 또는 null이어야 함")
        c.number_or_null(transport, "rssi_dbm", tp)
    if c.errors:
        return None, c.errors, c.warnings

    pkt = dict(obj)
    pkt["payload"] = dict(payload)
    pkt["transport"] = dict(transport)
    if "sensor_status" in pkt["payload"] and isinstance(pkt["payload"]["sensor_status"], dict):
        pkt["payload"]["sensor_status"] = dict(pkt["payload"]["sensor_status"])
    _PAYLOAD_CHECKS[pkt["packet_type"]](c, pkt["payload"], pkt)
    if c.errors:
        return None, c.errors, c.warnings

    t = pkt["transport"]
    if t["route"] == "relay" and (t["hop_count"] != 1 or t["relay_id"] is None):
        c.warn("transport", "route가 relay면 hop_count 1, relay_id가 있어야 함")
    if t["route"] != "relay" and (t["hop_count"] != 0 or t["relay_id"] is not None):
        c.warn("transport", "직접·가상 경로는 hop_count 0, relay_id null이어야 함")
    return pkt, c.errors, c.warnings


def timeout_ms(heartbeat_interval_ms):
    """규격 10장: 통신 두절 기준."""
    return max(15000, 3 * heartbeat_interval_ms + 2000)
