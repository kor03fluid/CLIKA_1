import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from squadlink.hub import Hub  # noqa: E402
from squadlink.ingest import Replayer, SerialReader  # noqa: E402


class RaisingHub:
    def ingest(self, *args):
        raise RuntimeError("boom")


class BrokenSerial:
    def write(self, data):
        raise OSError("device disconnected")


class SerialReaderTest(unittest.TestCase):
    def test_line_error_does_not_escape(self):
        r = SerialReader("p", 115200, RaisingHub())
        with contextlib.redirect_stderr(io.StringIO()):
            r._on_line('{"type":"env","node":49,"boot":1,"seq":1}')  # 예외가 나면 실패
        self.assertEqual(r.lines, 1)

    def test_write_line_failures_return_false(self):
        r = SerialReader("p", 115200, Hub())
        self.assertFalse(r.write_line("stats"))  # 연결 전
        r._ser = BrokenSerial()
        self.assertFalse(r.write_line("stats"))
        self.assertIn("disconnected", r.error)


class ReplayerTest(unittest.TestCase):
    def test_speed_must_be_positive(self):
        with self.assertRaises(ValueError):
            Replayer("x.jsonl", Hub(), speed=0)

    def test_missing_file_finishes_with_error(self):
        r = Replayer(os.path.join(tempfile.gettempdir(), "no-such-squadlink.jsonl"), Hub())
        with contextlib.redirect_stderr(io.StringIO()):
            r.run()
        self.assertTrue(r.done)
        self.assertIn("FileNotFoundError", r.error)

    def test_non_numeric_rx_ts_is_ignored(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write('{"rx_ts":"x","source":"real","port":"p","result":"ok",'
                    '"obj":{"type":"env","node":49,"boot":1,"seq":1}}\n')
        try:
            hub = Hub()
            r = Replayer(f.name, hub, speed=1000, gap_s=0)
            r.run()
            self.assertIsNone(r.error)
            self.assertIn(49, hub.nodes)
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
