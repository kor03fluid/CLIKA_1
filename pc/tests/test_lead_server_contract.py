"""환경 노드 펌웨어 출력이 팀장 공식 관제 서버(squad-link)의 입력 처리를 통과하는지 확인한다.

펌웨어 JSON 출력 코드(json_out.cpp)를 PC에서 빌드해 실측·가상 예시 줄을 만들고, 팀장 서버의 core/state.mjs
ingest에 그대로 넣는다. 팀장 서버 코드는 고치지 않는다(서버 수정은 팀장 담당). C++ 컴파일러나 Node.js가 없으면 건너뛴다.

아직 팀장 서버가 받지 않는 것(환경 노드 사건, anchor_observation)은 알려진 거절 사유로 허용한다. 서버가 확장되면
그 줄은 받아지고, 이 시험은 그대로 통과한다. 그 밖의 거절(형식·transport·센서 값 검사)은 펌웨어 출력 문제로 본다.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
FW_DIR = os.path.join(ROOT, "firmware", "env_node")
HOST_DIR = os.path.join(HERE, "firmware_host")
LEAD_DIR = os.path.join(ROOT, "squad-link")
CXX = shutil.which("g++") or shutil.which("clang++")
NODE = shutil.which("node")

SOURCE_MISMATCH = "현재 입력 모드와 source가 일치하지 않습니다"  # 팀장 서버는 input.mode와 같은 출처만 받는다(의도)
NOT_YET = {  # 팀장 서버 확장 전까지의 거절
    "event": "미등록 병사 노드",
    "anchor_observation": "지원하지 않는 패킷 유형",
}


@unittest.skipIf(CXX is None or NODE is None or not os.path.isdir(LEAD_DIR), "C++ 컴파일러·Node.js·squad-link 필요")
class LeadServerContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="squadlink-lead-")
        exe = os.path.join(cls.tmp, "host_samples")
        subprocess.run([CXX, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", HOST_DIR, "-I", FW_DIR,
                        os.path.join(FW_DIR, "json_out.cpp"), os.path.join(HOST_DIR, "host_samples.cpp"),
                        "-o", exe], check=True, capture_output=True, text=True)
        cls.lines = subprocess.run([exe], check=True, capture_output=True, text=True).stdout
        cls.ndjson = os.path.join(cls.tmp, "samples.ndjson")
        with open(cls.ndjson, "w", encoding="utf-8") as f:
            f.write(cls.lines)
        out = subprocess.run([NODE, os.path.join(HERE, "lead_ingest_check.mjs"), LEAD_DIR, cls.ndjson],
                             check=True, capture_output=True, text=True).stdout
        cls.results = [json.loads(l) for l in out.splitlines()]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_environment_is_accepted_in_matching_mode(self):
        env = [r for r in self.results if r["packet_type"] == "environment" and r["mode"] == r["source"]]
        self.assertEqual(len(env), 2)  # 실측(device 모드), 가상(simulation 모드)
        self.assertTrue(all(r["accepted"] for r in env), env)

    def test_no_unexpected_rejection(self):
        for r in self.results:
            if r["accepted"]:
                continue
            if r["mode"] != r["source"]:
                self.assertIn(SOURCE_MISMATCH, r["error"] or "", r)
            else:
                self.assertIn(NOT_YET.get(r["packet_type"], "(없음)"), r["error"] or "", r)

    def test_handoff_samples_match_firmware_output(self):
        # 팀장에게 보낸 예시(docs/lead_handoff)가 지금 펌웨어 출력과 같은지
        base = os.path.join(ROOT, "docs", "lead_handoff")
        with open(os.path.join(base, "samples_device.ndjson"), encoding="utf-8") as f:
            sent = f.read()
        with open(os.path.join(base, "samples_simulation.ndjson"), encoding="utf-8") as f:
            sent += f.read()
        self.assertEqual(sent.splitlines(), self.lines.splitlines())


if __name__ == "__main__":
    unittest.main()
