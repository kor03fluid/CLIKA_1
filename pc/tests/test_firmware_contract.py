"""환경 노드 펌웨어가 USB로 내보내는 JSON과 서버 입력 형식이 맞는지 확인한다.

가상 노드만으로 시험하면 펌웨어와 서버가 서로 다른 키를 써도 드러나지 않으므로,
펌웨어 소스의 printf 형식과 펌웨어 README의 출력 예를 직접 읽는다.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from squadlink.hub import Hub  # noqa: E402
from squadlink.ingest import parse_line  # noqa: E402

FW_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "firmware", "env_node")
# Serial.printf("{\"type\":\"<종류>\"<나머지 형식 문자열>" — 이스케이프된 따옴표는 건너뛴다
PRINTF_RE = re.compile(r'Serial\.printf\("\{\\"type\\":\\"(\w+)\\"((?:[^"\\]|\\.)*)"')


def read(name):
    with open(os.path.join(FW_DIR, name), encoding="utf-8") as f:
        return f.read()


class FirmwareContractTest(unittest.TestCase):
    def test_printf_formats_carry_node_boot_seq(self):
        found = {}
        for name in ("env_node.ino", "anchor.cpp"):
            for ptype, rest in PRINTF_RE.findall(read(name)):
                found[ptype] = rest
        for ptype in ("env", "anchor"):  # 패킷: node·boot·seq 필수
            self.assertIn(ptype, found)
            for key in ("node", "boot", "seq"):
                self.assertIn('\\"%s\\":%%u' % key, found[ptype], f"{ptype} JSON에 {key} 없음")
        for ptype in ("stats", "boot"):  # 메타: node로 장치를 구분
            self.assertIn('\\"node\\":%u', found[ptype])

    def test_readme_examples_are_accepted(self):
        readme = read("README.md")
        lines = [l for l in readme.splitlines() if l.startswith('{"type":')]
        self.assertGreaterEqual(len(lines), 2)
        hub = Hub()
        for i, line in enumerate(lines):
            obj = parse_line(line)
            self.assertIsNotNone(obj, line)
            self.assertEqual(hub.ingest(obj, "real", "p", float(i)), "ok", line)
        self.assertIn(1, hub.anchors[49])


if __name__ == "__main__":
    unittest.main()
