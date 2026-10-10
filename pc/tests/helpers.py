"""시험용 가짜 시계와 규격 v1 패킷 생성기."""

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from squadlink.hub import Hub  # noqa: E402

WALL0 = 1791590000.0  # 2026-10-10 경


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def wall(self):
        return WALL0 + self.t

    def mono(self):
        return self.t


def transport(route="simulation", relay_id=None):
    return {"gateway_id": "gateway_01", "route": route, "hop_count": 1 if route == "relay" else 0,
            "relay_id": relay_id, "rssi_dbm": None}


def packet(ptype, node, seq, payload, boot="boot_a1", source="simulation", uptime_ms=None,
           route=None, relay_id=None):
    if route is None:
        route = "simulation" if source == "simulation" else "direct"
    return {"schema_version": "1.0", "packet_type": ptype, "node_id": node, "boot_id": boot,
            "seq": seq, "source": source, "uptime_ms": uptime_ms if uptime_ms is not None else seq * 1000,
            "payload": copy.deepcopy(payload), "transport": transport(route, relay_id)}


def status_payload(hb=10000, mode="normal", bpm=78, quality="good", motion="moving", gps="disabled"):
    return {"mode": mode, "heart_rate_bpm": bpm if quality == "good" else None,
            "heart_rate_quality": quality, "motion_state": motion, "heartbeat_interval_ms": hb,
            "sensor_status": {"heart_rate": "ok", "imu": "ok", "body_temperature": "not_implemented",
                              "gps": gps},
            "body_temperature_c": None}


def status(node="halo_01", seq=1, **kw):
    pkw = {k: kw.pop(k) for k in list(kw) if k in ("hb", "mode", "bpm", "quality", "motion", "gps")}
    return packet("soldier_status", node, seq, status_payload(**pkw), **kw)


def event(node="halo_01", seq=1, event_type="sos", n=1, event_id=None, mode="normal", **kw):
    boot = kw.get("boot", "boot_a1")
    eid = event_id or f"{node}:{boot}:{event_type}:{n}"
    return packet("event", node, seq, {"event_id": eid, "event_type": event_type, "mode": mode}, **kw)


def environment(node="env_01", seq=1, temp=24.5, hb=10000, **kw):
    payload = {"air_temperature_c": temp, "humidity_pct": 52, "light_raw": 1730,
               "heartbeat_interval_ms": hb, "sensor_status": {"dht11": "ok", "light": "ok"}}
    return packet("environment", node, seq, payload, boot=kw.pop("boot", "boot_e1"), **kw)


def gps(node="halo_01", seq=1, valid=True, lat=37.5, lon=127.0, **kw):
    payload = ({"fix_valid": True, "latitude_deg": lat, "longitude_deg": lon, "hdop": 1.1} if valid
               else {"fix_valid": False, "latitude_deg": None, "longitude_deg": None, "hdop": None})
    return packet("gps", node, seq, payload, **kw)


def anchor(node="env_01", seq=1, observed="halo_01", observed_seq=1, rssi=-58, age_ms=300, **kw):
    payload = {"anchor_id": node, "observed_node_id": observed, "observed_boot_id": "boot_a1",
               "observed_seq": observed_seq, "rssi_dbm": rssi, "observation_age_ms": age_ms}
    return packet("anchor_observation", node, seq, payload, boot=kw.pop("boot", "boot_e1"), **kw)


def new_hub(**kw):
    clock = FakeClock()
    return Hub(clock=clock, **kw), clock


def soldier(hub, soldier_id):
    return next(s for s in hub.snapshot()["soldiers"] if s["soldier_id"] == soldier_id)
