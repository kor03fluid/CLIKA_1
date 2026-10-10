import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from helpers import FakeClock, event, status

from squadlink.hub import Hub
from squadlink.logger import JsonlLogger
from squadlink.web import App


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

    def test_disk_error_does_not_stop_writer(self):
        log = JsonlLogger(self.base)
        real = log._rx

        class Full:  # 디스크 가득 참
            def write(self, s):
                raise OSError(28, "No space left on device")

            def flush(self):
                pass

        log._rx = Full()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            for i in range(3):
                log.text(float(i), "serial", "p", "lost")
            self.assertTrue(log.flush())
        self.assertEqual(err.getvalue().count("No space left"), 1)  # 콘솔에는 한 번만
        st = log.status()
        self.assertEqual((st["dir"], st["dropped"]), (log.dir, 3))
        self.assertIn("OSError", st["error"])
        log._rx = real  # 공간이 다시 생기면 이어서 쓴다
        log.text(9.0, "serial", "p", "back")
        self.assertTrue(log.flush())
        self.assertEqual([r["text"] for r in read_jsonl(os.path.join(log.dir, "rx.jsonl"))], ["back"])
        log.close()

    def test_lines_lost_in_buffer_are_counted(self):
        # 디스크 오류는 보통 버퍼를 비울 때(flush) 난다. 그때 버퍼에 있던 줄을 버린 것으로 센다
        log = JsonlLogger(self.base)

        class FlushFails:
            def write(self, s):
                return len(s)

            def flush(self):
                raise OSError(28, "No space left on device")

        log._rx.close()
        log._rx = FlushFails()
        with contextlib.redirect_stderr(io.StringIO()):
            for i in range(5):
                log.text(float(i), "serial", "p", "lost")
            self.assertTrue(log.flush())
        self.assertEqual(log.status()["dropped"], 5)
        log._rx = open(os.devnull, "w")
        log.close()

    def test_state_shows_log_status(self):
        log = JsonlLogger(self.base)
        app = App(Hub(logger=log, clock=FakeClock()))
        self.assertEqual(app.state()["log"], {"dir": log.dir, "error": None, "dropped": 0})
        log.close()


if __name__ == "__main__":
    unittest.main()
