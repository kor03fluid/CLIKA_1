"""C 검증 → 팀장 관제 서버 전달.

역할(기획서 10장, 공통 데이터 규격 v1 2장): C는 환경·앵커 수신, USB JSON 입력, 검증·중복 제거·저장을 맡고
팀장은 관제를 맡는다. 그래서 환경 보드의 USB 줄은 C 시험 서버가 먼저 받아 규격 검사와 중복 제거를 하고,
**통과한 가상 데이터만** 팀장 서버의 POST /api/ingest로 넘긴다(팀장 서버는 고치지 않는다).

넘기는 조건(모두 만족)
  - C 서버 판정이 새 패킷(ok, 또는 다른 출처가 표시 중이라 가려진 shadowed). 중복·지연·이전 부팅·무효는 넘기지 않는다
  - 규격 검사 경고도 없음(검사기가 값을 고쳐야 했던 줄은 원래 줄이 틀린 것이므로 넘기지 않는다)
  - source가 정한 출처(기본 simulation = 가상 데이터)
  - 입력이 정한 경로(기본 serial = 환경 보드 USB. C 서버의 가상 노드는 팀장 서버에도 자체 가상 노드가 있어 넘기지 않는다)
보낸 줄은 받은 그대로다. 보내기는 별도 스레드가 하므로 USB 수신을 막지 않는다.
"""

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, deque

FORWARD_RESULTS = ("ok", "shadowed")


class LeadForwarder:
    def __init__(self, url, sources=("simulation",), inputs=("serial",), timeout=2.0, queue_max=2000,
                 post=None):
        self.url = url
        self.sources = tuple(sources)
        self.inputs = tuple(inputs)
        self.timeout = timeout
        self._post = post or self._http_post
        self._q = queue.Queue(maxsize=queue_max)
        self._lock = threading.Lock()
        self.counts = Counter()          # offered, queued, sent, accepted, rejected, failed, queue_full
        self.skipped = Counter()         # 넘기지 않은 이유별
        self.rejected = Counter()        # 팀장 서버 거절 사유별
        self.recent = deque(maxlen=20)   # 최근 결과(화면 표시)
        self._thread = None
        self._stop = threading.Event()

    # ----- 판정 -----
    def reason_to_skip(self, obj, result, errors, warnings, input_):
        if result not in FORWARD_RESULTS:
            return f"result:{result}"
        if errors or warnings:
            return "spec_warning"
        if not isinstance(obj, dict) or obj.get("source") not in self.sources:
            return "source"
        if input_ not in self.inputs:
            return "input"
        return None

    def offer(self, obj, result, errors, warnings, input_, port):
        """Hub.ingest_hooks에 붙이는 함수."""
        with self._lock:
            self.counts["offered"] += 1
            why = self.reason_to_skip(obj, result, errors, warnings, input_)
            if why:
                self.skipped[why] += 1
                return False
            try:
                self._q.put_nowait(obj)
            except queue.Full:
                self.counts["queue_full"] += 1
                return False
            self.counts["queued"] += 1
            return True

    # ----- 보내기 -----
    def _http_post(self, obj):
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def send_one(self, obj):
        """하나 보내고 결과를 센다. 반환: "accepted" | "rejected" | "failed"."""
        try:
            status, body = self._post(obj)
        except (urllib.error.URLError, OSError, ValueError) as e:
            outcome, detail = "failed", str(getattr(e, "reason", e))
        else:
            accepted = False
            detail = ""
            try:
                parsed = json.loads(body) if body else {}
                accepted = status < 300 and parsed.get("accepted", True) is not False
                detail = parsed.get("error") or parsed.get("reason") or ""
            except ValueError:
                accepted = status < 300
                detail = body[:120]
            outcome = "accepted" if accepted else "rejected"
            if not accepted:
                detail = detail or f"HTTP {status}"
        with self._lock:
            self.counts["sent"] += outcome != "failed"
            self.counts[outcome] += 1
            if outcome == "rejected":
                self.rejected[detail[:80]] += 1
            self.recent.append({"at": time.time(), "packet_type": obj.get("packet_type"),
                                "node_id": obj.get("node_id"), "seq": obj.get("seq"),
                                "outcome": outcome, "detail": detail[:120]})
        return outcome

    def _run(self):
        while not self._stop.is_set():
            try:
                obj = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            self.send_one(obj)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="forward-lead")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def drain(self, timeout=5.0):
        """시험용: 큐가 빌 때까지 기다린다."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._q.unfinished_tasks == 0 or self._q.empty():
                with self._lock:
                    if self.counts["queued"] <= self.counts["sent"] + self.counts["failed"]:
                        return True
            time.sleep(0.02)
        return False

    def status(self):
        with self._lock:
            return {"url": self.url, "sources": list(self.sources), "inputs": list(self.inputs),
                    "counts": dict(self.counts), "skipped": dict(self.skipped),
                    "rejected": dict(self.rejected.most_common(5)), "queue": self._q.qsize(),
                    "recent": list(self.recent)[-5:]}
