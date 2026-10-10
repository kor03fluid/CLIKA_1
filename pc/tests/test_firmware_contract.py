"""환경 노드 펌웨어의 USB 출력과 공통 데이터 규격 v1이 맞는지 확인한다.

펌웨어의 실제 JSON 출력 코드(firmware/env_node/json_out.cpp)를 PC용으로 빌드해 실행하고,
나온 줄을 서버 검사기(schema.validate)로 확인한다. 가상 노드만으로 시험하면 펌웨어와 서버가
서로 다른 형식을 써도 드러나지 않기 때문이다. C++ 컴파일러가 없으면 빌드 시험은 건너뛴다.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

from helpers import environment, new_hub

from squadlink.ingest import classify_line
from squadlink.schema import validate

HERE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "firmware", "env_node"))
HOST_DIR = os.path.join(HERE, "firmware_host")
CXX = shutil.which("g++") or shutil.which("clang++")


def read(name):
    with open(os.path.join(FW_DIR, name), encoding="utf-8") as f:
        return f.read()


@unittest.skipIf(CXX is None, "C++ 컴파일러 없음")
class FirmwareJsonOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-fw-")
        exe = os.path.join(cls.tmp, "host_json")
        subprocess.run([CXX, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", HOST_DIR, "-I", FW_DIR,
                        os.path.join(FW_DIR, "json_out.cpp"), os.path.join(HOST_DIR, "host_main.cpp"),
                        "-o", exe], check=True, capture_output=True, text=True)
        out = subprocess.run([exe], check=True, capture_output=True, text=True).stdout
        cls.lines = out.splitlines()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def packets(self):
        out = []
        for line in self.lines:
            kind, obj = classify_line(line)
            self.assertEqual(kind, "data", line)
            out.append(obj)
        return out

    def test_every_line_is_valid_v1(self):
        pkts = self.packets()
        self.assertEqual(len(pkts), 5)
        for p in pkts:
            pkt, errors, warnings = validate(p)
            self.assertEqual((errors, warnings), ([], []), p)

    def test_field_values(self):
        e1, e2, e3, ev, a = self.packets()
        self.assertEqual((e1["node_id"], e1["boot_id"], e1["source"]), ("env_01", "boot_1a2b", "device"))
        self.assertEqual(e1["payload"]["air_temperature_c"], 24.5)
        self.assertEqual(e1["payload"]["heartbeat_interval_ms"], 30000)
        self.assertEqual((e1["payload"]["flame_detected"], e1["payload"]["reed_closed"]), (True, True))
        self.assertEqual(set(e1["payload"]["sensor_status"]), {"dht11", "light", "sound", "flame", "shock", "reed"})
        # 측정 불가는 null, 쓰지 않는 추가 센서는 필드와 sensor_status 키를 모두 뺀다
        self.assertEqual(e2["source"], "simulation")
        self.assertEqual([e2["payload"][k] for k in ("air_temperature_c", "humidity_pct", "light_raw")],
                         [None, None, None])
        self.assertEqual(e2["payload"]["sensor_status"], {"dht11": "unavailable", "light": "unavailable"})
        self.assertNotIn("sound_detected", e2["payload"])
        self.assertEqual((e3["payload"]["air_temperature_c"], e3["payload"]["sound_detected"]), (-5.5, None))
        self.assertEqual((e3["node_id"], e3["seq"], e3["uptime_ms"]), ("env_02", 65535, 4294967295))
        self.assertEqual(ev["payload"], {"event_id": "env_01:boot_1a2b:heat_exposure:1",
                                         "event_type": "heat_exposure", "mode": "normal"})
        self.assertEqual(a["payload"], {"anchor_id": "env_01", "observed_node_id": "halo_01",
                                        "observed_boot_id": "boot_00a1", "observed_seq": 1,
                                        "rssi_dbm": -58, "observation_age_ms": 300})
        self.assertEqual(a["transport"], {"gateway_id": "env_01", "route": "direct", "hop_count": 0,
                                          "relay_id": None, "rssi_dbm": None})

    def test_server_accepts_the_stream(self):
        hub, clock = new_hub()
        results = [hub.ingest(p, "serial", "COM7") for p in self.packets()]
        self.assertEqual(results.count("invalid"), 0)
        snap = hub.snapshot()
        env = snap["environment_nodes"][0]
        self.assertEqual(env["node_id"], "env_01")
        self.assertEqual([e["event_type"] for e in hub.list_events()], ["heat_exposure"])
        self.assertEqual(snap["anchor_observations"][0]["observed_node_id"], "halo_01")


@unittest.skipIf(CXX is None, "C++ 컴파일러 없음")
class FirmwareNodeHeaderTest(unittest.TestCase):
    """node.cpp: seq는 출처·종류를 통틀어 부팅 내 하나이고, 65535에 이르면 새 boot_id로 넘어간다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-fw-")
        exe = os.path.join(cls.tmp, "host_node")
        # -I HOST_DIR를 앞에 두어 Preferences.h·esp_random.h 대체가 쓰이게 한다
        subprocess.run([CXX, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", HOST_DIR, "-I", FW_DIR,
                        os.path.join(FW_DIR, "node.cpp"), os.path.join(HOST_DIR, "host_node.cpp"),
                        "-o", exe], check=True, capture_output=True, text=True)
        out = subprocess.run([exe], check=True, capture_output=True, text=True).stdout
        cls.rows = [(src, boot, int(seq)) for src, boot, seq, _ in (l.split() for l in out.splitlines())]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_seq_shared_across_sources(self):
        # 규격 4장: 같은 부팅에서 seq를 재사용하지 않는다(실측·가상이 섞여도 한 번호열)
        mixed = self.rows[:7]
        self.assertEqual({b for _, b, _ in mixed}, {"1a2b"})
        self.assertEqual([q for _, _, q in mixed], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([s for s, _, _ in mixed].count("simulation"), 3)

    def test_wrap_starts_new_boot(self):
        self.assertEqual(self.rows[7:], [("device", "1a2c", 1), ("simulation", "1a2c", 2),
                                         ("device", "1a2d", 1)])

    def test_server_sees_no_missing_while_mixed(self):
        # 실측·가상이 섞인 스트림(같은 포트, vtemp 시험)을 서버에 넣어도 어느 쪽에도 누락이 없어야 한다
        hub, clock = new_hub()
        for src, boot, seq in self.rows[:7]:
            clock.t += 1
            self.assertEqual(hub.ingest(environment(seq=seq, boot="boot_" + boot, source=src),
                                        "serial", "COM7"), "ok")
        node = hub.snapshot()["nodes"]["env_01"]
        self.assertEqual(set(node["streams"]), {"device", "simulation"})
        self.assertEqual(node["counters"]["missing"], 0)  # 출처별로는 비어 보이지만 노드·부팅 단위로는 누락 없음


@unittest.skipIf(CXX is None, "C++ 컴파일러 없음")
class FirmwareTxQueueTest(unittest.TestCase):
    """ble_tx.cpp: 사건·감지 패킷은 쌓인 일반 패킷 앞에 나가고, 광고 시작 실패는 다시 시도한다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-fw-")
        exe = os.path.join(cls.tmp, "host_tx")
        subprocess.run([CXX, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", HOST_DIR, "-I", FW_DIR,
                        os.path.join(FW_DIR, "ble_tx.cpp"), os.path.join(HOST_DIR, "host_tx.cpp"),
                        "-o", exe], check=True, capture_output=True, text=True)
        out = subprocess.run([exe], check=True, capture_output=True, text=True).stdout
        cls.out = dict(line.split(" ", 1) for line in out.splitlines())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_urgent_goes_ahead_of_queued_normal_packets(self):
        self.assertEqual(self.out["active"], "AUUUBC")  # 광고 중인 A는 끊지 않음
        self.assertEqual(self.out["idle"], "VVWX")     # 사건끼리는 들어온 순서

    def test_full_queue_drops(self):
        self.assertEqual((self.out["full"], self.out["drop"]), ("abcdef", "g"))
        self.assertEqual(self.out["stats"].split()[-1], "dropped=1")

    def test_adv_start_failure_is_retried_not_counted(self):
        self.assertEqual(self.out["fail"], "F")
        self.assertEqual(self.out["stats"].split()[:2], ["adv_fail=2", "windows=1"])


class FirmwareSourceTest(unittest.TestCase):
    def test_only_json_out_prints_data_lines(self):
        # 데이터(JSON)는 json_out.cpp만 낸다. 다른 곳의 출력은 "# " 진단 줄이어야 한다(규격 2장).
        pattern = re.compile(r'Serial\.print(?:f|ln)?\("\{')
        for name in os.listdir(FW_DIR):
            if name.endswith((".cpp", ".ino", ".h")) and name != "json_out.cpp":
                self.assertIsNone(pattern.search(read(name)), name)

    def test_readme_examples_are_valid_v1(self):
        lines = [l for l in read("README.md").splitlines() if l.startswith('{"schema_version"')]
        self.assertGreaterEqual(len(lines), 3)
        for line in lines:
            kind, obj = classify_line(line)
            self.assertEqual(kind, "data", line)
            self.assertEqual(validate(obj)[1:], ([], []), line)


if __name__ == "__main__":
    unittest.main()
