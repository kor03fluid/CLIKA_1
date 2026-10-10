import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from helpers import FakeClock, anchor, environment, event, status

from squadlink.hub import Hub
from squadlink.logger import JsonlLogger
from squadlink.report import format_text, main, read_log, summarize


def stats(uptime_ms, packets, mode="fixed", anchor_on=True, reports=0, boot="boot_e1"):
    return {"type": "stats", "node_id": "env_01", "boot_id": boot, "tx_mode": mode,
            "anchor_enabled": anchor_on, "uptime_ms": uptime_ms,
            "tx": {"packets": packets, "windows": packets * 2, "est_adv_events": packets * 30,
                   "payload_bytes": packets * 21, "dropped": 0},
            "anchor": {"rx_total": 0, "rx_soldier": reports * 10, "rx_relayed_skip": 0, "rx_simulation_skip": 0,
                       "table_full_skip": 0, "reports": reports, "queue_full_skip": 0}}


def via(pkt, gateway_id):
    pkt = dict(pkt, transport=dict(pkt["transport"], gateway_id=gateway_id))
    return pkt


class ReportFromServerLogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="squadlink-report-")
        clock = FakeClock()
        log = JsonlLogger(cls.base)
        hub = Hub(logger=log, clock=clock)
        # 환경 노드: USB로 자기 송신분 1~10, 게이트웨이는 BLE로 2~9 중 5를 놓치고 3을 두 번 받음
        for seq in range(1, 11):
            clock.t += 1
            hub.ingest(via(environment(seq=seq, source="device"), "env_01"), "serial", "COM7")
        for seq in (2, 3, 3, 4, 6, 7, 8, 9):
            hub.ingest(via(environment(seq=seq, source="device"), "gateway_01"), "serial", "COM5")
        # 병사 노드: 3번 누락, 재부팅 후 새 boot
        for seq in (1, 2, 4):
            hub.ingest(status(seq=seq, source="device"), "serial", "COM5")
        hub.ingest(status(seq=1, source="device", boot="boot_b2"), "serial", "COM5")
        hub.ingest(event(seq=5, source="device"), "serial", "COM5")
        hub.ingest(event(seq=5, source="device"), "serial", "COM5")  # 반복 광고
        hub.ingest(event(seq=6, source="device"), "serial", "COM5")  # 같은 사건 재보고
        for seq, rssi in ((11, -60), (12, -70)):
            hub.ingest(via(anchor(seq=seq, source="device", rssi=rssi), "env_01"), "serial", "COM7")
        hub.ingest({"schema_version": "1.0"}, "serial", "COM5")  # 무효
        log.text(clock.wall(), "serial", "COM7", "ets Jun  8 2016 00:22:57")
        # stats: 고정 60초 → 고정에서 적응으로 전환한 구간 → 적응 600초
        for d in (stats(10000, 5), stats(70000, 17, reports=4), stats(80000, 18, mode="adaptive"),
                  stats(680000, 38, mode="adaptive", anchor_on=False)):
            hub.ingest_diag(d, "serial", "COM7")
        log.close()
        cls.rep = summarize(read_log(log.dir))  # 폴더를 주면 rx.jsonl을 읽는다

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def node(self, node_id):
        return next(n for n in self.rep["nodes"] if n["node_id"] == node_id)

    def test_results_and_period(self):
        r = self.rep["results"]
        self.assertEqual((r["invalid"], r["text"], r["diag"]), (1, 1, 4))
        self.assertGreater(self.rep["period"]["seconds"], 0)

    def test_node_counts(self):
        env = self.node("env_01")
        self.assertEqual((env["packets"], env["dup"], env["missing"], env["boots"]), (12, 8, 0, 1))
        halo = self.node("halo_01")
        self.assertEqual((halo["packets"], halo["missing"], halo["boots"]), (6, 1, 2))
        self.assertEqual(halo["types"], {"event": 2, "soldier_status": 4})
        self.assertEqual(halo["loss_pct"], round(100 / 7, 2))

    def test_ble_reception_against_usb_copy(self):
        row = next(p for p in self.rep["paths"] if p["gateway_id"] == "gateway_01" and p["node_id"] == "env_01")
        self.assertEqual((row["packets"], row["sent"], row["received_pct"]), (7, 8, 87.5))

    def test_tx_intervals_by_mode(self):
        rows = self.rep["tx_intervals"]
        self.assertEqual([(r["tx_mode"], r["anchor_enabled"], r["seconds"], r["tx_packets"]) for r in rows],
                         [("fixed", True, 60.0, 12), ("전환 포함", True, 10.0, 1),
                          ("adaptive", "전환 포함", 600.0, 20)])
        self.assertEqual((rows[0]["tx_packets_per_min"], rows[0]["anchor_reports"]), (12.0, 4))

    def test_anchor_and_events(self):
        (a,) = self.rep["anchors"]
        self.assertEqual((a["anchor_id"], a["observed_node_id"], a["reports"], a["rssi_mean"], a["rssi_sd"]),
                         ("env_01", "halo_01", 2, -65.0, 5.0))
        (e,) = self.rep["events"]
        self.assertEqual((e["event_type"], e["events"], e["reports"]), ("sos", 1, 2))

    def test_text_output(self):
        text = format_text(self.rep)
        self.assertIn("87.5", text)
        self.assertIn("전환 포함", text)


class ReportFromRawCaptureTest(unittest.TestCase):
    def write(self, lines):
        with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False, encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_invalid_raw_lines_are_skipped(self):
        bad = environment(seq=1, source="device")
        bad["source"] = None  # 정렬·집계에서 터지던 줄
        path = self.write([json.dumps(bad), json.dumps(environment(seq=2, source="device"))])
        rep = summarize(read_log(path))
        self.assertEqual(rep["results"], {"invalid": 1, "raw": 1})
        self.assertEqual([n["packets"] for n in rep["nodes"]], [1])

    def test_vtemp_mixed_sources_share_one_seq(self):
        # 환경 노드 vtemp: 한 boot의 번호열을 실측·가상이 나눠 쓴다. 출처별로 비어 보여도 누락이 아니다
        srcs = ["device", "device", "simulation", "device", "simulation", "device"]
        lines = [json.dumps(via(environment(seq=i + 1, source=s, boot="boot_1a2b"), "env_01"))
                 for i, s in enumerate(srcs) if i != 3]  # seq 4(실측)는 진짜 누락
        (env,) = summarize(read_log(self.write(lines)))["nodes"]
        self.assertEqual((env["sources"], env["packets"], env["missing"]), ({"device": 3, "simulation": 2}, 5, 1))

    def test_rate_counts_intervals_not_packets(self):
        # 10초마다 보내는 노드: 13개(120초) → 분당 6
        path = self.write([json.dumps(status(seq=s, source="device", uptime_ms=s * 10000)) for s in range(1, 14)])
        self.assertEqual(summarize(read_log(path))["nodes"][0]["per_min"], 6.0)

    def test_missing_file(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main([os.path.join(tempfile.gettempdir(), "no-such-squadlink.jsonl")]), 1)
        self.assertIn("로그를 읽을 수 없음", err.getvalue())

    def test_device_ndjson_with_diag_and_boot_text(self):
        lines = ["ets Jun  8 2016 00:22:57", "rst:0x1 (POWERON_RESET)"]
        lines += [json.dumps(via(environment(seq=s, source="device"), "env_01")) for s in (1, 2, 4)]
        lines += ["# " + json.dumps(stats(10000, 1)), "# " + json.dumps(stats(40000, 4))]
        with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False, encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.addCleanup(os.unlink, f.name)
        rep = summarize(read_log(f.name))
        (env,) = rep["nodes"]
        self.assertEqual((env["packets"], env["missing"]), (3, 1))
        self.assertEqual(env["per_min"], 60.0)  # uptime 1~4초 사이 seq 3 증가 → 분당 60
        self.assertEqual(rep["results"], {"text": 2, "raw": 3, "diag": 2})
        self.assertEqual(rep["tx_intervals"][0]["tx_packets_per_min"], 6.0)
        self.assertIsNone(rep["period"]["start"])

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main([f.name, "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["nodes"][0]["node_id"], "env_01")


if __name__ == "__main__":
    unittest.main()
