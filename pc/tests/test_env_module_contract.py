"""환경 모듈 펌웨어(firmware/env_module, 기획서 5장)가 공통 데이터 규격 v1·부록 A·역할 분담을 지키는지 확인한다.

- 공통 판단 코드(env_logic·anchor_logic)는 Arduino 없이 PC에서 그대로 빌드해 판단 규칙을 시험한다(기획서 10장 분리).
- 가상 센서 보드 10분 시나리오를 펌웨어 소스로 돌린 USB 줄을 규격 v1 검사기, C 시험 서버, 팀장 서버 입력 처리에 넣는다.
- C 시험 서버가 검증·중복 제거를 통과한 가상 데이터만 팀장 서버로 넘기는지, 팀장 서버를 임시 포트로 띄워 끝까지 본다.
C++ 컴파일러나 Node.js가 없으면 그 시험만 건너뛴다.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.request

from squadlink.forward import LeadForwarder
from squadlink.hub import Hub
from squadlink.ingest import classify_line
from squadlink.schema import validate

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
FW = os.path.join(ROOT, "firmware", "env_module")
OLD_FW = os.path.join(ROOT, "firmware", "env_node")
HOST = os.path.join(HERE, "firmware_host")
HOST_M = os.path.join(HERE, "firmware_host_module")
LEAD = os.path.join(ROOT, "squad-link")
CXX = shutil.which("g++") or shutil.which("clang++")
NODE = shutil.which("node")

SOURCE_MISMATCH = "현재 입력 모드와 source가 일치하지 않습니다"
LEAD_NOT_YET = {"event": "미등록 병사 노드", "anchor_observation": "지원하지 않는 패킷 유형"}  # 팀장 서버 확장 전


def read(name, base=FW):
    with open(os.path.join(base, name), encoding="utf-8") as f:
        return f.read()


def build(tmp, name, sources):
    exe = os.path.join(tmp, name)
    # 모듈용 대체(Preferences 키-값)를 먼저, 공통 대체(Arduino·BLE·DHT)를 다음에 찾는다
    subprocess.run([CXX, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", HOST_M, "-I", HOST, "-I", FW]
                   + sources + ["-o", exe], check=True, capture_output=True, text=True)
    return exe


def run(exe, *args):
    return subprocess.run([exe, *args], check=True, capture_output=True, text=True).stdout


def kv(text):
    out = {}
    for line in text.splitlines():
        k, _, v = line.partition(" ")
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = v
    return out


def fw(*names):
    return [os.path.join(FW, n) for n in names]


class EnvModuleSourceTest(unittest.TestCase):
    """소스 규칙: 공통 무선 규격, 입출력과 판단의 분리, 데이터 줄과 진단 줄의 분리."""

    def test_packet_layout_is_the_shared_appendix_a(self):
        # 무선 바이트 배치는 B의 규격(부록 A)이고 A·C가 같은 패킷을 쓴다: 환경 노드 두 펌웨어가 같은 packet.h
        self.assertEqual(read("packet.h"), read("packet.h", OLD_FW))

    def test_common_logic_has_no_board_io(self):
        banned = re.compile(r"#include\s*<(Arduino|BLE\w*|esp_\w*|Preferences|DHT|RBD_\w*)\.h>|Serial\.|digitalRead|"
                            r"analogRead|attachInterrupt|millis\(|delay\(")
        for name in ("env_logic.h", "env_logic.cpp", "anchor_logic.h", "anchor_logic.cpp"):
            self.assertIsNone(banned.search(read(name)), name)

    def test_only_json_out_prints_data_lines(self):
        # 규격 2장: 데이터 스트림에는 규격 JSON만. 다른 출력은 "# "로 시작하는 진단 줄
        pattern = re.compile(r'Serial\.print(?:f|ln)?\("\{')
        for name in os.listdir(FW):
            if name.endswith((".cpp", ".ino", ".h")) and name != "json_out.cpp":
                self.assertIsNone(pattern.search(read(name)), name)

    def test_diag_off_by_default_and_virtual_by_default(self):
        cfg = read("config.h")
        self.assertRegex(cfg, r"#define DEFAULT_DIAG 0\b")
        self.assertRegex(cfg, r"#define DEFAULT_VIRTUAL\s+1\b")  # 센서 검증 전에는 가상 데이터(출처 simulation)
        self.assertRegex(cfg, r"#define DEFAULT_USE_MASK 0x00\b")  # 추가 실제 센서는 검증 후 켠다
        ino = read("env_module.ino")
        self.assertIn("if (settings().diag) printBoot();", ino)
        self.assertIn("if (!reply && !settings().diag) return;", ino)

    def test_readme_examples_are_valid_v1(self):
        lines = [l for l in read("README.md").splitlines() if l.startswith('{"schema_version"')]
        self.assertEqual(len(lines), 4)
        for line in lines:
            kind, obj = classify_line(line)
            self.assertEqual(kind, "data", line)
            self.assertEqual(validate(obj)[1:], ([], []), line)

    def test_logical_counts_are_not_named_radio_events(self):
        # 규격 12장: 논리적 송신 호출 수를 실제 무선 광고 이벤트 수로 이름 붙이지 않는다
        for name in os.listdir(FW):
            if name.endswith((".cpp", ".ino", ".h")):
                self.assertNotIn("est_adv", read(name), name)


@unittest.skipIf(CXX is None, "C++ 컴파일러 없음")
class EnvModuleLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-mod-")
        exe = build(cls.tmp, "logic", fw("env_logic.cpp", "anchor_logic.cpp")
                    + [os.path.join(HOST_M, "host_module_logic.cpp")])
        cls.v = kv(run(exe))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_virtual_board_scenario(self):
        v = self.v
        self.assertEqual((v["vb_sound_at"], v["vb_sounds"], v["vb_shock_at"], v["vb_flame_pulse_at"]),
                         (30000, 1, 60000, 150000))
        self.assertEqual((v["vb_reed_open_from"], v["vb_reed_open_to"]), (90000, 100000))
        self.assertEqual((v["vb_flame_from"], v["vb_flame_to"]), (150000, 160000))
        self.assertEqual((v["vb_dht_fail_from"], v["vb_dht_fail_to"]), (480000, 500000))
        self.assertAlmostEqual(v["vb_temp_max"], 37.0, places=3)  # 열 노출 주의(35°C)를 넘는다
        self.assertLess(v["vb_light_min"], 400)                  # 어두워짐
        self.assertEqual(v["vb_sound_second_cycle"], 1)          # 10분 반복
        self.assertEqual((v["vb_inject_shock"], v["vb_inject_reed_closed"]), (1, 0))
        self.assertEqual(v["vb_phase_285s"], "heat_rise")

    def test_dht_needs_three_failures_and_null_both(self):
        v = self.v
        self.assertEqual((v["j_start_dht_ok"], v["j_real_dht_ok"], v["j_real_sim"]), (0, 1, 0))
        self.assertEqual((v["j_fail2_dht_ok"], v["j_fail2_temp"]), (1, 25))
        self.assertEqual((v["j_fail3_dht_ok"], v["j_fail3_temp_nan"]), (0, 1))
        self.assertEqual(v["b_half_both_null"], 1)  # dht11 ok ⇔ 온습도 모두 숫자

    def test_vtemp_and_heat_exposure(self):
        v = self.v
        self.assertEqual((v["j_vtemp_dht_ok"], v["j_vtemp_hum"], v["j_vtemp_sim"]), (1, 50, 1))
        self.assertEqual((v["j_vtemp_onset"], v["j_vtemp_onset_sim"], v["j_vtemp_off_heat"]), (1, 1, 0))
        self.assertEqual((v["j_real36_onset"], v["j_real36_onset_sim"]), (1, 0))
        self.assertEqual((v["j_real36_vtemp_onset"], v["j_real36_vtemp_onset_sim"]), (1, 1))
        self.assertEqual((v["j_real36_back_heat"], v["j_real36_back_onset"], v["j_real34_heat"]), (1, 0, 0))

    def test_detections_only_for_used_sensors(self):
        v = self.v
        self.assertEqual((v["j_unused_det"], v["j_used_det"]), (0, 1))
        self.assertEqual((v["j_reed_new_det"], v["j_reed_bounce_det"], v["j_reed_change_det"]), (0, 0, 8))
        self.assertEqual((v["j_switch_dht_ok"], v["j_switch_sim"], v["j_switch_det"]), (0, 1, 0))

    def test_report_policy(self):
        v = self.v
        self.assertEqual((v["p_first_before_3s"], v["p_first_after_3s"]), (0, 1))
        self.assertEqual((v["p_fixed_interval"], v["p_fixed_4s"], v["p_fixed_5s"]), (5000, 0, 1))
        self.assertEqual((v["p_adaptive_interval"], v["p_adaptive_idle_10s"]), (30000, 0))
        self.assertEqual((v["p_adaptive_urgent"], v["p_adaptive_urgent_gap"]), (2, 0))
        self.assertEqual((v["p_adaptive_change_2s"], v["p_adaptive_change_4s"], v["p_adaptive_heartbeat"]), (0, 1, 1))
        self.assertEqual(v["p_heat_interval"], 10000)

    def test_board_side_spec_checks(self):
        v = self.v
        for k in ("c_env_ok", "c_env_all_ok", "c_env_half_ok", "c_event_ok", "c_anchor_ok"):
            self.assertEqual(v[k], "OK", k)
        for k in ("c_env_hum101", "c_env_hum_only_null", "c_env_light5000", "c_env_hb0", "c_env_relayed_flag",
                  "c_env_soldier_id", "c_env_other_env", "c_env_omit_mismatch", "c_env_seq0", "c_event_sos",
                  "c_event_covert", "c_event_no0", "c_anchor_rssi_pos", "c_anchor_obs_env"):
            self.assertNotEqual(v[k], "OK", k)
        self.assertEqual((v["b_temp_c10"], v["b_hum_clamped"], v["b_heartbeat_s"], v["b_omit_all"]), (245, 100, 30, 1))

    def test_wiring_check(self):
        v = self.v
        self.assertEqual((v["k_virtual_ok"], v["k_high"], v["k_low"], v["k_virtual_ignores_dht"]), (0, 1, 1, 0))
        self.assertEqual((v["k_real_dht"], v["k_real_noisy_held"], v["k_real_unused_ignored"]), (1, 2, 0))

    def test_anchor_classify(self):
        v = self.v
        # AdvVerdict: 0 NOT_OURS, 1 NOT_SOLDIER, 2 RELAYED, 3 SIM_SKIPPED, 4 ACCEPT, 5 ACCEPT_SIM
        self.assertEqual((v["a_real"], v["a_real_seq"]), (4, 9))
        self.assertEqual((v["a_relayed"], v["a_relayed_test"], v["a_relayed_sim_test"]), (2, 2, 2))  # 중계 제외 유지
        self.assertEqual((v["a_sim_off"], v["a_sim_test"]), (3, 5))  # 가상은 시험 모드에서만
        self.assertEqual((v["a_env_node"], v["a_soldier_anchor_type"], v["a_soldier_event"]), (1, 1, 4))
        self.assertEqual((v["a_old_version"], v["a_other_company"], v["a_short"]), (0, 0, 0))

    def test_anchor_report_order(self):
        v = self.v
        self.assertEqual((v["t_size"], v["t_due_new"], v["t_due_rank0"], v["t_due_after_report"]), (3, 3, 0, 0))
        self.assertEqual((v["t_change_n"], v["t_change_rank"], v["t_change_id"], v["t_change_rssi_last"]),
                         (1, 1, 1, -40))
        self.assertEqual((v["t_periodic_n"], v["t_periodic_rank"], v["t_stale"]), (2, 2, 0))
        self.assertEqual((v["t_after_clear_sim"], v["t_fill_age_capped"], v["t_fill_rssi"]), (2, 65535, -41))


@unittest.skipIf(CXX is None, "C++ 컴파일러 없음")
class EnvModuleIdentTest(unittest.TestCase):
    """같은 펌웨어로 예비 WROOM을 env_02로: NVS 설정, boot_id·seq 규칙(규격 4장)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-mod-")
        exe = build(cls.tmp, "ident", fw("settings.cpp", "ident.cpp", "json_out.cpp")
                    + [os.path.join(HOST_M, "host_module_ident.cpp")])
        cls.text = run(exe)
        cls.v = kv(cls.text)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_defaults(self):
        v = self.v
        self.assertEqual((v["first_node"], v["first_virtual"], v["first_use"], v["first_anchor"], v["first_diag"]),
                         (0x31, 1, 0, 1, 0))

    def test_seq_one_counter_and_wrap(self):
        rows = [l.split()[1:] for l in self.text.splitlines() if re.match(r"seq\d ", l)]
        self.assertEqual([int(r[0]) for r in rows], [1, 2, 3, 4])  # 종류·출처를 통틀어 하나
        self.assertEqual({r[1] for r in rows}, {str(0x1a2b)})
        self.assertEqual((self.v["wrap_seq"], self.v["wrap_boot"]), (1, 0x1a2c))

    def test_spare_wroom_id(self):
        v = self.v
        self.assertEqual((v["parse_env_02"], v["parse_env_15"]), (0x32, 0x3F))
        self.assertEqual((v["parse_env_16"], v["parse_env_00"], v["parse_env_2"], v["parse_halo_01"]), (0, 0, 0, 0))
        self.assertEqual((v["set_halo"], v["set_env_02"]), (0, 1))
        self.assertEqual((v["running_after_set"], v["saved_after_set"]), (0x31, 0x32))  # 부팅 중에는 그대로
        self.assertEqual((v["reboot_node"], v["reboot_boot_next"], v["reboot_seq"], v["reboot_header_node"]),
                         (0x32, 1, 1, 0x32))
        self.assertEqual((v["reboot_use"], v["reboot_virtual"], v["reboot_diag"]), (9, 0, 1))
        self.assertEqual(v["bad_nvs_node"], 0x31)
        self.assertEqual((v["factory_node"], v["factory_virtual"], v["factory_use"], v["factory_boot_kept"]),
                         (0x31, 1, 0, 1))


@unittest.skipIf(CXX is None, "C++ 컴파일러 없음")
class EnvModuleJsonAndTxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-mod-")
        cls.json_lines = run(build(cls.tmp, "json", fw("json_out.cpp") + [os.path.join(HOST, "host_main.cpp")]))
        out = run(build(cls.tmp, "tx", fw("ble_tx.cpp") + [os.path.join(HOST, "host_tx.cpp")]))
        cls.tx = dict(line.split(" ", 1) for line in out.splitlines())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_json_lines_are_valid_v1(self):
        pkts = []
        for line in self.json_lines.splitlines():
            kind, obj = classify_line(line)
            self.assertEqual(kind, "data", line)
            self.assertEqual(validate(obj)[1:], ([], []), line)
            pkts.append(obj)
        self.assertEqual(len(pkts), 7)
        # USB 직결: gateway_id는 그 패킷을 낸 노드 자신(env_02 보드면 env_02)
        self.assertEqual([p["transport"]["gateway_id"] for p in pkts], [p["node_id"] for p in pkts])
        for p in pkts:
            sim = p["source"] == "simulation"
            self.assertEqual(p["transport"]["route"], "simulation" if sim else "direct")

    def test_tx_queue_order_and_failures(self):
        self.assertEqual((self.tx["active"], self.tx["idle"]), ("AUUUBC", "VVWX"))
        self.assertEqual((self.tx["full"], self.tx["drop"]), ("abcdef", "g"))
        self.assertEqual(self.tx["fail"], "F")
        self.assertEqual(self.tx["stats"].split(), ["adv_fail=2", "windows=1", "dropped=1"])


def _pipeline(tmp, *args):
    exe = os.path.join(tmp, "pipeline")
    if not os.path.exists(exe):
        build(tmp, "pipeline", fw("env_logic.cpp", "anchor_logic.cpp", "settings.cpp", "ident.cpp", "out.cpp",
                                  "json_out.cpp", "ble_tx.cpp") + [os.path.join(HOST_M, "host_module_pipeline.cpp")])
    lines = run(exe, *args).splitlines()
    return [json.loads(l) for l in lines], lines


@unittest.skipIf(CXX is None, "C++ 컴파일러 없음")
class EnvModuleVirtualDataTest(unittest.TestCase):
    """가상 센서 보드 → 공통 판단 → 보드 검사 → USB JSON(11분). 가상 데이터 값이 규격대로 나가는지."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-mod-")
        cls.pkts, cls.lines = _pipeline(cls.tmp)
        cls.fixed, _ = _pipeline(cls.tmp, "fixed")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def of(self, ptype, pkts=None):
        return [p for p in (pkts or self.pkts) if p["packet_type"] == ptype]

    def test_every_line_is_valid_v1_and_marked_virtual(self):
        for line in self.lines:
            kind, obj = classify_line(line)
            self.assertEqual(kind, "data", line)
            self.assertEqual(validate(obj)[1:], ([], []), line)
        for p in self.pkts:
            self.assertEqual((p["node_id"], p["source"]), ("env_01", "simulation"))
            self.assertEqual(p["transport"], {"gateway_id": "env_01", "route": "simulation", "hop_count": 0,
                                              "relay_id": None, "rssi_dbm": None})

    def test_seq_is_one_contiguous_counter(self):
        self.assertEqual({p["boot_id"] for p in self.pkts}, {"boot_1a2b"})
        self.assertEqual([p["seq"] for p in self.pkts], list(range(1, len(self.pkts) + 1)))

    def test_all_six_sensors_and_cases_appear(self):
        env = [p["payload"] for p in self.of("environment")]
        self.assertTrue(all(set(e["sensor_status"]) == {"dht11", "light", "sound", "flame", "shock", "reed"}
                            for e in env))
        for field in ("sound_detected", "flame_detected", "shock_detected"):
            self.assertTrue(any(e[field] is True for e in env), field)
        self.assertTrue(any(e["reed_closed"] is False for e in env))
        nulls = [e for e in env if e["air_temperature_c"] is None]
        self.assertTrue(nulls and all(e["humidity_pct"] is None and e["sensor_status"]["dht11"] == "unavailable"
                                      for e in nulls))  # DHT11 읽기 실패 → 측정 불가 null
        self.assertTrue(any(e["light_raw"] < 400 for e in env))
        self.assertGreaterEqual(max(e["air_temperature_c"] or 0 for e in env), 35.0)
        self.assertEqual({e["heartbeat_interval_ms"] for e in env}, {10000, 30000})
        self.assertEqual({e["heartbeat_interval_ms"] for e in (p["payload"] for p in self.of("environment", self.fixed))},
                         {5000})

    def test_heat_exposure_events(self):
        ev = self.of("event")
        self.assertEqual([e["payload"]["event_id"] for e in ev],
                         ["env_01:boot_1a2b:heat_exposure:1", "env_01:boot_1a2b:heat_exposure:2"])
        self.assertTrue(280000 <= ev[0]["uptime_ms"] <= 290000)  # 시나리오 약 285초에 35°C
        self.assertEqual(ev[1]["uptime_ms"], 620000)              # vtemp 38
        self.assertTrue(all(e["payload"]["mode"] == "normal" for e in ev))

    def test_lead_handoff_files_match_firmware_output(self):
        # 팀장에게 보낸 줄(docs/lead_handoff_env_module)이 지금 펌웨어 출력과 같은지
        base = os.path.join(ROOT, "docs", "lead_handoff_env_module")
        with open(os.path.join(base, "virtual_11min.ndjson"), encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), self.lines)
        with open(os.path.join(base, "samples_env_module.ndjson"), encoding="utf-8") as f:
            samples = f.read().splitlines()
        self.assertEqual([json.loads(l)["packet_type"] for l in samples], ["environment", "event", "anchor_observation"])
        self.assertTrue(all(l in self.lines for l in samples))
        readme = read("README.md", base)
        self.assertTrue(all(l in readme for l in samples))

    def test_adaptive_sends_less_than_fixed(self):
        self.assertLess(len(self.of("environment")), len(self.of("environment", self.fixed)) / 2)

    def test_c_server_accepts_without_missing(self):
        hub = Hub()
        results = [hub.ingest(p, "serial", "COM9") for p in self.pkts]
        self.assertEqual(set(results), {"ok"})
        snap = hub.snapshot()
        self.assertEqual(snap["nodes"]["env_01"]["counters"]["missing"], 0)
        self.assertEqual([(e["event_type"], e["source"]) for e in hub.list_events()],
                         [("heat_exposure", "simulation")] * 2)
        self.assertEqual({(a["observed_node_id"], a["source"]) for a in snap["anchor_observations"]},
                         {("halo_01", "simulation"), ("halo_02", "simulation")})

    @unittest.skipIf(NODE is None or not os.path.isdir(LEAD), "Node.js·squad-link 필요")
    def test_lead_server_ingest(self):
        path = os.path.join(self.tmp, "virtual.ndjson")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")
        out = subprocess.run([NODE, os.path.join(HERE, "lead_ingest_check.mjs"), LEAD, path],
                             check=True, capture_output=True, text=True).stdout
        for r in map(json.loads, out.splitlines()):
            if r["mode"] == "device":
                self.assertIn(SOURCE_MISMATCH, r["error"] or "", r)
            elif r["packet_type"] == "environment":
                self.assertTrue(r["accepted"], r)  # 가상 환경 데이터는 팀장 서버가 모두 받는다
            else:
                self.assertIn(LEAD_NOT_YET[r["packet_type"]], r["error"] or "", r)


@unittest.skipIf(CXX is None or NODE is None or not os.path.isdir(LEAD), "C++ 컴파일러·Node.js·squad-link 필요")
class ForwardToLeadServerTest(unittest.TestCase):
    """환경 보드 USB 줄 → C 시험 서버(검증·중복 제거) → 통과한 가상 데이터만 → 팀장 서버(임시 포트, 수정 없음)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-mod-")
        cls.pkts, _ = _pipeline(cls.tmp)
        cls.lead = subprocess.Popen([NODE, os.path.join(HERE, "lead_server_run.mjs"), LEAD, "simulation"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        line = cls.lead.stdout.readline()
        cls.port = int(line.split()[1])

    @classmethod
    def tearDownClass(cls):
        cls.lead.stdin.close()
        try:
            cls.lead.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.lead.kill()
            cls.lead.wait()
        cls.lead.stdout.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_validated_virtual_data_reaches_lead_server(self):
        base = f"http://127.0.0.1:{self.port}"
        fwd = LeadForwarder(base + "/api/ingest").start()
        hub = Hub()
        hub.ingest_hooks.append(fwd.offer)
        for p in self.pkts:
            hub.ingest(p, "serial", "COM9")
        hub.ingest(self.pkts[5], "serial", "COM9")          # USB·게이트웨이 사본 중복 → 넘기지 않음
        bad = dict(self.pkts[0], seq=99999, payload=dict(self.pkts[0]["payload"], humidity_pct=150))
        hub.ingest(bad, "serial", "COM9")                    # 규격 위반 → 넘기지 않음
        hub.ingest(dict(self.pkts[0], seq=99998, source="device",
                        transport=dict(self.pkts[0]["transport"], route="direct")), "serial", "COM9")  # 실측 → 안 넘김
        self.assertTrue(fwd.drain(10))
        fwd.stop()
        st = fwd.status()
        n_env = sum(p["packet_type"] == "environment" for p in self.pkts)
        self.assertEqual(st["counts"].get("accepted"), n_env)
        self.assertEqual(st["counts"].get("rejected"), len(self.pkts) - n_env)  # 사건·앵커: 팀장 서버 확장 전
        self.assertEqual(st["counts"].get("failed", 0), 0)
        self.assertEqual(st["skipped"], {"result:dup": 1, "result:invalid": 1, "source": 1})
        for reason in st["rejected"]:
            self.assertTrue(any(k in reason for k in LEAD_NOT_YET.values()), reason)
        with urllib.request.urlopen(base + "/api/state", timeout=5) as r:
            state = json.load(r)
        env = [t for t in state["telemetry"] if t["node_id"] == "env_01"]
        last = [p for p in self.pkts if p["packet_type"] == "environment"][-1]
        self.assertEqual(len(env), 1)
        self.assertEqual((env[0]["source"], env[0]["payload"]["air_temperature_c"]),
                         ("simulation", last["payload"]["air_temperature_c"]))


if __name__ == "__main__":
    unittest.main()
