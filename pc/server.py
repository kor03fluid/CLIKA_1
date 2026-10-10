#!/usr/bin/env python3
"""SQUAD LINK C 시험 서버 (팀원 C). 공식 PC 관제는 팀장 쪽 서버(node server.mjs, 8080)이고,
이것은 환경 노드·앵커 시험과 측정용 도구다. 함께 켤 수 있게 기본 포트는 8090.

예)
  python server.py --serial COM5                    # 게이트웨이 USB
  python server.py --serial /dev/ttyUSB0 --serial /dev/ttyUSB1
  python server.py --virtual demo                    # 실물 없이 가상 노드
  python server.py --serial COM5 --virtual normal --virtual-nodes halo_02   # 병사 02만 가상
  python server.py --roster roster.json              # 분대원 배정·환경 노드 설치 지점
  python server.py --replay logs/20261010-120000/rx.jsonl
"""

import argparse
import json
import math
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from squadlink.hub import Hub  # noqa: E402
from squadlink.ingest import Replayer, SerialReader  # noqa: E402
from squadlink.logger import JsonlLogger  # noqa: E402
from squadlink.virtual import SCENARIOS  # noqa: E402
from squadlink.web import App, serve  # noqa: E402


def positive_float(text):
    v = float(text)
    if not (v > 0 and math.isfinite(v)):
        raise argparse.ArgumentTypeError("0보다 큰 유한한 수여야 합니다")
    return v


def ratio(text):
    v = float(text)
    if not 0.0 <= v <= 1.0:
        raise argparse.ArgumentTypeError("0~1 사이여야 합니다")
    return v


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="SQUAD LINK PC 데이터 서버")
    p.add_argument("--serial", action="append", default=[], metavar="PORT",
                   help="USB 시리얼 포트(여러 번 지정 가능)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--virtual", metavar="SCENARIO", choices=sorted(SCENARIOS),
                   help="가상 노드 시나리오: " + ", ".join(sorted(SCENARIOS)))
    p.add_argument("--virtual-nodes", default="",
                   help="가상으로 만들 노드 ID 목록(쉼표). 비우면 halo_01, halo_02, env_01, gateway_01")
    p.add_argument("--virtual-speed", type=positive_float, default=1.0)
    p.add_argument("--virtual-loop", action="store_true")
    p.add_argument("--loss-rate", type=ratio, default=0.0, help="가상 병사 패킷 무작위 누락 비율(0~1)")
    p.add_argument("--replay", metavar="FILE", help="기록 로그(rx.jsonl) 재생")
    p.add_argument("--replay-speed", type=positive_float, default=1.0)
    p.add_argument("--host", default="0.0.0.0", help="휴대폰 접속을 위해 기본은 모든 인터페이스")
    p.add_argument("--port", type=int, default=8090, help="기본 8090(팀장 관제 서버 8080과 겹치지 않게)")
    p.add_argument("--log-dir", default="logs")
    p.add_argument("--roster", metavar="FILE",
                   help='분대원 배정 JSON: {"soldiers":[{"soldier_id","assigned_node_id","name"}],'
                        ' "environment_nodes":[{"node_id","location_name"}]}. 없으면 규격 기본값')
    p.add_argument("--allow-origin", action="append", default=[], metavar="ORIGIN",
                   help="쓰기 API(POST)를 허용할 다른 출처. 관제 UI를 별도 개발 서버에서 띄울 때 "
                        "(예: http://localhost:5173). 여러 번 지정 가능")
    p.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                   help="IP 주소·localhost·*.local 말고 이 서버를 부르는 이름(예: 노트북 이름)으로 접속해 "
                        "확인·종료 버튼을 쓸 때 그 이름. 여러 번 지정 가능")
    return p.parse_args(argv)


def _graceful_exit(signum, frame):
    # SIGTERM(창 닫기·서비스 중지 등)도 Ctrl+C처럼 정리 경로를 타게 해 로그 큐를 끝까지 쓴다
    raise KeyboardInterrupt


def main(argv=None):
    args = parse_args(argv)
    signal.signal(signal.SIGTERM, _graceful_exit)
    roster = env_nodes = None
    if args.roster:
        try:
            with open(args.roster, encoding="utf-8") as f:
                cfg = json.load(f)
            roster, env_nodes = cfg.get("soldiers"), cfg.get("environment_nodes")
        except (OSError, ValueError, AttributeError) as e:
            sys.exit(f"--roster 읽기 실패: {e}")
    try:
        Hub(roster=roster, env_nodes=env_nodes)  # 설정 검사(로그 폴더를 만들기 전에)
    except ValueError as e:
        sys.exit(f"--roster 설정 오류: {e}")
    logger = JsonlLogger(args.log_dir, meta=vars(args))
    hub = Hub(logger=logger, roster=roster, env_nodes=env_nodes)
    app = App(hub, allow_origins=args.allow_origin, allow_hosts=args.allow_host)

    for port in args.serial:
        r = SerialReader(port, args.baud, hub, logger)
        app.readers[port] = r
        r.start()
    if args.replay:
        app.replayer = Replayer(args.replay, hub, speed=args.replay_speed)
        app.replayer.start()
    if args.virtual:
        nodes = [n for n in args.virtual_nodes.split(",") if n.strip()]
        try:
            app.set_virtual({"scenario": args.virtual, "nodes": nodes, "speed": args.virtual_speed,
                             "loop": args.virtual_loop, "loss_rate": args.loss_rate})
        except ValueError as e:
            sys.exit(f"--virtual 설정 오류: {e}")
        note = app.virtual_status().get("note")
        if note:
            print(f"[virtual] 주의: {note}", file=sys.stderr, flush=True)

    threading.Thread(target=app.ticker, daemon=True, name="tick").start()
    httpd = serve(app, args.host, args.port)
    print(f"[squadlink] http://{args.host}:{args.port}  로그: {logger.dir}", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.stopping = True
        httpd.server_close()
        logger.close()
        print("[squadlink] 종료", flush=True)


if __name__ == "__main__":
    main()
