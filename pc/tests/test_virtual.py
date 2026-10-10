import unittest
from collections import Counter

from helpers import new_hub

from squadlink.virtual import SCENARIOS, Simulator, scenario_length, speed_note


def run(scenario, nodes=None, seed=1, until=None, hook=None, speed=1):
    """clock.t는 실제 시간, 가상 시각은 그 speed배(VirtualRunner와 같음)."""
    hub, clock = new_hub()
    sim = Simulator(lambda o: hub.ingest(o, "sim", "sim"), scenario=scenario, nodes=nodes, seed=seed,
                    speed=speed)
    end = (until if until is not None else scenario_length(scenario)) / speed
    while clock.t < end:
        clock.t = round(clock.t + 0.05, 2)
        sim.step(clock.t * speed)
        hub.tick()
        if hook:
            hook(hub, round(clock.t * speed, 2))
    return hub


def states(hub):
    return {s["soldier_id"]: s["connection_state"] for s in hub.snapshot()["soldiers"]}


class SimulatorTest(unittest.TestCase):
    def test_every_scenario_produces_only_valid_packets(self):
        for name in SCENARIOS:
            with self.subTest(name=name):
                t = run(name).snapshot()["totals"]
                self.assertEqual((t["invalid"], t["warnings"], t["error"]), (0, 0, 0))

    def test_demo_follows_spec_section_11(self):
        seen = {}

        def hook(hub, t):
            if t in (10.0, 16.0, 70.0, 100.0):
                seen[t] = (states(hub), [(e["event_type"], e["node_id"], e["event_state"])
                                         for e in hub.list_events()])
            if t == 16.0:  # 3단계: 지휘관 확인
                hub.mark_event("halo_01:" + hub.nodes["halo_01"].streams["simulation"].boot_id + ":sos:1", "ack")

        run("demo", hook=hook)
        st, ev = seen[10.0]  # 1 정상: 2명 연결, 6명 미배정
        self.assertEqual((st["soldier_01"], st["soldier_02"]), ("connected", "connected"))
        self.assertEqual(Counter(st.values())["unassigned"], 6)
        self.assertEqual(ev, [])
        st, ev = seen[16.0]  # 2 SOS
        self.assertEqual(ev, [("sos", "halo_01", "open")])
        st, ev = seen[70.0]  # 4 통신 두절: 병사 02 두절, 병사 01 SOS 유지
        self.assertEqual((st["soldier_01"], st["soldier_02"]), ("connected", "lost"))
        self.assertEqual(ev, [("sos", "halo_01", "acknowledged"), ("connection_lost", "halo_02", "open")])
        st, ev = seen[100.0]  # 5 복구: 병사 02 연결, SOS 사건 유지
        self.assertEqual(st["soldier_02"], "connected")
        self.assertEqual(ev[0], ("sos", "halo_01", "acknowledged"))

    def test_demo_loss_and_resume_at_speed(self):
        # 배속이어도 선언 주기를 실제 간격으로 줄이므로 두절이 보이고, 재개하면 바로 새 상태를 보낸다
        for speed in (1, 2, 3):
            seen = {}

            def hook(hub, t):
                if t in (84.0, 85.5):
                    seen[t] = states(hub)["soldier_02"]

            with self.subTest(speed=speed):
                hub = run("demo", hook=hook, speed=speed)
                self.assertEqual(seen, {84.0: "lost", 85.5: "connected"})
                self.assertEqual(hub.nodes["halo_02"].heartbeat_interval_ms, round(10000 / speed))
                self.assertIsNone(speed_note("demo", speed))
        self.assertIn("두절로 보이지 않습니다", speed_note("demo", 4))
        self.assertIsNone(speed_note("normal", 10))  # 송신 중단이 없는 시나리오

    def test_integration_scenario_covers_the_additional_checks(self):
        hub = run("all")
        snap = hub.snapshot()
        ev = Counter(e["event_type"] for e in hub.list_events(limit=1000))
        self.assertEqual(ev["sos"], 2)  # 재보고는 같은 사건, 새로 누른 SOS는 새 사건
        for t in ("impact", "prolonged_still", "heat_exposure", "connection_lost"):
            self.assertGreaterEqual(ev[t], 1, t)
        sos = [e for e in hub.list_events(limit=1000) if e["event_type"] == "sos"]
        self.assertEqual(sos[0]["report_count"], 2)
        n1 = snap["nodes"]["halo_01"]["counters"]
        self.assertGreater(n1["dup"], 0)
        self.assertGreater(n1["late"], 0)
        self.assertGreater(n1["relayed"], 0)
        self.assertEqual(n1["reboots"], 1)
        self.assertGreater(snap["nodes"]["halo_02"]["counters"]["missing"], 0)
        self.assertTrue(any(a["anchor_id"] == "gateway_01" for a in snap["anchor_observations"]))
        self.assertEqual(snap["environment_nodes"][0]["environment"]["sensor_status"]["reed"], "ok")

    def test_partial_and_unknown_nodes(self):
        hub = run("normal", nodes=["halo_02"], until=15)
        self.assertEqual(set(hub.nodes), {"halo_02"})
        with self.assertRaises(ValueError):
            Simulator(lambda o: None, nodes=["halo_09"])

    def test_gateway_anchor_does_not_see_relayed_soldier(self):
        hub = run("relay", until=39)
        obs = {(a["anchor_id"], a["observed_node_id"]): a for a in hub.snapshot()["anchor_observations"]}
        last_seq = hub.nodes["halo_01"].streams["simulation"].trackers
        latest = max(t.max_seq for t in last_seq.values())
        self.assertLess(obs[("gateway_01", "halo_01")]["observed_seq"], latest)


if __name__ == "__main__":
    unittest.main()
