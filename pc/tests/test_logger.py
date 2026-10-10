import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from squadlink.hub import Hub  # noqa: E402
from squadlink.logger import JsonlLogger  # noqa: E402


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class JsonlLoggerTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="squadlink-log-")

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_writes_in_order_from_background_thread(self):
        log = JsonlLogger(self.base)
        hub = Hub(logger=log)
        for s in range(1, 51):
            hub.ingest({"type": "soldier", "node": 1, "boot": 1, "seq": s, "sos": s == 10}, "real", "p", s)
        self.assertTrue(log.flush())
        rx = read_jsonl(os.path.join(log.dir, "rx.jsonl"))
        self.assertEqual([r["obj"]["seq"] for r in rx], list(range(1, 51)))
        ev = read_jsonl(os.path.join(log.dir, "events.jsonl"))
        self.assertEqual([e["kind"] for e in ev], ["sos"])
        log.close()

    def test_close_drains_and_later_writes_are_dropped(self):
        log = JsonlLogger(self.base)
        log.text(1.0, "real", "p", "boot message")
        log.close()
        log.text(2.0, "real", "p", "after close")  # 예외 없이 버려져야 한다
        rx = read_jsonl(os.path.join(log.dir, "rx.jsonl"))
        self.assertEqual([r["text"] for r in rx], ["boot message"])

    def test_unserializable_record_does_not_stop_writer(self):
        log = JsonlLogger(self.base)
        log.rx(1.0, "real", "p", "ok", {"bad": object()})
        log.text(2.0, "real", "p", "next")
        self.assertTrue(log.flush())
        rx = read_jsonl(os.path.join(log.dir, "rx.jsonl"))
        self.assertIn("log_error", rx[0])
        self.assertEqual(rx[1]["text"], "next")
        log.close()


if __name__ == "__main__":
    unittest.main()
