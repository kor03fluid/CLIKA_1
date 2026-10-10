"""입력 경로: USB 시리얼(게이트웨이·환경 노드)과 로그 재생.

입력 형식은 한 줄에 JSON 객체 하나. JSON이 아닌 줄(ESP32 부팅 메시지 등)은 로그에만 남긴다.
"""

import json
import math
import sys
import threading
import time
import traceback


def _reject_constant(name):
    # NaN·Infinity는 표준 JSON이 아니어서 그대로 내보내면 브라우저 JSON.parse가 실패한다
    raise ValueError("non-standard JSON constant: " + name)


def parse_line(line):
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line, parse_constant=_reject_constant)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


class SerialReader(threading.Thread):
    """시리얼 포트 하나를 읽는다. 끊기면 2초마다 다시 연다(USB 재연결 대비)."""

    def __init__(self, port, baud, hub, logger=None, clock=time.time):
        super().__init__(daemon=True, name="serial:" + port)
        self.port = port
        self.baud = baud
        self.hub = hub
        self.logger = logger
        self.clock = clock
        self.connected = False
        self.lines = 0
        self.error = None
        self._ser = None
        self._stop_evt = threading.Event()
        self._wlock = threading.Lock()

    def run(self):
        import serial  # pyserial. 시리얼을 쓸 때만 필요

        while not self._stop_evt.is_set():
            try:
                ser = serial.Serial(self.port, self.baud, timeout=1)
                with self._wlock:
                    self._ser = ser
                self.connected = True
                print(f"[serial {self.port}] 연결", file=sys.stderr, flush=True)
                self.error = None
                buf = b""
                while not self._stop_evt.is_set():
                    chunk = ser.readline()
                    if not chunk:
                        continue
                    buf += chunk
                    if not buf.endswith(b"\n"):
                        continue
                    line = buf.decode("utf-8", errors="replace").strip()
                    buf = b""
                    if line:
                        self._on_line(line)
            except Exception as e:  # serial.SerialException, OSError 등
                if str(e) != self.error:
                    print(f"[serial {self.port}] {e}", file=sys.stderr, flush=True)
                self.error = str(e)
            finally:
                self.connected = False
                with self._wlock:  # write_line과 겹치지 않게 닫는다
                    ser, self._ser = self._ser, None
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass
            self._stop_evt.wait(2.0)

    def _on_line(self, line):
        """한 줄 처리. 여기서 난 예외는 포트를 닫지 않고 기록만 한다."""
        self.lines += 1
        now = self.clock()
        try:
            obj = parse_line(line)
            if obj is None:
                if self.logger:
                    self.logger.text(now, "real", self.port, line)
                return
            self.hub.ingest(obj, "real", self.port, now)
        except Exception:
            print(f"[serial {self.port}] 줄 처리 실패: {line[:120]}", file=sys.stderr, flush=True)
            traceback.print_exc()

    def write_line(self, text):
        """장치로 명령 한 줄 보내기(예: 환경 노드 "stats", "mode fixed"). 실패하면 False."""
        with self._wlock:
            if self._ser is None:
                return False
            try:
                self._ser.write((text.strip() + "\n").encode("utf-8"))
                return True
            except Exception as e:  # 분리 직후 등
                self.error = str(e)
                return False

    def status(self):
        return {"port": self.port, "baud": self.baud, "connected": self.connected,
                "lines": self.lines, "error": self.error}

    def stop(self):
        self._stop_evt.set()


def iter_log_records(path):
    """rx.jsonl(이 서버의 로그) 또는 JSON 줄 파일에서 (원래 수신 시각 또는 None, 객체)를 낸다."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            obj = parse_line(line)
            if obj is None:
                continue
            if "rx_ts" in obj and "result" in obj:  # 서버 로그 형식
                # 받아들였던 줄(+중복·이전 부팅 패킷)만 다시 흘린다. 다른 출처에 가려졌던 줄(shadowed)은 뺀다.
                if (obj["result"] in ("ok", "late", "meta", "dup", "stale_boot")
                        and isinstance(obj.get("obj"), dict)):
                    ts = obj["rx_ts"]
                    ok_ts = isinstance(ts, (int, float)) and not isinstance(ts, bool)
                    yield (ts if ok_ts else None), obj["obj"]
            else:
                yield None, obj


class Replayer(threading.Thread):
    """기록 로그를 다시 흘려보낸다. source="replay"로 표시되어 실시간 데이터와 구분된다."""

    def __init__(self, path, hub, speed=1.0, gap_s=1.0, clock=time.time):
        if not (speed > 0 and math.isfinite(speed)):
            raise ValueError("replay speed must be a finite number > 0")
        super().__init__(daemon=True, name="replay")
        self.path = path
        self.hub = hub
        self.speed = speed
        self.gap_s = gap_s  # 시각 정보가 없는 줄 사이 간격
        self.clock = clock
        self.done = False
        self.error = None
        self._stop_evt = threading.Event()

    def run(self):
        prev_ts = None
        try:
            for ts, obj in iter_log_records(self.path):
                if self._stop_evt.is_set():
                    break
                if ts is not None and prev_ts is not None:
                    wait = max(0.0, (ts - prev_ts) / self.speed)
                elif ts is None:
                    wait = self.gap_s / self.speed
                else:
                    wait = 0.0
                prev_ts = ts if ts is not None else prev_ts
                if self._stop_evt.wait(min(wait, 60.0)):
                    break
                self.hub.ingest(obj, "replay", "replay", self.clock())
        except Exception as e:  # 파일 열기·읽기 실패
            self.error = f"{type(e).__name__}: {e}"
            print(f"[replay] {self.error}", file=sys.stderr, flush=True)
        finally:
            self.done = True

    def stop(self):
        self._stop_evt.set()
