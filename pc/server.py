#!/usr/bin/env python3
"""SQUAD LINK PC 데이터 서버 (팀원 C).

예)
  python server.py --serial COM5                    # 게이트웨이 USB
  python server.py --serial /dev/ttyUSB0 --serial /dev/ttyUSB1
  python server.py --virtual demo                    # 실물 없이 가상 노드
  python server.py --serial COM5 --virtual normal --virtual-nodes 2   # 병사 2만 가상
  python server.py --replay logs/20261010-120000/rx.jsonl
"""

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from squadlink.hub import Hub  # noqa: E402
from squadlink.ingest import Replayer, SerialReader  # noqa: E402
from squadlink.logger import JsonlLogger  # noqa: E402
from squadlink.virtual import SCENARIOS  # noqa: E402
from squadlink.web import App, serve  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="SQUAD LINK PC 데이터 서버")
    p.add_argument("--serial", action="append", default=[], metavar="PORT",
                   help="USB 시리얼 포트(여러 번 지정 가능)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--virtual", metavar="SCENARIO", choices=sorted(SCENARIOS),
                   help="가상 노드 시나리오: " + ", ".join(sorted(SCENARIOS)))
    p.add_argument("--virtual-nodes", default="",
                   help="가상으로 만들 노드 ID 목록(쉼표). 비우면 병사 1·2, 환경 0x31, 게이트웨이 앵커 0x20")
    p.add_argument("--virtual-speed", type=float, default=1.0)
    p.add_argument("--virtual-loop", action="store_true")
    p.add_argument("--loss-rate", type=float, default=0.0, help="가상 병사 패킷 무작위 누락 비율(0~1)")
    p.add_argument("--replay", metavar="FILE", help="기록 로그(rx.jsonl) 재생")
    p.add_argument("--replay-speed", type=float, default=1.0)
    p.add_argument("--host", default="0.0.0.0", help="휴대폰 접속을 위해 기본은 모든 인터페이스")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--log-dir", default="logs")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logger = JsonlLogger(args.log_dir, meta=vars(args))
    hub = Hub(logger=logger)
    app = App(hub)

    for port in args.serial:
        r = SerialReader(port, args.baud, hub, logger)
        app.readers[port] = r
        r.start()
    if args.replay:
        app.replayer = Replayer(args.replay, hub, speed=args.replay_speed)
        app.replayer.start()
    if args.virtual:
        nodes = [int(n, 0) for n in args.virtual_nodes.split(",") if n.strip()]
        app.set_virtual({"scenario": args.virtual, "nodes": nodes, "speed": args.virtual_speed,
                         "loop": args.virtual_loop, "loss_rate": args.loss_rate})

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
