# 환경 노드 펌웨어 (ESP32 WROOM)

SQUAD LINK T4-3 환경 노드. 담당: 팀원 C. 데이터 형식은 **공통 데이터 규격 v1**
([`docs/data_spec_v1.md`](../../docs/data_spec_v1.md))을 따른다.

- DHT11·조도(필수), 소리·불꽃·충격·리드스위치(추가) 측정 → `environment`
- 공기 온도 기준 환경 열 노출 주의 → `event` (`heat_exposure`)
- 고정 앵커: 병사 노드의 **직접** 방송(중계·가상 아님)을 패시브 스캔 → `anchor_observation`
- BLE 비연결 광고로 송신. 고정 5초(기준)와 적응 주기를 시리얼 명령으로 전환
- USB 시리얼에는 보낸 패킷마다 규격 v1 JSON 한 줄(NDJSON). 진단은 `# `로 시작하는 줄로 따로 낸다

**검증 상태**: 빌드 검증(arduino-esp32 3.3.12, `esp32:esp32:esp32`, 경고 없음). JSON 출력 코드(`json_out.cpp`)는
PC에서 빌드·실행해 서버의 규격 검사기로 확인하고, `boot_id`·`seq` 부여(`node.cpp`)도 PC에서 빌드해 출처별 번호와
65535 이후 새 `boot_id`를 확인한다(`pc/tests/test_firmware_contract.py`). 실물 센서·무선은 미검증.

## 파일

| 파일 | 내용 |
|---|---|
| `env_node.ino` | setup/loop, 송신 정책, 시리얼 명령, 진단 줄 |
| `json_out.cpp/.h` | 규격 v1 JSON 출력, 숫자 ID → 문자열 ID |
| `config.h` | 노드 ID, 핀, 임계값, 주기, 광고·스캔 설정 |
| `packet.h` | BLE 무선 패킷 초안 v2 (**바이트 배치는 팀원 B와 확정**) |
| `node.cpp/.h` | boot_id·seq·uptime_ms |
| `sensors.cpp/.h` | 센서 읽기, 감지 래치, 열 노출 판단, 가상 온도 |
| `ble_tx.cpp/.h` | 광고 송신 큐, 송신량 통계 |
| `anchor.cpp/.h` | 병사 직접 수신 RSSI 관측·보고 |

## 핀 (ESP32 DevKit 기준, 실물 확인 후 `config.h` 수정)

| 기능 | GPIO | 비고 |
|---|---|---|
| DHT11 DATA | 4 | 3.3V 공급, 모듈에 풀업 없으면 10kΩ |
| 조도 (분압 출력) | 34 | ADC1 입력 전용. 12bit 원시값(0~4095)을 `light_raw`로 보냄 |
| 소리 DO | 27 | 활성 레벨 `SOUND_ACTIVE_LEVEL` |
| 불꽃 DO | 26 | 활성 레벨 `FLAME_ACTIVE_LEVEL` |
| 충격 DO | 25 | 활성 레벨 `SHOCK_ACTIVE_LEVEL` |
| 리드스위치 | 33 | 핀–GND, 내부 풀업 |
| 상태 LED | 2 | 광고 창 동안 켜짐 |

- 전원은 USB 5V. **5V 출력 신호를 GPIO·ADC에 직접 넣지 않는다.** 모듈은 3.3V로 공급하거나 분압·레벨 변환.
- 디지털 모듈의 활성 레벨(HIGH/LOW)은 모듈마다 다르므로 실물로 확인.
- 추가 센서는 `USE_SOUND` 등을 0으로 끄면 코드와 JSON에서 빠진다(필드·`sensor_status` 키 모두).

## 빌드

Arduino IDE: 보드 매니저에서 **esp32 by Espressif 3.x** 설치 → 보드 `ESP32 Dev Module` → 저장소의
`DHT-sensor-library`, `Adafruit_Sensor`, `RBD_LightSensor` 폴더를 Arduino `libraries`에 복사 → `env_node.ino` 열기.

arduino-cli (저장소 루트에서):

```sh
arduino-cli compile --fqbn esp32:esp32:esp32 \
  --library DHT-sensor-library --library Adafruit_Sensor --library RBD_LightSensor \
  firmware/env_node
```

예비 WROOM은 `NODE_ID`를 `0x32`(env_02)로 바꿔 빌드한다.

## USB 시리얼 출력 (115200bps)

데이터 줄은 규격 v1 그대로다. PC에 직접 연결한 경로이므로 `transport`는 자기 자신이 USB 출력 노드
(`gateway_id: "env_01"`, `route: "direct"`, `rssi_dbm: null`)다. 아래는 실제 출력 코드가 낸 줄이다.

```json
{"schema_version":"1.0","packet_type":"environment","node_id":"env_01","boot_id":"boot_1a2b","seq":1,"source":"device","uptime_ms":10000,"payload":{"air_temperature_c":24.5,"humidity_pct":52,"light_raw":1730,"heartbeat_interval_ms":30000,"sensor_status":{"dht11":"ok","light":"ok","sound":"ok","flame":"ok","shock":"ok","reed":"ok"},"sound_detected":false,"flame_detected":true,"shock_detected":false,"reed_closed":true},"transport":{"gateway_id":"env_01","route":"direct","hop_count":0,"relay_id":null,"rssi_dbm":null}}
{"schema_version":"1.0","packet_type":"event","node_id":"env_01","boot_id":"boot_1a2b","seq":3,"source":"device","uptime_ms":50000,"payload":{"event_id":"env_01:boot_1a2b:heat_exposure:1","event_type":"heat_exposure","mode":"normal"},"transport":{"gateway_id":"env_01","route":"direct","hop_count":0,"relay_id":null,"rssi_dbm":null}}
{"schema_version":"1.0","packet_type":"anchor_observation","node_id":"env_01","boot_id":"boot_1a2b","seq":4,"source":"device","uptime_ms":50300,"payload":{"anchor_id":"env_01","observed_node_id":"halo_01","observed_boot_id":"boot_00a1","observed_seq":1,"rssi_dbm":-58,"observation_age_ms":300},"transport":{"gateway_id":"env_01","route":"direct","hop_count":0,"relay_id":null,"rssi_dbm":null}}
```

필드 규칙:
- 측정 불가는 `null`(예: DHT11 읽기 실패 → 온도·습도 `null`, `sensor_status.dht11: "unavailable"`).
- `light_raw`는 ADC 원시값이다. lux로 바꾸지 않는다.
- `sound_detected`·`shock_detected`: 직전 `environment` 보고 이후 반응이 있었는지(래치).
  `flame_detected`: 지금 반응 중이거나 직전 보고 이후 반응. `reed_closed`: 현재 접점 닫힘 여부.
- `heartbeat_interval_ms`: 지금 선언하는 정상 보고 주기. 적응 모드 평상시 30000, 열 노출·불꽃 중 10000, 고정 모드 5000.
  서버 두절 기준은 `max(15000, 3 × 주기 + 2000)` → 92초 / 32초 / 17초.
- 열 노출 주의(`heat_exposure`)는 공기 온도 기준이다(개인 체온·과열 아님). 환경 노드에는 기도비닉 모드가 없어 `mode`는 항상 `normal`.
- `vtemp`로 가상 온도를 넣는 동안 `environment`와 그 온도로 생긴 사건은 `source: "simulation"`이다.
  사건의 출처는 사건이 생긴 시점에 정한다(큐가 차서 기다리는 사이 `vtemp off` 해도 가상으로 나감).
  앵커 관측은 실제 관측이라 계속 `device`다.
- `seq`는 패킷 종류를 통틀어 부팅 내에서 1부터 증가하되, **출처(`device`/`simulation`)마다 따로 센다**.
  서버가 출처별로 번호가 이어지는지 보고 누락을 세기 때문이다(같이 쓰면 `vtemp` 시험 중 가짜 누락이 생김).
  `boot_id`는 부팅마다 새 값(NVS 카운터, 처음엔 무작위 시작)이고 두 출처가 같은 값을 쓴다.
  `seq`(16bit)가 65535에 이르면 번호를 재사용하지 않도록 새 `boot_id`로 넘어간다(서버는 재부팅처럼 처리).

진단 줄은 `# `로 시작한다(데이터 스트림 아님. 서버는 `stats`만 보관):

```text
# {"type":"boot","node_id":"env_01","boot_id":"boot_1a2b","tx_mode":"adaptive","anchor":true,"schema_version":"1.0"}
# {"type":"stats","node_id":"env_01","boot_id":"boot_1a2b","tx_mode":"adaptive","uptime_ms":61234,"tx":{...},"anchor":{...}}
# {"type":"warn","node_id":"env_01","boot_id":"boot_1a2b","msg":"unknown command: foo"}
```

ESP32 자체 부팅 메시지(ROM 로그)는 JSON이 아니어서 서버가 데이터로 읽지 않는다.

명령(줄 단위):

| 명령 | 동작 |
|---|---|
| `stats` | 송신량·앵커 수신 통계(진단 줄) |
| `mode fixed` / `mode adaptive` | 송신 정책 전환 |
| `vtemp 38` / `vtemp off` | 가상 온도 주입/해제(−40~100 숫자만) |
| `send` | 환경 패킷 즉시 1회 송신 |

## BLE 무선 패킷 초안 v2 (`packet.h`) → 규격 v1 JSON

**바이트 배치는 팀원 B가 확정한다.** 아래는 환경 노드가 지금 쓰는 안과, 게이트웨이가 JSON으로 바꿀 때의 대응이다.
BLE 레거시 광고 제조사 데이터(회사 ID `0xFFFF` = SIG 시험용), 페이로드 최대 24B, little-endian.

공통 머리 11B:

| 바이트 | 필드 | JSON |
|---|---|---|
| 1 | `ver_type` (버전 4bit=2, 종류 4bit) | `packet_type`: 1 soldier_status · 2 gps · 3 environment · 4 anchor_observation · 5 event |
| 1 | `flags` | `0x01` 중계됨 → `transport.route: "relay"` · `0x02` → `source: "simulation"`(없으면 `"device"`) · `0x04` 즉시 송신 |
| 1 | `node_id` | 문자열 ID(아래 변환표) |
| 2 | `boot_id` | `"boot_%04x"` |
| 2 | `seq` | `seq` |
| 4 | `uptime_ms` | `uptime_ms` |

숫자 ID → 문자열 ID(안): `0x01~0x1F` → `halo_01~` · `0x20~0x27` → `gateway_01~` · `0x28~0x2F` → `relay_01~` ·
`0x31~0x3F` → `env_01~`.

| 종류 | 크기 | 본문 → JSON `payload` |
|---|---|---|
| environment (3) | 21B | 온도×10 int16(`INT16_MIN`=null) → `air_temperature_c` · 습도 u8(0xFF=null) → `humidity_pct` · 조도 u16(0xFFFF=null) → `light_raw` · 주기(초) u16 → `heartbeat_interval_ms`(×1000) · 센서 상태 u16(2bit×6: dht11·light·sound·flame·shock·reed, 0 ok·1 unavailable·2 not_implemented·3 disabled) · 감지 u8(2bit×4: sound·flame·shock·reed_closed, 0 false·1 true·2 생략·3 null) |
| event (5) | 15B | 종류 u8(1 sos·2 impact·3 prolonged_still·4 heat_exposure) · 모드 u8(0 normal·1 covert) · 번호 u16 → `event_id = "<node_id>:<boot_id>:<event_type>:<번호>"` |
| anchor_observation (4) | 19B | 관측 노드 u8 → `observed_node_id` · 관측 boot u16 → `observed_boot_id` · 관측 seq u16 · RSSI i8 → `rssi_dbm` · 경과 ms u16 → `observation_age_ms`. `anchor_id`는 머리의 `node_id` |

- 감지 값이 "생략"(2)이면 그 필드와 `sensor_status` 키를 JSON에서 모두 뺀다.
- 앵커 관측은 **패킷 하나에 관측 하나**다. 규격의 중복 제거 키가 앵커의 `seq`라서, 한 패킷에 여러 관측을 넣으면
  JSON으로 펼쳤을 때 같은 seq가 여러 줄 생겨 중복으로 버려진다.
- 반복 광고와 중계는 머리를 그대로 유지한다(규격 4장).
- 앵커는 병사 패킷(종류 1·2·5, ID `0x01~0x1F`)의 머리만 해석하므로 병사 본문 형식과 무관하다.
  중계됨(`0x01`)·가상(`0x02`) 패킷은 관측하지 않는다.

## 송신 정책

| 모드 | 동작 |
|---|---|
| `fixed` (기준) | 환경 5초마다. 감지는 다음 패킷에 실림. 사건은 즉시 |
| `adaptive` (기본) | 사건 즉시 · 감지 즉시(3회 반복, 최소 간격 2초) · 값 변화(온도 1°C·습도 5%·조도 원시값 400·리드 개폐·상태·주기 변화, 최소 3초) · 열 노출/불꽃 중 10초 · 평상시 30초 |

- 소리·충격·불꽃 감지 값은 래치라서 "값 변화" 비교에 넣지 않는다(감지 송신 뒤 참→거짓으로 보여 패킷이 한 번 더 나가지 않게).

앵커 보고: 새 병사 또는 RSSI 평균 6dB 이상 변화 시(최소 2초), 변화 없어도 병사별로 15초마다 보낸다. 병사마다 한 패킷.
송신 큐(6칸)보다 보고할 병사가 많으면 큐 자리만큼만 보내고 나머지는 다음 차례에 먼저 보낸다
(새로 보인 병사 > 변화 > 오래 기다린 순).
`rssi_dbm`은 마지막으로 직접 받은 병사 패킷(`observed_seq`)의 값이다(평활은 서버). 45초 동안 못 받은 병사는 빠지고,
다시 보이면 새로 보인 병사로 바로 보고한다.

`est_adv_events`는 창 길이/광고 간격으로 계산한 **추정치**다. 실제 광고 이벤트 수·RF 방출량으로 부르지 않는다(규격 12장).

## 남은 일

- [ ] 팀원 B와 BLE 바이트 배치·숫자 ID 변환표·회사 ID 확정 (`packet.h`, `json_out.cpp`)
- [ ] 실물 핀·센서 전압·활성 레벨 확인
- [ ] 조도 단선·포화 판정 기준 (현재 항상 `ok`)
- [ ] 열 노출 임계값·변화 기준을 센서 로그로 조정
- [ ] 송신 출력(`BLE_TX_POWER`) 실측으로 선정
- [ ] 센싱·스캔·보고 동시 운용 시 수신 누락 시험, 스캔·보고로 늘어난 소비전류·송신량 기록
- [ ] 예비 WROOM에 같은 펌웨어(`NODE_ID 0x32`) 업로드
