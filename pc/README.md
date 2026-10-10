# PC 데이터 서버 (팀원 C)

게이트웨이·환경 노드가 USB로 보내는 **공통 데이터 규격 v1**([`docs/data_spec_v1.md`](../docs/data_spec_v1.md)) NDJSON을
받아 검사·중복 제거하고, 분대원 8명의 통신 상태와 사건 상태를 관리하고, 로그로 남기고, 노트북과 휴대폰 관제
화면에 같은 상태를 동시에 내보낸다. 실물이 없을 때는 가상 노드로 같은 형식의 데이터를 만든다.

```
게이트웨이(USB NDJSON) ─┐
환경 노드(USB NDJSON) ──┼─> 검사(schema) ─> Hub(중복 제거·지연·분대원·통신 상태·사건) ─> HTTP API / SSE ─> 관제
가상 노드 ──────────────┤                        │
로그 재생 ──────────────┘                        └─> logs/<시각>/rx.jsonl, events.jsonl
```

관제 UI·구역 추정·PMVP는 팀장 담당이다. 이 서버는 그 화면이 쓰는 데이터와 API를 제공한다.
`/`의 디버그 화면은 데이터 확인용이다.

**검증 상태**: 단위 테스트 73개 통과. 규격 문서의 JSON 예시 5개와, 환경 노드 펌웨어의 실제 JSON 출력 코드를
PC에서 빌드·실행한 결과를 검사기로 확인한다. 가짜 시리얼 장치로 수신·진단 줄·명령 전달·로그와 디버그 화면
(데스크톱·휴대폰 폭)을 확인. 실물 게이트웨이·환경 노드 연결은 미검증.

## 실행

Python 3.9 이상. 시리얼을 쓸 때만 `pip install -r requirements.txt` (pyserial).

```sh
python server.py --virtual demo                          # 실물 없이: 규격 11장 시연 흐름
python server.py --serial COM5                           # 게이트웨이 (Windows)
python server.py --serial /dev/ttyUSB0 --serial /dev/ttyUSB1   # 게이트웨이 + 환경 노드
python server.py --serial COM5 --virtual normal --virtual-nodes halo_02   # 병사 02만 가상
python server.py --roster roster.json                    # 분대원 배정·환경 노드 설치 지점
python server.py --replay logs/20261010-120000/rx.jsonl --replay-speed 5
```

- 브라우저: 노트북 `http://localhost:8080`, 휴대폰 `http://<노트북 IP>:8080` (같은 Wi-Fi·핫스팟, 방화벽 허용).
  휴대폰 경로는 핫스팟·Wi-Fi 방출이 생기므로 병사 노드 BLE 송신량과 구분해서 설명한다.
- 관제 UI를 별도 개발 서버에서 띄워 확인·종료 버튼까지 쓰려면 `--allow-origin http://localhost:5173`처럼 그 주소를 지정한다.
- 주요 옵션: `--virtual-speed 10`(배속), `--virtual-loop`, `--loss-rate 0.2`(무작위 누락), `--port`, `--log-dir`.
- 시리얼 장치가 빠졌다 다시 꽂히면 2초마다 자동으로 다시 연다. Ctrl+C·SIGTERM으로 끄면 남은 로그를 모두 쓰고 닫는다.

`roster.json` 예(없으면 규격 기본값: 8명, 병사 01·02 ← `halo_01`·`halo_02`, 환경 노드 `env_01`):

```json
{"soldiers": [{"soldier_id": "soldier_01", "assigned_node_id": "halo_01", "name": "홍길동"},
              {"soldier_id": "soldier_02", "assigned_node_id": "halo_02"},
              {"soldier_id": "soldier_03", "assigned_node_id": null}],
 "environment_nodes": [{"node_id": "env_01", "location_name": "북쪽 출입구"}]}
```

## 입력 처리 (규격 v1)

- **한 줄 = JSON 객체 하나**(UTF-8). `#`로 시작하는 줄은 장치 진단(`# {...}`), 그 밖의 JSON이 아닌 줄(ESP32 부팅
  메시지 등)은 로그에만 남는다. `NaN`·`Infinity`가 든 줄은 받지 않는다.
- **검사**(`squadlink/schema.py`): 공통 머리·`transport`·패킷 종류별 `payload`의 필수 필드·자료형·enum·범위.
  어기면 `invalid`로 받지 않고 이유를 `recent_invalid`와 로그에 남긴다. 고칠 수 있는 규칙 위반은 고쳐서 받고
  `recent_warnings`에 남긴다(예: 심박 품질이 `good`이 아닌데 bpm이 있음 → `null`, `fix_valid: false`인데 좌표 있음 → `null`,
  실제 노드인데 체온이 있음 → `null`).
- **중복 제거 키**: `source + node_id + boot_id + seq`. 같은 패킷이 다시 오면 `dup`(수신 기록을 갱신하지 않음).
- **지연 패킷**: 이미 받은 것보다 작은 `seq`(`late`)나 이전 `boot_id`(`stale_boot`)는 최신 상태를 덮지 않는다.
  사건은 `event_id`로 따로 기록한다(`late: true`). 예전 `boot_id`가 다시 와도 현재 boot가 두절 기준만큼 조용했으면
  재사용된 번호로 보고 새 부팅으로 받는다.
- **출처**: 같은 `node_id`를 실제(`device`)와 가상(`simulation`)이 함께 보내면 실제가 우선이다. 표시 중인 출처가
  활동 중이면 다른 출처의 상태 패킷은 `shadowed`로 가리고(사건은 출처 라벨을 달고 기록), 두절 기준만큼 조용하면
  이어받는다. 같은 입력 포트에서 출처가 바뀌면(환경 노드 `vtemp` 시험) 장치가 바꾼 것으로 보고 따른다.
  앵커 관측은 출처 선택과 무관하게 받는다.

## 상태

- **분대원**(`soldiers`, 8명): `connection_state`
  - `unassigned`: 배정 노드 없음(미배정 인원은 두절·정상으로 세지 않음)
  - `waiting`: 배정했지만 유효한 `soldier_status`를 아직 못 받음(주기 정보가 없어 `lost`로 바꾸지 않음)
  - `connected`: 새 패킷(직접·중계)이 두절 기준 안에 들어옴
  - `lost`: `timeout_ms = max(15000, 3 × heartbeat_interval_ms + 2000)` 초과. 서버 단조 시계로 잰다
- 주기는 가장 최근 유효 `soldier_status`·`environment`의 `heartbeat_interval_ms`. 중복 패킷, 이전 순번·이전 boot의
  지연 패킷, 다른 노드의 앵커 관측, 지휘관 조작은 수신 기록(`last_seen_at`)을 갱신하지 않는다.
- `data_stale`: `connection_state != "connected"`. 위치는 마지막 유효 GPS를 `location_updated_at`과 함께 보관하고,
  지금 무효이거나 연결이 끊기면 `location_stale: true`. `estimated_zone_id`는 앵커 구역 추정 검증 전이라 `null`.
- 시각은 UTC ISO 8601(`2026-10-10T01:49:00.000Z`). 관제는 한국 시간으로 표시한다. `uptime_ms`를 발생 시각으로 쓰지 않는다.

## 사건

- 노드 사건(`event` 패킷): 키는 `source + event_id`. 같은 `event_id`의 재보고는 `report_count`만 늘고
  확인·해결 상태를 초기화하지 않는다. 새 `event_id`는 새 미확인 사건.
- 서버 사건: 통신 두절 전환마다 한 번 `connection_lost`(`event_id: "server:<node_id>:connection_lost:<n>"`).
  분대원에 배정된 노드와 환경 노드만 만든다. 재연결은 사건을 해결하지 않는다.
- `event_state`: `open` → `acknowledged`(지휘관 확인) → `resolved`(조치 종료). 확인 없이 종료할 수 있고,
  종료한 사건은 다시 바꾸지 않는다. 사건 상태와 측정·연결 상태는 따로 표시한다.
- 사건 레코드: `event_id, event_type, origin(node|server), node_id, soldier_id, source, mode, boot_id, seq,
  route, late, event_state, first_received_at, last_received_at, report_count, acknowledged_at, acknowledged_by,
  resolved_at, resolved_by, n`(서버 순번).

## API

| 요청 | 내용 |
|---|---|
| `GET /api/state` | 전체 상태(아래) |
| `GET /api/events?since=<n>&limit=200` | 사건 목록(`n`보다 나중 것) |
| `GET /api/stream` | SSE. `event: state`(변경 시, 최대 초당 4회) · `event: event`(즉시). 상태 JSON은 변경당 한 번 만들어 모든 연결이 같이 쓴다 |
| `GET /api/roster` / `POST /api/roster` | 분대원 배정 조회·변경 `{"soldier_id","assigned_node_id"(null 가능),"name"}` |
| `POST /api/env_nodes` | 환경 노드 설치 지점 `{"node_id","location_name"}` |
| `POST /api/events/<event_id>/ack` | 지휘관 확인. body `{"by"}` 선택. 같은 ID가 두 출처에 있으면 `?source=device` |
| `POST /api/events/<event_id>/resolve` | 조치 종료 |
| `POST /api/virtual` | `{"enabled":true,"scenario":"demo","nodes":["halo_02"],"speed":1,"loop":false,"loss_rate":0}` / `{"enabled":false}` |
| `POST /api/cmd` | 장치에 명령 한 줄. `{"port":"COM5","cmd":"stats"}` |
| `GET /api/scenarios` | 가상 시나리오 이름 |

`event_id`의 `:`는 그대로 써도 되고 `/`가 들어 있으면 퍼센트 인코딩한다.

쓰기 요청(POST)은 `Content-Type: application/json`이어야 한다(아니면 415). 브라우저에서 오는 쓰기는 같은 출처와
`--allow-origin`으로 지정한 출처만 받는다(아니면 403). Origin 헤더가 없는 클라이언트(curl, 스크립트)는 받는다.
같은 네트워크의 기기가 직접 요청하는 것까지 막지는 않는다.

`/api/state` 구조:

```
schema_version · server_time · version
soldiers[]            soldier_id · name · assigned_node_id · connection_state · data_stale · source · input
                      last_seen_at · received_at · heartbeat_interval_ms · timeout_ms
                      status(최근 soldier_status payload) · status_seq · status_boot_id · route
                      location{fix_valid, latitude_deg, longitude_deg, hdop, location_updated_at, location_stale}
                      estimated_zone_id(null) · active_event_ids
environment_nodes[]   node_id · location_name · connection_state · data_stale · source · input · last_seen_at
                      received_at · heartbeat_interval_ms · timeout_ms · environment(최근 payload) · active_event_ids
anchor_observations[] anchor_id · observed_node_id · observed_boot_id · observed_seq · rssi_dbm · observed_at
                      received_at · age_ms · source · route
nodes{node_id}        노드별 진단: kinds · active_source · counters(rx·dup·late·stale_boot·shadowed·missing·relayed·reboots)
event_counts · totals · recent_invalid · recent_warnings · device_stats · virtual · inputs · replay
```

`input`은 데이터가 들어온 경로(`serial`·`sim`·`replay`), `source`는 패킷의 출처(`device`·`simulation`)다.
재생 데이터는 `source`를 그대로 유지하고 `input: "replay"`로 구분한다.

## 가상 노드

`halo_01`·`halo_02`(보고 주기 10초 → 두절 기준 32초), `env_01`(앵커 겸용), `gateway_01`(앵커).
모든 패킷은 `source: "simulation"`, `transport.route: "simulation"`(중계 시험은 `"relay"`).

| 시나리오 | 내용 |
|---|---|
| `normal` | 정상 송신만 |
| `demo` | 규격 11장: 정상 → 15초 병사 01 SOS → 35초 병사 02 송신 중단(약 62초 두절) → 85초 재개(복구). 확인·종료는 지휘관이 조작 |
| `sos` | SOS · 같은 사건 새 패킷 재보고 · 같은 패킷 중복 · 새로 누른 SOS |
| `impact` | 충격(`impact`) → 무움직임 → `prolonged_still` → 회복 |
| `loss`, `reboot`, `dup`, `late` | 두절과 복구 / 새 `boot_id` / 중복 / 순서 바뀐 지연 패킷 |
| `hr_contact`, `gps`, `relay`, `covert` | 심박 접촉 해제 / GPS 수신·미수신 / 중계 경유 / 기도비닉 |
| `heat`, `env_sensors`, `move` | 환경 열 노출 주의 / 소리·충격·리드 / 앵커 RSSI 구역 이동 |
| `all` | 위 시나리오를 이어서(추가 검증 항목 전부) |

시연 중 실물 노드 하나가 안 보이면 그 노드만 가상으로 켠다: `POST /api/virtual {"scenario":"normal","nodes":["halo_02"]}`.
실물이 아직 보내고 있으면 가상은 가려지고, 실물이 두절 기준만큼 조용해진 뒤 이어받는다. 화면과 로그에 가상 라벨이 붙으므로 말로도 밝힌다.

## 로그

`logs/<시작 시각>/`

- `rx.jsonl`: 모든 입력 줄. `rx_ts`(UTC epoch 초), `input`, `port`, `result`(ok·late·stale_boot·dup·shadowed·invalid·error·
  diag·text), `obj`, `errors`, `warnings`
- `events.jsonl`: 사건(`rec:"event"`)과 확인·종료 기록(`rec:"ack"`, `rec:"resolve"`)
- `session.json`: 실행 옵션

파일 쓰기는 전용 스레드가 한다. 강제 종료(kill -9, 전원 차단)에서는 마지막 몇 줄이 빠질 수 있다.
`--replay`로 `rx.jsonl`(받아들였던 줄·중복·지연·진단)이나 NDJSON 파일을 다시 흘릴 수 있다.

## 테스트

```sh
python -m unittest discover -s tests
```

`test_firmware_contract.py`는 C++ 컴파일러(g++ 또는 clang++)가 있으면 환경 노드 펌웨어의 JSON 출력 코드를 빌드해 확인한다.

## 남은 일

- [ ] 팀원 B: 게이트웨이 USB 출력이 규격 v1과 맞는지 실물로 확인(이 서버의 `recent_invalid`로 이유 확인 가능)
- [ ] 팀장: 관제 UI가 쓸 필드 확인, 분대원 이름·환경 노드 설치 지점 등록
- [ ] 실물 보고 주기에 맞춰 두절 기준 확인
- [ ] 앵커 구역 추정(`estimated_zone_id`)은 앵커 수신 시험 통과 후 팀장과 적용
