import unittest

from helpers import anchor, environment, event, gps, new_hub, soldier, status

from squadlink.hub import SeqTracker


def kinds(hub):
    return [(e["event_type"], e["node_id"]) for e in hub.list_events(limit=1000)]


class SeqTrackerTest(unittest.TestCase):
    def test_new_late_dup_and_gap(self):
        t = SeqTracker()
        self.assertEqual(t.add(1), "new")
        self.assertFalse(t.add(1))
        self.assertEqual(t.add(4), "new")
        self.assertEqual(t.missing_total, 2)
        self.assertEqual(t.add(3), "late")
        self.assertEqual(t.missing_total, 1)

    def test_large_jump_is_not_counted_as_missing(self):
        t = SeqTracker()
        t.add(1)
        t.add(5000)
        self.assertEqual(t.missing_total, 0)


class DedupeAndOrderTest(unittest.TestCase):
    def test_duplicate_packet_is_dropped(self):
        h, c = new_hub()
        self.assertEqual(h.ingest(status(seq=1), "serial", "p"), "ok")
        self.assertEqual(h.ingest(status(seq=1), "serial", "p"), "dup")
        self.assertEqual(h.nodes["halo_01"].c["dup"], 1)

    def test_duplicate_does_not_refresh_last_seen(self):
        h, c = new_hub()
        h.ingest(status(seq=1), "serial", "p")
        first = soldier(h, "soldier_01")["last_seen_at"]
        c.t = 5
        h.ingest(status(seq=1), "serial", "p")
        self.assertEqual(soldier(h, "soldier_01")["last_seen_at"], first)

    def test_source_is_part_of_the_dedupe_key(self):
        h, c = new_hub()
        h.ingest(status(seq=1, source="simulation"), "sim", "sim")
        # 실제 장치의 같은 node_id·boot_id·seq는 다른 원본이다(실측이 표시 출처를 이어받음)
        self.assertEqual(h.ingest(status(seq=1, source="device"), "serial", "COM5"), "ok")
        self.assertEqual(soldier(h, "soldier_01")["source"], "device")

    def test_late_packet_does_not_overwrite_latest_status(self):
        h, c = new_hub()
        h.ingest(status(seq=1, bpm=70), "serial", "p")
        h.ingest(status(seq=3, bpm=90), "serial", "p")
        self.assertEqual(h.ingest(status(seq=2, bpm=60, route="relay", relay_id="relay_01"), "serial", "p"), "late")
        s = soldier(h, "soldier_01")
        self.assertEqual((s["status"]["heart_rate_bpm"], s["status_seq"], s["route"]), (90, 3, "simulation"))
        self.assertEqual(h.nodes["halo_01"].c["late"], 1)

    def test_late_event_is_still_recorded(self):
        h, c = new_hub()
        h.ingest(status(seq=1), "serial", "p")
        h.ingest(status(seq=3), "serial", "p")
        self.assertEqual(h.ingest(event(seq=2), "serial", "p"), "late")
        ev = h.list_events()
        self.assertEqual([(e["event_type"], e["late"]) for e in ev], [("sos", True)])

    def test_previous_boot_packet_does_not_overwrite_state(self):
        h, c = new_hub()
        h.ingest(status(seq=5, boot="boot_a1", bpm=70), "serial", "p")
        h.ingest(status(seq=1, boot="boot_a2", bpm=80), "serial", "p")  # 재부팅
        self.assertEqual(h.ingest(status(seq=6, boot="boot_a1", bpm=99), "serial", "p"), "stale_boot")
        s = soldier(h, "soldier_01")
        self.assertEqual((s["status_boot_id"], s["status"]["heart_rate_bpm"]), ("boot_a2", 80))
        # 이전 boot의 사건은 기록한다
        self.assertEqual(h.ingest(event(seq=7, boot="boot_a1"), "serial", "p"), "stale_boot")
        self.assertEqual(kinds(h), [("sos", "halo_01")])

    def test_reused_boot_id_is_accepted_after_the_node_went_quiet(self):
        h, c = new_hub()
        h.ingest(status(seq=1, boot="boot_x"), "serial", "p")
        c.t = 1
        h.ingest(status(seq=1, boot="boot_y"), "serial", "p")
        c.t = 2
        self.assertEqual(h.ingest(status(seq=2, boot="boot_x"), "serial", "p"), "stale_boot")
        c.t = 1 + 32 + 1  # 현재 boot가 두절 기준(32초)보다 오래 조용함
        self.assertEqual(h.ingest(status(seq=1, boot="boot_x"), "serial", "p"), "ok")
        self.assertEqual(soldier(h, "soldier_01")["status_boot_id"], "boot_x")


class ConnectionStateTest(unittest.TestCase):
    def test_roster_defaults(self):
        h, c = new_hub()
        states = {s["soldier_id"]: s["connection_state"] for s in h.snapshot()["soldiers"]}
        self.assertEqual(states["soldier_01"], "waiting")
        self.assertEqual(states["soldier_02"], "waiting")
        self.assertEqual({states[f"soldier_{i:02d}"] for i in range(3, 9)}, {"unassigned"})

    def test_waiting_until_first_status_and_never_lost_without_interval(self):
        h, c = new_hub()
        h.ingest(event(seq=1), "serial", "p")  # 상태 패킷 전 사건만
        c.t = 1000
        h.tick()
        self.assertEqual(soldier(h, "soldier_01")["connection_state"], "waiting")
        self.assertNotIn(("connection_lost", "halo_01"), kinds(h))

    def test_timeout_uses_declared_heartbeat(self):
        h, c = new_hub()
        h.ingest(status(seq=1, hb=10000), "serial", "p")
        s = soldier(h, "soldier_01")
        self.assertEqual((s["connection_state"], s["timeout_ms"], s["data_stale"]), ("connected", 32000, False))
        c.t = 31.9
        h.tick()
        self.assertEqual(soldier(h, "soldier_01")["connection_state"], "connected")
        c.t = 32.1
        h.tick()
        h.tick()  # 반복 검사로 사건을 더 만들지 않는다
        s = soldier(h, "soldier_01")
        self.assertEqual((s["connection_state"], s["data_stale"]), ("lost", True))
        self.assertEqual(kinds(h), [("connection_lost", "halo_01")])

    def test_reconnect_keeps_sos_and_new_loss_makes_new_event(self):
        h, c = new_hub()
        h.ingest(status(seq=1, hb=5000), "serial", "p")
        h.ingest(event(seq=2), "serial", "p")
        c.t = 18
        h.tick()
        c.t = 19
        h.ingest(status(seq=3, hb=5000), "serial", "p")
        self.assertEqual(soldier(h, "soldier_01")["connection_state"], "connected")
        sos = h.find_events("halo_01:boot_a1:sos:1")[0]
        self.assertEqual(sos["event_state"], "open")  # 재연결이 SOS를 해결하지 않는다
        c.t = 40
        h.tick()
        lost = [e for e in h.list_events() if e["event_type"] == "connection_lost"]
        self.assertEqual([e["event_id"] for e in lost],
                         ["server:halo_01:connection_lost:1", "server:halo_01:connection_lost:2"])
        self.assertEqual(lost[0]["soldier_id"], "soldier_01")

    def test_anchor_observation_does_not_refresh_observed_soldier(self):
        h, c = new_hub()
        h.ingest(status(seq=1), "serial", "p")
        c.t = 30
        h.ingest(anchor(seq=1, observed="halo_01"), "serial", "p")
        c.t = 33
        h.tick()
        self.assertEqual(soldier(h, "soldier_01")["connection_state"], "lost")

    def test_unassigned_node_creates_no_loss_event(self):
        h, c = new_hub()
        h.ingest(status(node="halo_07", seq=1), "serial", "p")
        c.t = 100
        h.tick()
        self.assertEqual(kinds(h), [])
        self.assertEqual(soldier(h, "soldier_07")["connection_state"], "unassigned")

    def test_environment_node(self):
        h, c = new_hub()
        h.set_env_location("env_01", "북쪽 출입구")
        h.ingest(environment(seq=1, hb=10000), "serial", "p")
        env = h.snapshot()["environment_nodes"][0]
        self.assertEqual((env["node_id"], env["location_name"], env["connection_state"]),
                         ("env_01", "북쪽 출입구", "connected"))
        self.assertEqual(env["environment"]["air_temperature_c"], 24.5)
        c.t = 33
        h.tick()
        self.assertEqual(kinds(h), [("connection_lost", "env_01")])


class EventTest(unittest.TestCase):
    def test_same_event_id_is_one_event_and_keeps_its_state(self):
        h, c = new_hub()
        h.ingest(event(seq=1), "serial", "p")
        ev, err = h.mark_event("halo_01:boot_a1:sos:1", "ack", by="cmd")
        self.assertEqual((ev["event_state"], ev["acknowledged_by"], err), ("acknowledged", "cmd", None))
        h.ingest(event(seq=2), "serial", "p")  # 같은 사건, 새 패킷
        h.ingest(event(seq=2), "serial", "p")  # 같은 패킷 중복
        evs = h.list_events()
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0]["report_count"], evs[0]["event_state"]), (2, "acknowledged"))
        h.ingest(event(seq=3, n=2), "serial", "p")  # 새로 누른 SOS
        self.assertEqual([e["event_state"] for e in h.list_events()], ["acknowledged", "open"])

    def test_ack_resolve_rules(self):
        h, c = new_hub()
        h.ingest(event(seq=1), "serial", "p")
        eid = "halo_01:boot_a1:sos:1"
        c.t = 5
        ev, _ = h.mark_event(eid, "resolve")  # 확인 없이 종료 가능
        self.assertEqual((ev["event_state"], ev["acknowledged_at"]), ("resolved", None))
        self.assertTrue(ev["resolved_at"].endswith("Z"))
        ev, _ = h.mark_event(eid, "ack")  # 종료 후 확인은 바뀌지 않음
        self.assertEqual(ev["event_state"], "resolved")
        self.assertEqual(h.mark_event("nope", "ack"), (None, "not found"))
        self.assertEqual(h.mark_event(eid, "delete")[1], "action은 ack 또는 resolve")

    def test_same_event_id_from_two_sources_needs_source(self):
        h, c = new_hub()
        h.ingest(event(seq=1, source="simulation"), "sim", "sim")
        h.ingest(event(seq=1, source="device"), "serial", "COM5")
        self.assertEqual(len(h.list_events()), 2)
        self.assertIsNotNone(h.mark_event("halo_01:boot_a1:sos:1", "ack")[1])
        ev, err = h.mark_event("halo_01:boot_a1:sos:1", "ack", source="device")
        self.assertEqual((ev["source"], err), ("device", None))

    def test_shadowed_stream_events_are_still_recorded(self):
        h, c = new_hub()
        h.ingest(status(seq=1, source="device"), "serial", "COM5")
        self.assertEqual(h.ingest(status(seq=1, source="simulation"), "sim", "sim"), "shadowed")
        self.assertEqual(h.ingest(event(seq=2, source="simulation"), "sim", "sim"), "shadowed")
        self.assertEqual([e["source"] for e in h.list_events()], ["simulation"])
        self.assertEqual(soldier(h, "soldier_01")["source"], "device")

    def test_shadowed_repeats_are_deduplicated(self):
        # 반복 광고(같은 seq)는 가려진 출처에서도 한 번만 보고로 센다
        h, c = new_hub()
        h.ingest(status(seq=1, source="device"), "serial", "COM5")
        for _ in range(3):
            self.assertEqual(h.ingest(event(seq=2, source="simulation"), "sim", "sim"), "shadowed")
        (ev,) = h.list_events()
        self.assertEqual((ev["source"], ev["report_count"]), ("simulation", 1))
        h.ingest(event(seq=3, source="simulation"), "sim", "sim")  # 다른 패킷의 같은 사건은 재보고
        self.assertEqual(h.list_events()[0]["report_count"], 2)

    def test_list_events_limit(self):
        h, c = new_hub()
        for i in range(1, 4):
            h.ingest(event(seq=i, n=i), "serial", "p")
        self.assertEqual(h.list_events(limit=0), [])
        self.assertEqual([e["n"] for e in h.list_events(limit=1)], [3])
        self.assertEqual([e["n"] for e in h.list_events(since_n=2)], [3])
        h.list_events()[0]["event_state"] = "x"  # 복사본
        self.assertEqual(h.list_events()[0]["event_state"], "open")


class SourceTest(unittest.TestCase):
    def test_device_preempts_simulation_and_simulation_waits(self):
        h, c = new_hub()
        h.ingest(status(seq=1, source="simulation"), "sim", "sim")
        h.ingest(status(seq=1, source="device", boot="boot_d"), "serial", "COM5")
        self.assertEqual(h.ingest(status(seq=2, source="simulation"), "sim", "sim"), "shadowed")
        c.t = 33  # 실측이 두절 기준만큼 조용하면 가상이 이어받는다
        self.assertEqual(h.ingest(status(seq=3, source="simulation"), "sim", "sim"), "ok")
        self.assertEqual(soldier(h, "soldier_01")["source"], "simulation")

    def test_shadowed_stream_has_no_false_missing_after_takeover(self):
        # 가려진 동안의 번호도 추적하므로, 가상이 이어받을 때 그 사이 번호가 누락으로 잡히지 않는다
        h, c = new_hub()
        h.ingest(status(seq=1, source="simulation"), "sim", "sim")
        h.ingest(status(seq=1, source="device", boot="boot_d"), "serial", "COM5")
        for seq in range(2, 6):
            c.t += 10
            h.ingest(status(seq=seq, source="device", boot="boot_d"), "serial", "COM5")
            self.assertEqual(h.ingest(status(seq=seq, source="simulation"), "sim", "sim"), "shadowed")
        c.t += 33  # 실측 두절 → 가상이 이어받는다
        self.assertEqual(h.ingest(status(seq=6, source="simulation"), "sim", "sim"), "ok")
        self.assertEqual(h.snapshot()["nodes"]["halo_01"]["streams"]["simulation"]["missing"], 0)

    def test_touch_bumps_version(self):
        h, c = new_hub()
        v = h.version
        h.touch()
        self.assertEqual(h.version, v + 1)

    def test_anchor_observation_from_other_source_does_not_switch(self):
        h, c = new_hub()
        h.ingest(environment(seq=1, source="device"), "serial", "COM7")
        h.ingest(environment(seq=2, source="simulation", temp=40.0), "serial", "COM7")  # vtemp 시험
        self.assertEqual(h.ingest(anchor(seq=3, source="device", boot="boot_e1"), "serial", "COM7"), "ok")
        self.assertEqual(h.ingest(environment(seq=4, source="simulation", temp=40.0), "serial", "COM7"), "ok")
        env = h.snapshot()["environment_nodes"][0]
        self.assertEqual((env["source"], env["connection_state"]), ("simulation", "connected"))
        self.assertEqual(h.nodes["env_01"].c["source_changes"], 1)
        self.assertEqual(len(h.snapshot()["anchor_observations"]), 1)

    def test_same_port_switch_follows_the_device(self):
        # 환경 노드가 vtemp 시험으로 source를 simulation으로 바꾼 경우
        h, c = new_hub()
        h.ingest(environment(seq=1, source="device", temp=24.0), "serial", "COM7")
        self.assertEqual(h.ingest(environment(seq=2, source="simulation", temp=40.0), "serial", "COM7"), "ok")
        env = h.snapshot()["environment_nodes"][0]
        self.assertEqual((env["source"], env["environment"]["air_temperature_c"]), ("simulation", 40.0))


class OtherTest(unittest.TestCase):
    def test_invalid_packets_are_reported(self):
        h, c = new_hub()
        bad = status()
        del bad["transport"]
        self.assertEqual(h.ingest(bad, "serial", "COM5"), "invalid")
        self.assertEqual(h.ingest([1], "serial", "COM5"), "invalid")
        snap = h.snapshot()
        self.assertEqual(snap["totals"]["invalid"], 2)
        self.assertEqual(snap["recent_invalid"][0]["node_id"], "halo_01")
        self.assertTrue(any("transport" in e for e in snap["recent_invalid"][0]["errors"]))

    def test_unexpected_exception_becomes_error(self):
        h, c = new_hub()
        h._record_event = lambda *a, **k: (_ for _ in ()).throw(KeyError("x"))
        self.assertEqual(h.ingest(event(seq=1), "serial", "p"), "error")
        self.assertEqual(h.totals["error"], 1)

    def test_gps_location(self):
        h, c = new_hub()
        h.ingest(status(seq=1, gps="ok"), "serial", "p")
        h.ingest(gps(seq=2, lat=37.51, lon=127.02), "serial", "p")
        loc = soldier(h, "soldier_01")["location"]
        self.assertEqual((loc["fix_valid"], loc["latitude_deg"], loc["location_stale"]), (True, 37.51, False))
        c.t = 5
        h.ingest(gps(seq=3, valid=False), "serial", "p")
        loc = soldier(h, "soldier_01")["location"]
        # 과거 유효 위치는 시각과 함께 남고 오래된 위치로 표시
        self.assertEqual((loc["fix_valid"], loc["latitude_deg"], loc["location_stale"]), (False, 37.51, True))
        self.assertIsNotNone(loc["location_updated_at"])

    def test_anchor_keeps_newest_observation(self):
        h, c = new_hub()
        h.ingest(anchor(seq=1, rssi=-60, age_ms=100), "serial", "p")
        h.ingest(anchor(seq=2, rssi=-90, age_ms=5000), "serial", "p")  # 더 오래된 관측
        a = h.snapshot()["anchor_observations"]
        self.assertEqual([(x["anchor_id"], x["observed_node_id"], x["rssi_dbm"]) for x in a],
                         [("env_01", "halo_01", -60)])

    def test_roster_assignment(self):
        h, c = new_hub()
        self.assertEqual(h.set_assignment("soldier_03", "halo_03")["assigned_node_id"], "halo_03")
        with self.assertRaises(ValueError):
            h.set_assignment("soldier_04", "halo_03")  # 한 노드는 한 분대원에게만
        with self.assertRaises(ValueError):
            h.set_assignment("soldier_99", "halo_09")
        h.ingest(status(node="halo_03", seq=1), "serial", "p")
        self.assertEqual(soldier(h, "soldier_03")["connection_state"], "connected")
        h.set_assignment("soldier_03", None)
        self.assertEqual(soldier(h, "soldier_03")["connection_state"], "unassigned")

    def test_roster_config_is_validated(self):
        from squadlink.hub import Hub
        with self.assertRaises(ValueError):
            Hub(roster=[{"soldier_id": "s1", "assigned_node_id": "halo_01"},
                        {"soldier_id": "s2", "assigned_node_id": "halo_01"}])
        with self.assertRaises(ValueError):
            Hub(roster=[{"assigned_node_id": "halo_01"}])

    def test_snapshot_shape(self):
        h, c = new_hub()
        h.ingest(status(seq=1), "serial", "p")
        snap = h.snapshot()
        self.assertEqual(snap["schema_version"], "1.0")
        self.assertTrue(snap["server_time"].endswith("Z"))
        self.assertEqual(len(snap["soldiers"]), 8)
        self.assertIsNone(snap["soldiers"][0]["estimated_zone_id"])
        self.assertIn("halo_01", snap["nodes"])


if __name__ == "__main__":
    unittest.main()
