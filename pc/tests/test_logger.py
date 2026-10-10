import json
import os
import shutil
import tempfile
import unittest

from helpers import FakeClock, event, status

from squadlink.hub import Hub
from squadlink.logger import JsonlLogger


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
        hub = Hub(logger=log, clock=FakeClock())
        for s in range(1, 51):
            hub.ingest(status(seq=s), "serial", "p")
        hub.ingest(event(seq=51), "serial", "p")
        bad = status(seq=52)
        del bad["payload"]
        hub.ingest(bad, "serial", "p")
        hub.mark_event("halo_01:boot_a1:sos:1", "ack", by="cmd")
        self.assertTrue(log.flush())
        rx = read_jsonl(os.path.join(log.dir, "rx.jsonl"))
        self.assertEqual([r["obj"]["seq"] for r in rx], list(range(1, 53)))
        self.assertEqual(rx[-1]["result"], "invalid")
        self.assertTrue(rx[-1]["errors"])
        ev = read_jsonl(os.path.join(log.dir, "events.jsonl"))
        self.assertEqual([(e["rec"], e["event_id"]) for e in ev],
                         [("event", "halo_01:boot_a1:sos:1"), ("ack", "halo_01:boot_a1:sos:1")])
        log.close()

    def test_close_drains_and_later_writes_are_dropped(self):
        log = JsonlLogger(self.base)
        log.text(1.0, "serial", "p", "boot message")
        log.close()
        log.text(2.0, "serial", "p", "after close")
        rx = read_jsonl(os.path.join(log.dir, "rx.jsonl"))
        self.assertEqual([r["text"] for r in rx], ["boot message"])

    def test_unserializable_record_does_not_stop_writer(self):
        log = JsonlLogger(self.base)
        log.rx(1.0, "serial", "p", "ok", {"bad": object()})
        log.text(2.0, "serial", "p", "next")
        self.assertTrue(log.flush())
        rx = read_jsonl(os.path.join(log.dir, "rx.jsonl"))
        self.assertIn("log_error", rx[0])
        self.assertEqual(rx[1]["text"], "next")
        log.close()


if __name__ == "__main__":
    unittest.main()
