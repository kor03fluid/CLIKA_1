import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from squadlink.hub import Hub  # noqa: E402
from squadlink.virtual import SCENARIOS, Simulator, scenario_length  # noqa: E402


def run(scenario, nodes=None, seed=1, extra_s=0):
    hub = Hub()
    clock = {"t": 0.0}
    sim = Simulator(lambda o: hub.ingest(o, "virtual", "sim", clock["t"]), scenario=scenario,
                    nodes=nodes, seed=seed)
    t = 0.0
    while t <= scenario_length(scenario) + extra_s:
        clock["t"] = t
        sim.step(t)
        hub.tick(t)
        t += 0.1
    return hub


def kinds(hub):
    return {e["kind"] for e in hub.list_events()}


class SimulatorTest(unittest.TestCase):
    def test_all_scenarios_run(self):
        for name in SCENARIOS:
            with self.subTest(name=name):
                hub = run(name)
                self.assertEqual(hub.totals["invalid"], 0)
                self.assertTrue(all(n.virtual for n in hub.nodes.values()))

    def test_integration_scenario_covers_pre_arrival_checklist(self):
        hub = run("all")
        k = kinds(hub)
        for expected in ("sos", "alert:check", "alert:priority", "comm_lost", "comm_restored",
                         "reboot", "gps_lost", "env:heat", "hr_contact"):
            self.assertIn(expected, k)
        self.assertGreater(hub.totals["dup"], 0)
        self.assertGreater(hub.nodes[2].missing_total(), 0)
        self.assertGreater(hub.nodes[1].relayed, 0)
        self.assertEqual(set(hub.nodes), {1, 2, 0x31, 0x20})
        self.assertIn(1, hub.anchors[0x31])

    def test_partial_virtual_nodes(self):
        hub = run("sos", nodes=[2])
        self.assertEqual(set(hub.nodes), {2})
        self.assertIn("sos", kinds(hub))

    def test_relay_hides_soldier_from_gateway_anchor(self):
        hub = Hub()
        sim = Simulator(lambda o: hub.ingest(o, "virtual", "sim", 0), scenario="relay", seed=3)
        t = 0.0
        while t < 39:
            sim.step(t)
            t += 0.1
        gw = hub.anchors[0x20]
        # 중계 시작(10초) 이후 게이트웨이 앵커의 병사 1 관측은 갱신되지 않는다
        self.assertLess(gw[1]["last_seq"], hub.nodes[1].last_seq)


if __name__ == "__main__":
    unittest.main()
