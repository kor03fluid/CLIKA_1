import json
import os
import re
import unittest

from helpers import environment, gps, packet, status, status_payload  # noqa: F401

from squadlink.schema import timeout_ms, validate

SPEC = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "data_spec_v1.md")


def spec_examples():
    with open(SPEC, encoding="utf-8") as f:
        return [json.loads(b) for b in re.findall(r"```json\n(.*?)```", f.read(), re.S)]


class SpecExamplesTest(unittest.TestCase):
    def test_every_example_in_the_spec_is_valid(self):
        examples = spec_examples()
        self.assertEqual(sorted(e["packet_type"] for e in examples),
                         sorted(["soldier_status", "event", "environment", "gps", "anchor_observation"]))
        for ex in examples:
            pkt, errors, warnings = validate(ex)
            self.assertEqual((errors, warnings), ([], []), ex["packet_type"])
            self.assertEqual(pkt, ex)


class ValidateTest(unittest.TestCase):
    def errors(self, obj):
        return validate(obj)[1]

    def test_common_header(self):
        base = status()
        self.assertEqual(self.errors(base), [])
        for key in ("schema_version", "packet_type", "node_id", "boot_id", "seq", "source",
                    "uptime_ms", "payload", "transport"):
            bad = dict(base)
            del bad[key]
            self.assertTrue(self.errors(bad), key)
        for key, value in (("schema_version", "2.0"), ("packet_type", "status"), ("source", "real"),
                           ("seq", -1), ("seq", True), ("seq", 1.5), ("node_id", ""), ("uptime_ms", "10")):
            self.assertTrue(self.errors(dict(base, **{key: value})), (key, value))

    def test_transport(self):
        base = status()
        for key in ("gateway_id", "route", "hop_count", "relay_id", "rssi_dbm"):
            t = dict(base["transport"])
            del t[key]
            self.assertTrue(self.errors(dict(base, transport=t)), key)
        t = dict(base["transport"], route="wifi")
        self.assertTrue(self.errors(dict(base, transport=t)))
        t = dict(base["transport"], route="relay", hop_count=0, relay_id=None)
        pkt, errors, warnings = validate(dict(base, transport=t))
        self.assertEqual(errors, [])
        self.assertTrue(warnings)

    def test_enums_are_lowercase_only(self):
        p = status_payload()
        p["mode"] = "Normal"
        self.assertTrue(self.errors(packet("soldier_status", "halo_01", 1, p)))
        p = status_payload()
        p["sensor_status"]["imu"] = "OK"
        self.assertTrue(self.errors(packet("soldier_status", "halo_01", 1, p)))

    def test_null_vs_missing(self):
        p = status_payload()
        del p["body_temperature_c"]  # 필수: 측정 불가여도 null로 있어야 함
        self.assertTrue(self.errors(packet("soldier_status", "halo_01", 1, p)))
        p = status_payload()
        p["heartbeat_interval_ms"] = 0
        self.assertTrue(self.errors(packet("soldier_status", "halo_01", 1, p)))

    def test_heart_rate_requires_good_quality(self):
        p = status_payload()
        p["heart_rate_quality"] = "poor"  # bpm은 78 그대로
        pkt, errors, warnings = validate(packet("soldier_status", "halo_01", 1, p))
        self.assertEqual(errors, [])
        self.assertIsNone(pkt["payload"]["heart_rate_bpm"])
        self.assertTrue(warnings)
        self.assertEqual(p["heart_rate_bpm"], 78)  # 원본은 바꾸지 않는다

    def test_device_body_temperature_must_be_null_when_not_implemented(self):
        p = status_payload()
        p["body_temperature_c"] = 36.5
        pkt, _, warnings = validate(packet("soldier_status", "halo_01", 1, p, source="device"))
        self.assertIsNone(pkt["payload"]["body_temperature_c"])
        self.assertTrue(warnings)
        pkt, _, warnings = validate(packet("soldier_status", "halo_01", 1, p, source="simulation"))
        self.assertEqual(pkt["payload"]["body_temperature_c"], 36.5)  # 가상 체온은 시험용으로 허용

    def test_environment(self):
        self.assertEqual(self.errors(environment()), [])
        for key, value in (("humidity_pct", 120), ("light_raw", -1), ("light_raw", 1.5),
                           ("air_temperature_c", "24")):
            e = environment()
            e["payload"][key] = value
            self.assertTrue(self.errors(e), key)
        e = environment()
        e["payload"]["sound_detected"] = False  # sensor_status.sound 없음
        pkt, errors, warnings = validate(e)
        self.assertEqual(errors, [])
        self.assertTrue(warnings)
        e["payload"]["sound_detected"] = "no"
        self.assertTrue(self.errors(e))

    def test_gps(self):
        self.assertEqual(self.errors(gps()), [])
        g = gps(valid=True, lat=None)
        self.assertTrue(self.errors(g))
        g = gps(lat=91.0)
        self.assertTrue(self.errors(g))
        g = gps(valid=False)
        g["payload"]["latitude_deg"] = 37.0  # 무효 위치에 좌표
        pkt, errors, warnings = validate(g)
        self.assertEqual(errors, [])
        self.assertIsNone(pkt["payload"]["latitude_deg"])
        self.assertTrue(warnings)

    def test_not_an_object(self):
        self.assertTrue(self.errors([1, 2]))
        self.assertTrue(self.errors(dict(status(), payload=[])))

    def test_timeout_formula(self):
        self.assertEqual(timeout_ms(5000), 17000)
        self.assertEqual(timeout_ms(10000), 32000)
        self.assertEqual(timeout_ms(30000), 92000)
        self.assertEqual(timeout_ms(1000), 15000)


if __name__ == "__main__":
    unittest.main()
