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

    def test_reused_boot_number_is_accepted_after_window(self):
        # 플래시 초기화로 boot 카운터가 1부터 다시 시작한 경우
        h = Hub()
        for i, b in enumerate((1, 2, 3)):
            h.ingest({"type": "env", "node": 49, "boot": b, "seq": 1}, "real", "p", float(i))
        # 현재 boot(3)가 막 수신된 동안에는 늦은 패킷으로 본다
        self.assertEqual(h.ingest({"type": "env", "node": 49, "boot": 1, "seq": 2}, "real", "p", 10.0),
                         "stale_boot")
        # 현재 boot가 두절 판정 시간(환경 노드 65초) 넘게 조용하면 새 부팅으로 받아들인다
        window = h.nodes[49].window_s()
        self.assertEqual(window, 65.0)
        self.assertEqual(h.ingest({"type": "env", "node": 49, "boot": 1, "seq": 3}, "real", "p", 2 + window - 1),
                         "stale_boot")
        t = 2 + window + 1
        self.assertEqual(h.ingest({"type": "env", "node": 49, "boot": 1, "seq": 1}, "real", "p", t), "ok")
        self.assertEqual(h.nodes[49].boot, 1)
        self.assertEqual(h.ingest({"type": "env", "node": 49, "boot": 1, "seq": 2}, "real", "p", t + 1), "ok")
        self.assertEqual(h.nodes[49].last_rx, t + 1)
        self.assertEqual(kinds(h).count("reboot"), 3)

    def test_malformed_fields_do_not_raise(self):
        h = Hub()
        cases = [
            {"type": "anchor", "node": 49, "boot": 1, "seq": 1, "obs": [1, None, "x"]},
            {"type": "anchor", "node": 49, "boot": 1, "seq": 2, "obs": {"soldier": 1}},
            {"type": "anchor", "node": 49, "boot": 1, "seq": 3, "obs": [{"soldier": 1, "age_ms": "400"}]},
            {"type": "env", "node": 49, "boot": 1, "seq": 4, "events": [{}, 3, "sound"]},
            {"type": "env", "node": 49, "boot": 1, "seq": 5, "events": "heat"},
            {"type": "soldier", "node": 1, "boot": 1, "seq": 1, "alert": 5, "gps": "bad"},
        ]
        for c in cases:
            self.assertEqual(h.ingest(c, "real", "p", 0), "ok", c)
        self.assertEqual(h.anchors[49][1]["seen_ts"], 0)  # 숫자가 아닌 age_ms는 0으로 본다
        self.assertEqual(kinds(h), ["env:sound", "alert:5"])
        self.assertEqual(h.totals["error"], 0)

    def test_unexpected_exception_becomes_error_result(self):
        h = Hub()
        h._soldier_events = lambda *a: (_ for _ in ()).throw(KeyError("x"))
        self.assertEqual(h.ingest(soldier(seq=1), "real", "p", 0), "error")
        self.assertEqual(h.totals["error"], 1)

    def test_snapshot_and_events_are_copies(self):
        h = Hub()
        h.ingest(soldier(seq=1, sos=True), "real", "p", 0)
        snap = h.snapshot(0)
        self.assertIsNot(snap["nodes"]["1"]["latest"], h.nodes[1].latest)
        ev = h.list_events()[0]
        ev["acked_at"] = 123
        self.assertIsNone(h.list_events()[0]["acked_at"])
        self.assertIsNot(h.mark_event(ev["id"], "ack", 1), h.events_by_id[ev["id"]])

    def test_list_events_limit(self):
        h = Hub()
        for s in range(1, 6):
            h.ingest(soldier(seq=s, sos=s % 2 == 1), "real", "p", s)
        self.assertEqual(len(h.list_events()), 3)
        self.assertEqual(h.list_events(limit=0), [])
        self.assertEqual(h.list_events(limit=-5), [])
        self.assertEqual([e["seq"] for e in h.list_events(limit=1)], [5])

    def test_late_packet_does_not_overwrite_state_or_repeat_sos(self):
        h = Hub()
        h.ingest(soldier(seq=18, sos=True), "real", "p", 0)
        h.ingest(soldier(seq=20, sos=False), "real", "p", 2)
        self.assertEqual(h.ingest(soldier(seq=19, sos=True, via="relay"), "real", "p", 3), "late")
        self.assertEqual(kinds(h), ["sos"])
        n = h.nodes[1]
        self.assertEqual(n.last_seq, 20)
        self.assertFalse(n.latest["soldier"]["sos"])
        self.assertEqual(n.via, "direct")
        self.assertEqual((n.late, n.relayed, n.last_rx), (1, 1, 3))

    def test_late_packet_reports_sos_that_was_never_seen(self):
        h = Hub()
        h.ingest(soldier(seq=18, sos=False), "real", "p", 0)
        h.ingest(soldier(seq=20, sos=False), "real", "p", 2)
        h.ingest(soldier(seq=19, sos=True), "real", "p", 3)  # 직접 경로의 19는 유실
        evs = h.list_events()
        self.assertEqual([e["kind"] for e in evs], ["sos"])
        self.assertTrue(evs[0]["detail"]["late"])

    def test_late_sos_after_release_is_a_new_press(self):
        h = Hub()
        h.ingest(soldier(seq=10, sos=True), "real", "p", 0)
        h.ingest(soldier(seq=12, sos=False), "real", "p", 1)  # 해제
        h.ingest(soldier(seq=20, sos=False), "real", "p", 2)
        h.ingest(soldier(seq=19, sos=True), "real", "p", 3)   # 해제 뒤 다시 누름(늦게 도착)
        h.ingest(soldier(seq=11, sos=True), "real", "p", 4)   # 첫 구간 안의 늦은 패킷: 알리지 않음
        self.assertEqual(kinds(h), ["sos", "sos"])

    def test_late_env_packet_still_reports_its_events(self):
        h = Hub()
        h.ingest({"type": "env", "node": 49, "boot": 1, "seq": 5, "temp": 25}, "real", "p", 0)
        self.assertEqual(h.ingest({"type": "env", "node": 49, "boot": 1, "seq": 4, "temp": 20,
                                   "events": ["shock"]}, "real", "p", 1), "late")
        self.assertEqual(kinds(h), ["env:shock"])
        self.assertEqual(h.nodes[49].latest["env"]["temp"], 25)

    def test_real_source_wins_over_virtual_for_same_node(self):
        h = Hub()
        h.ingest(soldier(boot=100, seq=1), "real", "p", 0)
        self.assertEqual(h.ingest(soldier(boot=200, seq=1, virtual=True), "virtual", "sim", 1), "shadowed")
        self.assertEqual(h.ingest(soldier(boot=100, seq=2), "real", "p", 2), "ok")
        self.assertEqual(kinds(h), [])
        self.assertEqual(h.nodes[1].shadowed, 1)
        # 실측이 두절 판정 시간 넘게 조용하면 가상이 이어받는다
        t = 2 + h.nodes[1].timeout_s() + 1
        h.tick(t)
        self.assertEqual(h.ingest(soldier(boot=200, seq=2, virtual=True), "virtual", "sim", t), "ok")
        self.assertEqual((h.nodes[1].source, h.nodes[1].boot), ("virtual", 200))
        # 실측이 돌아오면 바로 실측으로 바뀐다
        self.assertEqual(h.ingest(soldier(boot=100, seq=3), "real", "p", t + 1), "ok")
        self.assertEqual(h.ingest(soldier(boot=200, seq=3, virtual=True), "virtual", "sim", t + 2), "shadowed")
        self.assertEqual(kinds(h), ["comm_lost", "source_change", "source_change"])
        self.assertNotIn("reboot", kinds(h))

    def test_anchor_only_node_is_not_marked_lost(self):
        h = Hub()
        h.ingest({"type": "anchor", "node": 0x20, "boot": 1, "seq": 1, "obs": []}, "real", "p", 0)
        self.assertIsNone(h.nodes[0x20].timeout_s())
        h.tick(1000)
        self.assertEqual(kinds(h), [])
        self.assertIsNone(h.snapshot(1000)["nodes"]["32"]["timeout_s"])

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
        self.assertIsNone(parse_line('{"type":"env","temp":NaN}'))
        self.assertIsNone(parse_line('{"type":"env","temp":Infinity}'))

    def test_iter_log_records_reads_server_log_and_plain_lines(self):
        lines = [
            '{"rx_ts":1.0,"source":"real","port":"p","result":"text","text":"ets Jun  8"}',
            '{"rx_ts":2.0,"source":"real","port":"p","result":"ok","obj":{"type":"env","node":49,"boot":1,"seq":1}}',
            '{"rx_ts":3.0,"source":"real","port":"p","result":"invalid","obj":{"type":"x"}}',
            '{"rx_ts":3.5,"source":"real","port":"p","result":"late","obj":{"type":"env","node":49,"boot":1,"seq":0}}',
            '{"rx_ts":3.6,"source":"virtual","port":"sim","result":"shadowed","obj":{"type":"env","node":49,"boot":2,"seq":1}}',
            '{"type":"soldier","node":1,"boot":1,"seq":1}',
            "not json",
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write("\n".join(lines))
        try:
            recs = list(iter_log_records(f.name))
        finally:
            os.unlink(f.name)
        self.assertEqual([ts for ts, _ in recs], [2.0, 3.5, None])
        self.assertEqual([o["type"] for _, o in recs], ["env", "env", "soldier"])


if __name__ == "__main__":
    unittest.main()
