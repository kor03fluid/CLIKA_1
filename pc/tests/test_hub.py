import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from squadlink.hub import Hub, SeqTracker  # noqa: E402
import tempfile  # noqa: E402

from squadlink.ingest import iter_log_records, parse_line  # noqa: E402


def soldier(node=1, boot=10, seq=1, **kw):
    return dict({"type": "soldier", "node": node, "boot": boot, "seq": seq}, **kw)


def kinds(hub):
    return [e["kind"] for e in hub.list_events()]


class SeqTrackerTest(unittest.TestCase):
    def test_dup_and_gap(self):
        t = SeqTracker()
        self.assertTrue(t.add(1))
        self.assertFalse(t.add(1))
        self.assertTrue(t.add(4))
        self.assertEqual(t.missing_total, 2)
        self.assertTrue(t.add(3))  # 늦게 도착
        self.assertEqual(t.missing_total, 1)

    def test_wraparound(self):
        t = SeqTracker()
        t.add(0xFFFE)
        t.add(0xFFFF)
        t.add(1)  # 0 누락
        self.assertEqual(t.missing_total, 1)

    def test_resync_on_large_jump(self):
        t = SeqTracker()
        t.add(1)
        t.add(5000)
        self.assertEqual(t.missing_total, 0)


class HubTest(unittest.TestCase):
    def test_dedupe_by_node_boot_seq(self):
        h = Hub()
        self.assertEqual(h.ingest(soldier(seq=1), "real", "p", 0), "ok")
        self.assertEqual(h.ingest(soldier(seq=1), "real", "p", 0.1), "dup")
        self.assertEqual(h.ingest(soldier(node=2, seq=1), "real", "p", 0.2), "ok")
        self.assertEqual(h.totals["dup"], 1)
        self.assertEqual(h.nodes[1].dup, 1)

    def test_reboot_and_late_old_boot_packet(self):
        h = Hub()
        h.ingest(soldier(boot=10, seq=5), "real", "p", 0)
        self.assertEqual(h.ingest(soldier(boot=11, seq=1), "real", "p", 1), "ok")
        self.assertIn("reboot", kinds(h))
        # 이전 부팅의 늦은 패킷은 현재 상태를 바꾸지 않는다
        self.assertEqual(h.ingest(soldier(boot=10, seq=6), "real", "p", 2), "stale_boot")
        self.assertEqual(h.nodes[1].boot, 11)
        self.assertEqual(h.ingest(soldier(boot=10, seq=5), "real", "p", 3), "dup")

    def test_invalid_and_meta(self):
        h = Hub()
        self.assertEqual(h.ingest({"type": "soldier", "node": 1}, "real", "p", 0), "invalid")
        self.assertEqual(h.ingest([1, 2], "real", "p", 0), "invalid")
        self.assertEqual(h.ingest({"type": "stats", "node": 49, "tx": {}}, "real", "p", 0), "meta")
        self.assertIn(49, h.device_stats)

    def test_comm_lost_and_restored(self):
        h = Hub()
        h.ingest(soldier(seq=1), "real", "p", 0)
        timeout = h.nodes[1].timeout_s()
        h.tick(timeout - 1)
        self.assertTrue(h.nodes[1].online)
        h.tick(timeout + 1)
        self.assertFalse(h.nodes[1].online)
        h.ingest(soldier(seq=2), "real", "p", timeout + 2)
        self.assertTrue(h.nodes[1].online)
        self.assertEqual(kinds(h), ["comm_lost", "comm_restored"])

    def test_fixed_tx_mode_shortens_timeout(self):
        h = Hub()
        h.ingest({"type": "env", "node": 49, "boot": 1, "seq": 1, "tx_mode": "fixed"}, "real", "p", 0)
        self.assertEqual(h.nodes[49].timeout_s(), 15.0)

    def test_soldier_events_on_rising_edge(self):
        h = Hub()
        h.ingest(soldier(seq=1, sos=False, alert="none"), "real", "p", 0)
        h.ingest(soldier(seq=2, sos=True, alert="check"), "real", "p", 1)
        h.ingest(soldier(seq=3, sos=True, alert="check"), "real", "p", 2)
        h.ingest(soldier(seq=4, sos=True, alert="priority"), "real", "p", 3)
        self.assertEqual(kinds(h), ["sos", "alert:check", "alert:priority"])
        self.assertEqual(h.list_events()[0]["level"], "critical")

    def test_relayed_counted(self):
        h = Hub()
        h.ingest(soldier(seq=1, via="relay"), "real", "p", 0)
        self.assertEqual(h.nodes[1].via, "relay")
        self.assertEqual(h.nodes[1].relayed, 1)

    def test_env_events_and_anchor(self):
        h = Hub()
        h.ingest({"type": "env", "node": 49, "boot": 1, "seq": 1, "events": ["heat", "sound"]},
                 "real", "p", 0)
        self.assertEqual(kinds(h), ["env:heat", "env:sound"])
        h.ingest({"type": "anchor", "node": 49, "boot": 1, "seq": 2,
                  "obs": [{"soldier": 1, "rssi": -60, "rssi_avg": -62, "n": 4, "age_ms": 500}]},
                 "real", "p", 10)
        obs = h.anchors[49][1]
        self.assertAlmostEqual(obs["seen_ts"], 9.5)
        self.assertEqual(h.nodes[49].kind, "env")
        # 더 오래된 관측은 덮어쓰지 않는다
        h.ingest({"type": "anchor", "node": 49, "boot": 1, "seq": 3,
                  "obs": [{"soldier": 1, "rssi": -90, "age_ms": 5000}]}, "real", "p", 11)
        self.assertEqual(h.anchors[49][1]["rssi"], -60)

    def test_ack_and_resolve_are_separate(self):
        h = Hub()
        h.ingest(soldier(seq=1, sos=True), "real", "p", 0)
        eid = h.list_events()[0]["id"]
        ev = h.mark_event(eid, "ack", 5, by="cmd")
        self.assertEqual(ev["acked_at"], 5)
        self.assertIsNone(ev["resolved_at"])
        ev = h.mark_event(eid, "resolve", 9)
        self.assertEqual(ev["resolved_at"], 9)
        self.assertIsNone(h.mark_event(999, "ack", 1))

    def test_virtual_label(self):
        h = Hub()
        h.ingest(soldier(seq=1, sos=True), "virtual", "sim", 0)
        self.assertTrue(h.nodes[1].virtual)
        self.assertTrue(h.list_events()[0]["virtual"])

    def test_parse_line(self):
        self.assertEqual(parse_line('{"type":"env"}\r\n'), {"type": "env"})
        self.assertIsNone(parse_line("ets Jun  8 2016 00:22:57"))
        self.assertIsNone(parse_line("{broken"))

    def test_iter_log_records_reads_server_log_and_plain_lines(self):
        lines = [
            '{"rx_ts":1.0,"source":"real","port":"p","result":"text","text":"ets Jun  8"}',
            '{"rx_ts":2.0,"source":"real","port":"p","result":"ok","obj":{"type":"env","node":49,"boot":1,"seq":1}}',
            '{"rx_ts":3.0,"source":"real","port":"p","result":"invalid","obj":{"type":"x"}}',
            '{"type":"soldier","node":1,"boot":1,"seq":1}',
            "not json",
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write("\n".join(lines))
        try:
            recs = list(iter_log_records(f.name))
        finally:
            os.unlink(f.name)
        self.assertEqual([ts for ts, _ in recs], [2.0, None])
        self.assertEqual([o["type"] for _, o in recs], ["env", "soldier"])


if __name__ == "__main__":
    unittest.main()
