"""JSONL 로그. 실행마다 logs/<시각>/ 아래에 rx.jsonl(모든 입력)과 events.jsonl을 남긴다."""

import json
import os
import threading
import time


class JsonlLogger:
    def __init__(self, base_dir, meta=None):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(base_dir, stamp)
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.Lock()
        self._rx = open(os.path.join(self.dir, "rx.jsonl"), "a", encoding="utf-8")
        self._ev = open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8")
        with open(os.path.join(self.dir, "session.json"), "w", encoding="utf-8") as f:
            json.dump(dict(meta or {}, started=time.time()), f, ensure_ascii=False, indent=2)

    def _write(self, fp, rec):
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            if fp.closed:  # 종료 중 늦게 들어온 줄
                return
            fp.write(line + "\n")
            fp.flush()

    def rx(self, ts, source, port, result, obj):
        self._write(self._rx, {"rx_ts": ts, "source": source, "port": port, "result": result,
                               "obj": obj})

    def text(self, ts, source, port, line):
        """JSON이 아닌 시리얼 줄(부팅 로그 등)."""
        self._write(self._rx, {"rx_ts": ts, "source": source, "port": port, "result": "text",
                               "text": line})

    def event(self, ev):
        self._write(self._ev, {"rec": "event", **ev})

    def event_update(self, ts, event_id, action, by):
        self._write(self._ev, {"rec": action, "ts": ts, "id": event_id, "by": by})

    def close(self):
        with self._lock:
            self._rx.close()
            self._ev.close()
