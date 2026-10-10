# PC 데이터 서버 (팀원 C)

게이트웨이·환경 노드가 USB로 보내는 JSON 줄을 받아 중복을 거르고, 노드 상태와 이벤트를 만들고,
로그로 남기고, 노트북과 휴대폰 관제 화면에 같은 상태를 동시에 내보낸다. 실물이 없을 때는 가상 노드로
같은 형식의 데이터를 만든다.

```
게이트웨이(USB) ─┐
환경 노드(USB) ──┼─> Hub(정규화·중복 제거·누락·통신 두절·이벤트) ─> HTTP API / SSE ─> 노트북·휴대폰 관제
가상 노드 ───────┤                    │
로그 재생 ───────┘                    └─> logs/<시각>/rx.jsonl, events.jsonl
```

관제 UI·구역 추정·우선순위 판단은 팀장 담당이다. 이 서버는 그 화면이 쓰는 데이터와 API를 제공한다.
`/`의 디버그 화면은 데이터 확인용이다.

**검증 상태**: 단위 테스트 22개 통과. 가짜 시리얼 장치(pty)로 수신·명령 전달·로그·재생과
디버그 화면(데스크톱·휴대폰 폭)을 확인. 실물 게이트웨이·환경 노드 연결은 미검증.

## 실행

Python 3.9 이상. 시리얼을 쓸 때만 `pip install -r requirements.txt` (pyserial).

```sh
python server.py --virtual demo                         # 실물 없이: 가상 병사 2·환경·앵커
python server.py --serial COM5                          # 게이트웨이 (Windows)
python server.py --serial /dev/ttyUSB0 --serial /dev/ttyUSB1   # 게이트웨이 + 환경 노드
python server.py --serial COM5 --virtual normal --virtual-nodes 2   # 병사 2만 가상
python server.py --replay logs/20261010-120000/rx.jsonl --replay-speed 5
```

- 브라우저: 노트북 `http://localhost:8080`, 휴대폰 `http://<노트북 IP>:8080` (같은 Wi-Fi·핫스팟, 방화벽 허용).
  휴대폰 경로는 핫스팟·Wi-Fi 방출이 생기므로 병사 노드 BLE 송신량과 구분해서 설명한다.
- 주요 옵션: `--virtual-speed 10`(배속), `--virtual-loop`, `--loss-rate 0.2`(무작위 누락), `--port`, `--log-dir`.
- 시리얼 장치가 빠졌다 다시 꽂히면 2초마다 자동으로 다시 연다.

## 입력 형식 (한 줄에 JSON 하나)

패킷은 `type`, `node`, `boot`, `seq`가 필수다. 중복 제거 키는 `node + boot + seq`.
`boot`가 바뀌면 재부팅으로 기록하고, 이전 `boot`의 늦은 패킷은 상태를 바꾸지 않는다(`stale_boot`).
seq 간격으로 누락 수를 센다(16bit 순환, 늦게 온 패킷은 누락에서 뺌).

| type | 보내는 쪽 | 형식 |
|---|---|---|
| `env`, `anchor`, `boot`, `stats` | 환경 노드 | `firmware/env_node/README.md`의 시리얼 출력 |
| `soldier` | 게이트웨이 | 아래 **초안** (팀원 B와 확정) |
| `boot`, `stats`, `warn`, `log` | 모든 장치 | 메타. 패킷 수에 넣지 않음. `stats`는 `device_stats`에 보관 |

JSON이 아닌 줄(ESP32 부팅 메시지 등)은 `rx.jsonl`에 `"result":"text"`로만 남는다.

공통 선택 필드: `via`(`"direct"`/`"relay"`) 또는 `relayed`(bool), `virtual`(bool), `tx_mode`(`"fixed"`/`"adaptive"`).

병사 패킷 초안:

```json
{"type":"soldier","node":1,"boot":5,"seq":120,"via":"direct","relay_id":null,
 "op_mode":"normal","tx_mode":"adaptive",
 "hr":78,"hr_valid":true,"motion":"active","sos":false,
 "alert":"none","reasons":[],
 "body_temp":36.6,"body_temp_virtual":true,
 "gps":{"valid":true,"lat":37.5,"lon":127.0}}
```

- `op_mode`: `normal`(일반) / `silent`(기도비닉). `motion`: `active` / `still` / `impact`.
- `alert`: `none` / `check`(확인 필요) / `priority`(우선 경보). `reasons` 예: `impact_then_still`.
- 체온은 실측 미구현이라 `body_temp_virtual: true`로 둔다.
- 알 수 없는 필드도 그대로 보관해 `latest.soldier`로 내보낸다.

## API

| 요청 | 내용 |
|---|---|
| `GET /api/state` | 전체 상태(아래) |
| `GET /api/events?since=<id>&limit=200` | 이벤트 목록 |
| `GET /api/stream` | SSE. `event: state`(변경 시, 최대 초당 4회) · `event: event`(즉시) |
| `POST /api/events/<id>/ack` | 지휘관 확인. body `{"by":"..."}` 선택 |
| `POST /api/events/<id>/resolve` | 실제 해결. 확인과 따로 기록 |
| `POST /api/virtual` | `{"enabled":true,"scenario":"demo","nodes":[2],"speed":1,"loop":false,"loss_rate":0}` / `{"enabled":false}` |
| `POST /api/cmd` | 장치에 명령 한 줄. `{"port":"COM5","cmd":"mode fixed"}` |
| `GET /api/scenarios` | 가상 시나리오 이름 |

CORS를 허용하므로 관제 UI를 다른 개발 서버에서 띄워도 된다.

`/api/state` 구조:

```
nodes.<id>        kind(soldier|env|anchor) · boot · last_seq · last_rx · age_s · online · timeout_s
                  source(real|virtual|replay) · virtual · via(direct|relay)
                  latest.<type>  마지막 패킷 원문 + rx_ts·source·port
                  counters       rx · dup · missing · relayed · reboots · stale_boot
anchors.<앵커>.<병사>  rssi · rssi_avg · n · last_seq · seen_ts(수신 시각 추정) · age_s · virtual
device_stats.<id>  장치가 보낸 마지막 stats (송신량 비교용)
totals             lines · packets · dup · invalid · meta
virtual · inputs · replay
```

- 앵커 관측의 `seen_ts`는 서버 수신 시각에서 `age_ms`를 뺀 값이다. 오래된 관측으로 최신 값을 덮지 않는다.
  구역 추정(같은 시간대 비교·평활·전환 지연)은 관제 쪽에서 한다.
- 통신 두절: `최대 송신 간격 × 2 + 5초` 동안 못 받으면 `online=false`. 기본 최대 간격은 병사·환경 30초,
  앵커 15초, `tx_mode:"fixed"`면 5초. `squadlink/hub.py` 맨 위에서 조정한다.

## 이벤트

| kind | 등급 | 조건 |
|---|---|---|
| `sos` | critical | `sos`가 false → true |
| `alert:check`, `alert:priority` | warning / critical | `alert` 값이 바뀔 때 |
| `hr_contact` | info | `hr_valid`가 false가 될 때(접촉 불량, 이상과 구분) |
| `gps_lost` | info | 유효 GPS → 무효 |
| `env:heat`, `env:flame` | warning | 환경 노드 이벤트 |
| `env:sound`, `env:shock`, `env:reed` | info | 환경 노드 이벤트 |
| `comm_lost`, `comm_restored` | warning / info | 통신 두절 판정·복구 |
| `reboot` | info | `boot` 변경 |

등급은 서버 기본 분류다. 최종 우선순위는 관제 쪽 판단 로직이 정한다. 모든 이벤트에 `source`·`virtual` 라벨,
`acked_at`(확인)·`resolved_at`(해결)이 따로 있다.

## 가상 노드

병사 `1`·`2`, 환경 노드 `0x31`(앵커 겸용), 게이트웨이 앵커 `0x20`을 만든다. 모든 패킷에 `"virtual":true`.

| 시나리오 | 내용 |
|---|---|
| `normal` | 정상 송신만 |
| `demo` | 90초 시연 흐름: 쓰러짐(충격 후 무움직임) → SOS → 중계 경유 → 복귀 |
| `sos`, `fall`, `relay`, `move` | SOS / 쓰러짐 / 중계 경유 / 구역 이동 |
| `loss`, `dup`, `reboot` | 80초 무수신(통신 두절) / 중복 패킷 / 재부팅 |
| `gps_fail`, `hr_contact` | 위치 무효 / 심박 접촉 불량 |
| `heat`, `env_events` | 환경 온도 상승 / 소리·충격·리드 이벤트 |
| `all` | 위 시나리오 전부를 이어서(약 12분). 도착 전 통합 시험용 |

시연 중 실물 노드 하나가 안 보이면 디버그 화면이나 API로 그 노드만 가상으로 켠다:
`POST /api/virtual {"scenario":"normal","nodes":[2]}`. 화면과 로그에 가상 라벨이 붙으므로 말로도 밝힌다.
실물과 같은 ID를 가상으로 켜면 boot가 달라 재부팅 이벤트가 한 번 생긴다.

## 로그

`logs/<시작 시각>/`

- `rx.jsonl`: 모든 입력 줄. `rx_ts`, `source`, `port`, `result`(ok·dup·stale_boot·meta·invalid·text), `obj`
- `events.jsonl`: 이벤트(`rec:"event"`)와 확인·해결 기록(`rec:"ack"`, `rec:"resolve"`)
- `session.json`: 실행 옵션

`--replay`로 `rx.jsonl`을 다시 흘릴 수 있다(`source:"replay"`로 표시, 실시간 시연이 아님을 밝힌다).

## 테스트

```sh
python -m unittest discover -s tests
```

## 남은 일

- [ ] 팀원 B와 게이트웨이 USB JSON 형식 확정(병사 패킷 필드, 중계 표시, 게이트웨이 앵커 보고)
- [ ] 팀장과 관제 UI가 쓸 필드·이벤트 등급 확인
- [ ] 실물 송신 간격에 맞춰 통신 두절 기준 조정
- [ ] 실물 게이트웨이·환경 노드 연결 시험
