"""JSONL 로그. 실행마다 logs/<시각>/ 아래에 rx.jsonl(모든 입력)과 events.jsonl을 남긴다.

디스크 쓰기는 전용 스레드가 한다. 호출 쪽(허브 잠금 안)은 큐에 넣기만 하므로 디스크가 느려도
시리얼·가상·재생 입력과 SSE 전송이 기다리지 않는다. 큐가 빌 때마다 flush해서 바로 파일에 보인다.
"""

import json
import os
import queue
import threading
import time

_STOP = object()


class JsonlLogger:
    def __init__(self, base_dir, meta=None):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(base_dir, stamp)
        os.makedirs(self.dir, exist_ok=True)
        self._rx = open(os.path.join(self.dir, "rx.jsonl"), "a", encoding="utf-8")
        self._ev = open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8")
        with open(os.path.join(self.dir, "session.json"), "w", encoding="utf-8") as f:
            json.dump(dict(meta or {}, started=time.time()), f, ensure_ascii=False, indent=2)
        self._q = queue.Queue()
        self._closed = False
        self._writer = threading.Thread(target=self._run, daemon=True, name="log-writer")
        self._writer.start()

    def _write(self, fp, rec):
        # rec은 호출 시점의 얕은 복사본이어야 한다(나중에 바뀌는 dict를 그대로 넘기지 않는다)
        if not self._closed:
            self._q.put((fp, rec))

    def _run(self):
        dirty = set()
        while True:
            item = self._q.get()
            if item is _STOP:
                break
            fp, rec = item
            if fp is None:  # flush() 요청: 앞선 줄을 모두 쓰고 알린다
                for f in dirty:
                    f.flush()
                dirty.clear()
                rec.set()
                continue
            try:
                fp.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                dirty.add(fp)
            except (TypeError, ValueError) as e:  # 직렬화할 수 없는 값
                fp.write(json.dumps({"log_error": str(e)}) + "\n")
                dirty.add(fp)
            if self._q.empty():
                for f in dirty:
                    f.flush()
                dirty.clear()
        for f in dirty:
            f.flush()

    # rx.jsonl 한 줄: rx_ts(서버 UTC epoch 초) · input(serial/sim/replay) · port · result · obj
    def rx(self, ts, input_, port, result, obj, errors=None, warnings=None):
        rec = {"rx_ts": ts, "input": input_, "port": port, "result": result, "obj": obj}
        if errors:
            rec["errors"] = list(errors)
        if warnings:
            rec["warnings"] = list(warnings)
        self._write(self._rx, rec)

    def text(self, ts, input_, port, line):
        """JSON이 아닌 시리얼 줄(ESP32 부팅 메시지 등)."""
        self._write(self._rx, {"rx_ts": ts, "input": input_, "port": port, "result": "text",
                               "text": line})

    def diag(self, ts, input_, port, obj):
        """장치 진단 줄("# {...}"). 데이터 스트림과 구분해 남긴다."""
        self._write(self._rx, {"rx_ts": ts, "input": input_, "port": port, "result": "diag",
                               "diag": obj})

    def event(self, ev):
        self._write(self._ev, {"rec": "event", **ev})

    def event_update(self, ts, source, event_id, action, by):
        self._write(self._ev, {"rec": action, "ts": ts, "source": source, "event_id": event_id,
                               "by": by})

    def flush(self, timeout=5.0):
        """지금까지 넣은 줄이 파일에 쓰일 때까지 기다린다(시험·종료용)."""
        done = threading.Event()
        self._q.put((None, done))
        return done.wait(timeout)

    def close(self):
        """남은 줄을 모두 쓰고 파일을 닫는다. 이후 들어오는 줄은 버린다."""
        if self._closed:
            return
        self._closed = True
        self._q.put(_STOP)
        self._writer.join(timeout=5.0)
        self._rx.close()
        self._ev.close()
