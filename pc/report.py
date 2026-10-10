#!/usr/bin/env python3
"""SQUAD LINK 로그 요약 (팀원 C). 실물 시험의 수신·누락·송신량 기록용.

예)
  python report.py logs/20261010-120000              # 서버 로그 폴더(rx.jsonl)
  python report.py env01_capture.ndjson               # 장치 USB 출력을 그대로 저장한 파일
  python report.py logs/20261010-120000 --json > result.json
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from squadlink.report import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
