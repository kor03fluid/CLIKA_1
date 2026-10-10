#!/usr/bin/env python3
"""NDJSON 파일의 JSON 줄을 팀장 서버 입력(POST /api/ingest)에 한 줄씩 보낸다 (팀원 C 시험용).

팀장의 serial_bridge.py --stdin과 같은 일을 하지만 셸 리디렉션(<) 없이 파일 경로로 받는다.
PowerShell·VS Code 작업에서 그대로 쓸 수 있다. "#"으로 시작하는 진단 줄과 JSON이 아닌 줄은 건너뛴다.

예)
  python send_ndjson.py ../docs/lead_handoff/samples_simulation.ndjson
  python send_ndjson.py capture.ndjson --url http://127.0.0.1:8080/api/ingest --gap 0.5
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def send(obj, url, timeout):
    req = urllib.request.Request(url, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "OK", r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return f"REJECT {e.code}", e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return "HTTP FAILED", str(e)


def main(argv=None):
    ap = argparse.ArgumentParser(description="NDJSON 줄을 팀장 서버 /api/ingest로 보내기")
    ap.add_argument("file", help="NDJSON 파일(한 줄에 JSON 객체 하나)")
    ap.add_argument("--url", default="http://127.0.0.1:8080/api/ingest", help="기본: 팀장 서버 8080")
    ap.add_argument("--gap", type=float, default=0.2, help="줄 사이 간격(초)")
    ap.add_argument("--timeout", type=float, default=2.0)
    args = ap.parse_args(argv)
    sent = bad = 0
    with open(args.file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                print(f"SKIP (JSON 아님): {line[:80]}", file=sys.stderr)
                continue
            status, body = send(obj, args.url, args.timeout)
            print(f"{status}  {obj.get('packet_type')} {obj.get('node_id')} seq={obj.get('seq')}  {body[:160]}")
            sent += 1
            bad += status != "OK"
            time.sleep(args.gap)
    print(f"보냄 {sent}줄, 실패·거부 {bad}줄")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
