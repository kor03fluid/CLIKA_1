"""JSONL 로그. 실행마다 logs/<시각>/ 아래에 rx.jsonl(모든 입력)과 events.jsonl을 남긴다.

디스크 쓰기는 전용 스레드가 한다. 호출 쪽(허브 잠금 안)은 큐에 넣기만 하므로 디스크가 느려도
시리얼·가상·재생 입력과 SSE 전송이 기다리지 않는다. 큐가 빌 때마다 flush해서 바로 파일에 보인다.
쓰기가 실패해도(디스크 가득 참 등) 스레드는 멈추지 않고 그 줄을 버린 뒤 다음 줄을 계속 쓴다.
버린 줄 수와 마지막 오류는 status()로 화면에 보인다.
"""

import json
import os
import queue
import sys
import threading
import time

_STOP = object()


class JsonlLogger:
    def __init__(self, base_dir, meta=None):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(base_dir, stamp)
        os.makedirs(self.dir, exist_ok=True)
        # 입력에서 거르지만, UTF-8로 못 바꾸는 글자가 들어와도 줄을 잃지 않게 이스케이프해 쓴다
        self._rx = open(os.path.join(self.dir, "rx.jsonl"), "a", encoding="utf-8", errors="backslashreplace")
        self._ev = open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8", errors="backslashreplace")
        with open(os.path.join(self.dir, "session.json"), "w", encoding="utf-8") as f:
            json.dump(dict(meta or {}, started=time.time()), f, ensure_ascii=False, indent=2)
        self._q = queue.Queue()
        self._closed = False
        self.error = None   # 마지막 쓰기 오류
        self.dropped = 0    # 쓰지 못하고 버린 줄(추정: 실패한 flush 전에 버퍼에 있던 줄 포함)
        self._writer = threading.Thread(target=self._run, daemon=True, name="log-writer")
        self._writer.start()

    def _write(self, fp, rec):
        # rec은 호출 시점의 얕은 복사본이어야 한다(나중에 바뀌는 dict를 그대로 넘기지 않는다)
        if not self._closed:
            self._q.put((fp, rec))

    def _failed(self, e):
        msg = f"{type(e).__name__}: {e}"
        if msg != self.error:  # 같은 오류는 콘솔에 한 번만
            print(f"[log] 쓰기 실패, 이후 실패한 줄은 버림: {msg}", file=sys.stderr, flush=True)
        self.error = msg

    def _flush(self, dirty):
        """dirty: 파일 -> 마지막 flush 뒤 버퍼에 쓴 줄 수."""
        for f, pending in dirty.items():
            try:
                f.flush()
            except Exception as e:  # 디스크 오류는 대개 여기서 난다. 버퍼에 있던 줄을 잃은 것으로 센다
                self.dropped += pending
                self._failed(e)
        dirty.clear()

    def _run(self):
        dirty = {}
        while True:
            item = self._q.get()
            if item is _STOP:
                break
            fp, rec = item
            if fp is None:  # flush() 요청: 앞선 줄을 모두 쓰고 알린다
                self._flush(dirty)
                rec.set()
                continue
            try:
                try:
                    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
                except (TypeError, ValueError) as e:  # 직렬화할 수 없는 값
                    line = json.dumps({"log_error": str(e)})
                fp.write(line + "\n")
                dirty[fp] = dirty.get(fp, 0) + 1
            except Exception as e:  # OSError(디스크 가득 참) 등: 이 줄을 버리고 계속 돈다
                # 버퍼를 비우다 실패한 것이므로 앞서 버퍼에 있던 줄도 잃은 것으로 센다
                self.dropped += 1 + dirty.pop(fp, 0)
                self._failed(e)
            if self._q.empty():
                self._flush(dirty)
        self._flush(dirty)

    def status(self):
        return {"dir": self.dir, "error": self.error, "dropped": self.dropped}

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
        for f in (self._rx, self._ev):
            try:
                f.close()
            except OSError as e:
                self._failed(e)
