# 부록 A. BLE 무선 패킷 바이트 배치 (C 초안 v2 — 팀원 B 확정 전)

공통 데이터 규격 v1 12장 "BLE 바이트 배치는 구현 담당이 확정한 뒤 부록으로 인계한다"에 따른 부록 초안이다.
**무선 원본 패킷과 게이트웨이 USB 출력은 팀원 B 담당**이므로 B가 확정하기 전까지 아래는 초안이다.
환경 노드 펌웨어(`firmware/env_node/packet.h`)는 지금 이 배치로 송신한다. B와 합의한 내용으로 바뀌면 `packet.h`·`json_out.cpp`를 함께 고친다.

- 범위: 공통 머리, 숫자 ID, `environment`·`event`·`anchor_observation` 본문(C 정의), JSON 변환 규칙.
- `soldier_status`·`gps` 본문은 A·B가 같은 형식으로 채운다(A.4.4).
- 바이트 순서는 little-endian. 오프셋은 페이로드(회사 ID 뒤) 기준 바이트 위치.

## A.1 광고 형식

| 항목 | 값 |
|---|---|
| 광고 종류 | BLE 레거시 광고, 비연결(`ADV_NONCONN_IND`), 스캔 응답 없음 |
| AD 구성 | Flags(3B: `02 01 04`) + 제조사 데이터(`len`, `0xFF`, 회사 ID 2B, 페이로드) |
| 회사 ID | `0xFFFF` (Bluetooth SIG 시험용. 제품용 ID 아님) |
| 페이로드 최대 | 24B (31B − Flags 3B − 제조사 데이터 머리 4B) |
| 환경 노드 송신 설정(참고) | 광고 간격 100ms, 창 300ms(약 3 광고 이벤트), 사건·감지는 같은 패킷을 창 3개로 반복(간격 500ms), 0dBm |

## A.2 공통 머리 (11B)

| 오프셋 | 크기 | 필드 | 값 | JSON |
|---|---|---|---|---|
| 0 | 1 | `ver_type` | 상위 4bit 버전(현재 `2`), 하위 4bit 종류(A.4) | `packet_type` |
| 1 | 1 | `flags` | bit0 `0x01` 중계됨 · bit1 `0x02` 가상 · bit2 `0x04` 즉시 송신(반복) | A.5 |
| 2 | 1 | `node_id` | 숫자 ID(A.3) | `node_id` 문자열 |
| 3 | 2 | `boot_id` | 부팅마다 새 값 | `"boot_%04x"` (예: `0x1a2b` → `"boot_1a2b"`) |
| 5 | 2 | `seq` | 부팅 내 순번 | `seq` |
| 7 | 4 | `uptime_ms` | 패킷 생성 시 부팅 후 경과 ms | `uptime_ms` |

규칙(규격 4장과 같음)

- `seq`는 패킷 종류와 출처(실제·가상)를 통틀어 부팅 안에서 하나씩 증가하고 재사용하지 않는다. 65535 다음에는 새 `boot_id`로 넘어간다.
- 반복 광고와 중계는 머리를 그대로 둔다(`node_id`·`boot_id`·`seq`·`uptime_ms` 유지). 중계기는 `flags`에 `0x01`만 더한다.
- 중복 제거 키는 `source + node_id + boot_id + seq`.

## A.3 숫자 ID ↔ 문자열 ID

| 숫자 범위 | 문자열 | 계산 | 예 |
|---|---|---|---|
| `0x01`~`0x1F` | `halo_01`~`halo_31` | NN = 숫자 | `0x01` → `halo_01`, `0x02` → `halo_02` |
| `0x20`~`0x27` | `gateway_01`~`gateway_08` | NN = 숫자 − `0x1F` | `0x20` → `gateway_01` |
| `0x28`~`0x2F` | `relay_01`~`relay_08` | NN = 숫자 − `0x27` | `0x28` → `relay_01` |
| `0x31`~`0x3F` | `env_01`~`env_15` | NN = 숫자 − `0x30` | `0x31` → `env_01`, **`0x32` → `env_02`(예비 환경 노드)** |
| `0x00`, `0x30`, `0x40`~`0xFF` | 예약 | | |

## A.4 종류별 본문

| 종류 값 | `packet_type` | 정의 | 크기(머리 포함) |
|---|---|---|---|
| `0x1` | `soldier_status` | A·B (A.4.4) | — |
| `0x2` | `gps` | A·B (A.4.4) | — |
| `0x3` | `environment` | C | 21B |
| `0x4` | `anchor_observation` | C | 19B |
| `0x5` | `event` | C 초안(병사 사건도 같은 형식 제안) | 15B |

### A.4.1 `environment` (21B)

| 오프셋 | 크기 | 필드 | 값 | JSON `payload` |
|---|---|---|---|---|
| 11 | 2 | `air_temp_c10` | int16, 공기 온도 ×10. `INT16_MIN`(`0x8000`) = 측정 불가 | `air_temperature_c` = 값/10 또는 `null` |
| 13 | 1 | `humidity_pct` | uint8. `0xFF` = 측정 불가 | `humidity_pct` 또는 `null` |
| 14 | 2 | `light_raw` | uint16, ADC 원시값(12bit). `0xFFFF` = 측정 불가 | `light_raw` 또는 `null` (lux 아님) |
| 16 | 2 | `heartbeat_s` | uint16, 선언 보고 주기(초) | `heartbeat_interval_ms` = ×1000 |
| 18 | 2 | `sensor_status` | 2bit × 6: bit0-1 dht11, 2-3 light, 4-5 sound, 6-7 flame, 8-9 shock, 10-11 reed | `sensor_status` (0 `ok`, 1 `unavailable`, 2 `not_implemented`, 3 `disabled`) |
| 20 | 1 | `detected` | 2bit × 4: bit0-1 sound, 2-3 flame, 4-5 shock, 6-7 reed_closed | `sound_detected`·`flame_detected`·`shock_detected`·`reed_closed` (0 `false`, 1 `true`, 2 생략, 3 `null`) |

- 감지 값이 2(생략)면 그 필드와 `sensor_status`의 해당 키를 JSON에서 모두 뺀다(그 센서를 쓰지 않음).
- `sensor_status.dht11`이 `ok`이면 온도·습도가 모두 숫자, 아니면 모두 `null`. `light`도 같다.

### A.4.2 `event` (15B)

| 오프셋 | 크기 | 필드 | 값 | JSON `payload` |
|---|---|---|---|---|
| 11 | 1 | `event_type` | 1 `sos` · 2 `impact` · 3 `prolonged_still` · 4 `heat_exposure` | `event_type` |
| 12 | 1 | `mode` | 0 `normal` · 1 `covert` | `mode` |
| 13 | 2 | `event_no` | uint16, 부팅·종류마다 1부터 | `event_id` = `"<node_id>:<boot_id>:<event_type>:<event_no>"` |

- 예: `env_01`, `boot_1a2b`, 열 노출 1번 → `"env_01:boot_1a2b:heat_exposure:1"`.
- 같은 사건을 새 패킷으로 다시 알리면 새 `seq`와 같은 `event_no`를 쓴다.
- `heat_exposure`는 **환경 노드가 만들고 서버는 받기만 한다**(2026-10-10 팀장 확정). 공기 온도 35°C 이상에서 생성, 34°C 이하로 해제. 환경 노드에는 기도비닉 모드가 없어 `mode`는 항상 0.

### A.4.3 `anchor_observation` (19B)

| 오프셋 | 크기 | 필드 | 값 | JSON `payload` |
|---|---|---|---|---|
| 11 | 1 | `observed_node` | 관측한 병사 숫자 ID | `observed_node_id` |
| 12 | 2 | `observed_boot` | 관측한 병사 패킷의 `boot_id` | `observed_boot_id` = `"boot_%04x"` |
| 14 | 2 | `observed_seq` | 관측한 병사 패킷의 `seq` | `observed_seq` |
| 16 | 1 | `rssi_dbm` | int8, 그 패킷의 직접 수신 RSSI | `rssi_dbm` |
| 17 | 2 | `age_ms` | uint16, 관측부터 이 패킷 생성까지(최대 65535) | `observation_age_ms` |

- `anchor_id`는 머리의 `node_id`다. 머리의 `boot_id`·`seq`·`uptime_ms`는 앵커의 값이다.
- 패킷 하나에 관측 하나(관측마다 앵커의 `seq`가 달라야 중복 제거에 걸리지 않는다).
- 앵커는 병사 패킷(종류 1·2·5, ID `0x01`~`0x1F`)의 머리만 읽는다. 중계됨(`0x01`)은 관측하지 않는다.
- 가상(`0x02`) 원본은 평상시 관측하지 않는다. **시험 모드**(환경 노드 시리얼 `anchor test on`)에서는 A의 가상 센서 보드처럼 가상 표시가 있는 원본 방송도 관측하고, 그 관측 보고에 가상(`0x02`)을 붙인다. 실제·가상 관측은 따로 보관한다. 중계 제외는 시험 모드에서도 유지한다.

### A.4.4 `soldier_status`·`gps` (A·B 작성 칸)

공통 머리(A.2)를 쓰고 본문은 A·B가 정해 이 칸에 채운다. 앵커는 머리만 읽으므로 본문 형식과 무관하다.
`event`(A.4.2)는 병사 사건(SOS·충격·무움직임)에도 같은 형식을 쓰는 것을 제안한다.

## A.5 게이트웨이 JSON 변환 (B)

| 원본 | JSON |
|---|---|
| `flags & 0x02` | `source: "simulation"`, `transport.route: "simulation"`, `hop_count: 0`, `relay_id: null` |
| `flags & 0x01` (가상 아님) | `source: "device"`, `route: "relay"`, `hop_count: 1`, `relay_id`: 중계기 ID |
| 그 외 | `source: "device"`, `route: "direct"`, `hop_count: 0`, `relay_id: null` |
| 게이트웨이 | `transport.gateway_id`: 게이트웨이 자신의 문자열 ID, `rssi_dbm`: 이번 수신의 RSSI(중계 경로면 중계기 신호) |

- 가상 패킷의 `route`를 `simulation`으로 두는 것은 규격 예시와 팀장 서버 입력 검사(가상이면 `route: "simulation"`, `hop_count: 0`)에 맞춘 것이다.
- 환경 노드를 PC에 USB로 직접 연결하면 환경 노드가 자기 패킷을 같은 JSON으로 낸다(`gateway_id: "env_01"`, 실측 `route: "direct"`, 가상 `route: "simulation"`).

## A.6 B와 확정할 것

| 항목 | C 초안 | 확인 |
|---|---|---|
| 공통 머리 11B·종류 값·플래그 | A.2·A.4 | B |
| 숫자 ID 표, `env_02` = `0x32` | A.3 | B·팀장 |
| 회사 ID | `0xFFFF`(시험용) 유지 | B |
| 중계기 ID 전달 방법 | 미정. 예: 중계기가 페이로드 뒤에 `relay_id` 1B를 붙임(머리 11B + 본문 + 1B ≤ 24B) | B |
| `soldier_status`·`gps` 본문 | A·B 작성 | A·B |
| 버전 값 | 확정 시 `2` 유지 | B |
