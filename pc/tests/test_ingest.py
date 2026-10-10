import contextlib
import io
import json
import os
import tempfile
import unittest

from helpers import event, new_hub, status

from squadlink.ingest import Replayer, SerialReader, classify_line, iter_log_records, parse_line


class RecordingHub:
    def __init__(self):
        self.data, self.diag = [], []

    def ingest(self, obj, input_, port):
        self.data.append((obj, input_, port))

    def ingest_diag(self, obj, input_, port):
        self.diag.append((obj, input_, port))


class RaisingHub(RecordingHub):
    def ingest(self, *args):
        raise RuntimeError("boom")


class BrokenSerial:
    def write(self, data):
        raise OSError("device disconnected")


class LineTest(unittest.TestCase):
    def test_parse_line(self):
        self.assertEqual(parse_line('{"a":1}\r\n'), {"a": 1})
        self.assertIsNone(parse_line("ets Jun  8 2016 00:22:57"))
        self.assertIsNone(parse_line("{broken"))
        self.assertIsNone(parse_line('{"t":NaN}'))
        self.assertIsNone(parse_line('{"t":Infinity}'))

    def test_classify_line(self):
        self.assertEqual(classify_line('{"a":1}'), ("data", {"a": 1}))
        self.assertEqual(classify_line('# {"type":"stats"}'), ("diag", {"type": "stats"}))
        self.assertEqual(classify_line("# free text"), ("diag", None))
        self.assertEqual(classify_line("rst:0x1 (POWERON_RESET)"), ("text", None))


class SerialReaderTest(unittest.TestCase):
    def test_routes_data_diag_and_text(self):
        hub = RecordingHub()
        r = SerialReader("COM5", 115200, hub)
        r._on_line(json.dumps(status()))
        r._on_line('# {"type":"stats","node_id":"env_01"}')
        r._on_line("ets Jun  8 2016")
        self.assertEqual(len(hub.data), 1)
        self.assertEqual(hub.data[0][1:], ("serial", "COM5"))
        self.assertEqual(hub.diag[0][0]["node_id"], "env_01")
        self.assertEqual((r.lines, r.text_lines), (3, 1))

    def test_line_error_does_not_escape(self):
        r = SerialReader("p", 115200, RaisingHub())
        with contextlib.redirect_stderr(io.StringIO()):
            r._on_line(json.dumps(status()))
        self.assertEqual(r.lines, 1)

    def test_write_line_failures_return_false(self):
        r = SerialReader("p", 115200, RecordingHub())
        self.assertFalse(r.write_line("stats"))
        r._ser = BrokenSerial()
        self.assertFalse(r.write_line("stats"))
        self.assertIn("disconnected", r.error)


class ReplayTest(unittest.TestCase):
    def write(self, lines):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        f.write("\n".join(lines) + "\n")
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_reads_server_log_and_plain_ndjson(self):
        rec = lambda ts, result, obj: json.dumps({"rx_ts": ts, "input": "serial", "port": "p",
                                                  "result": result, "obj": obj})
        path = self.write([
            json.dumps({"rx_ts": 1.0, "input": "serial", "port": "p", "result": "text", "text": "ets"}),
            rec(2.0, "ok", status(seq=1)),
            rec(3.0, "late", status(seq=0)),
            rec(3.5, "invalid", {"bad": 1}),
            rec(3.6, "shadowed", status(seq=9)),
            json.dumps({"rx_ts": 4.0, "input": "serial", "port": "p", "result": "diag",
                        "diag": {"type": "stats"}}),
            json.dumps(event(seq=2)),
            "not json",
        ])
        recs = list(iter_log_records(path))
        self.assertEqual([(ts, kind) for ts, kind, _ in recs],
                         [(2.0, "data"), (3.0, "data"), (4.0, "diag"), (None, "data")])

    def test_replay_keeps_packet_source_and_marks_input(self):
        path = self.write([json.dumps(status(seq=1, source="device"))])
        hub, clock = new_hub()
        r = Replayer(path, hub, speed=1000, gap_s=0)
        r.run()
        s = hub.snapshot()["soldiers"][0]
        self.assertEqual((s["source"], s["input"]), ("device", "replay"))

    def test_speed_must_be_positive(self):
        hub, _ = new_hub()
        with self.assertRaises(ValueError):
            Replayer("x.jsonl", hub, speed=0)

    def test_missing_file_finishes_with_error(self):
        hub, _ = new_hub()
        r = Replayer(os.path.join(tempfile.gettempdir(), "no-such-squadlink.jsonl"), hub)
        with contextlib.redirect_stderr(io.StringIO()):
            r.run()
        self.assertTrue(r.done)
        self.assertIn("FileNotFoundError", r.error)


if __name__ == "__main__":
    unittest.main()
