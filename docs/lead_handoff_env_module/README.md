# C → 팀장: 환경 모듈 펌웨어 자료 (2026-10-10)

요청하신 세 가지(펌웨어, 실제 출력 JSON, 연결 방식)를 정리했다.

## 1. 펌웨어

| 항목 | 내용 |
|---|---|
| 저장소 | https://github.com/kor03fluid/CLIKA_1 (브랜치 `main`) |
| 폴더 | `firmware/env_module/` (Arduino 스케치 `env_module.ino`, 설명서는 그 폴더의 `README.md`) |
| 펌웨어 커밋 | **`fc7781e2a1dc2c744e955957c96a332764153b4c`** (`fc7781e`). 이 커밋 이후 펌웨어 파일은 바뀌지 않았다 |
| 펌웨어 판 | `fw` = `env_module/1.0.0` (부팅·`stats` 진단 줄) |
| ZIP | `docs/C_to_lead_env_module.zip`: 펌웨어 폴더 전체, 이 문서, 예시 줄, 부록 A |
| 빌드 | arduino-esp32 3.3.12, 보드 `ESP32 Dev Module`(`esp32:esp32:esp32`). 저장소 루트의 `DHT-sensor-library`, `Adafruit_Sensor`, `RBD_LightSensor`가 필요하다. 경고 없음, 프로그램 공간 86% |
| 이전 판 | `firmware/env_node/`(0.4.0, 커밋 `1ef7cd4`)는 그대로 남겨 두었다. 앞으로는 `env_module`을 쓴다 |

기획서 5장(환경 모듈과 예비 모듈) 기준이다.

- 예비 WROOM에는 같은 펌웨어를 올리고 시리얼 `id env_02`만 보낸다. NVS에 저장되고 재시작하면 env_02(0x32)로 동작한다.
- 공통 판단 코드와 보드 입출력 코드는 분리했다(기획서 10장).

## 2. 실제 출력 JSON (USB로 나가는 줄 그대로, 각 한 줄)

**실물 WROOM 보드에서 받은 줄이 아니다.** 보드가 아직 없어서, 위 커밋의 펌웨어 소스를 고치지 않고 PC에서 빌드해 돌렸다.
보드의 가상 센서 시나리오를 실행했을 때 USB로 나가는 줄이다. JSON을 만드는 코드(`json_out.cpp`)와 판단·검사·seq 부여 코드는 보드와 같다.
실물 센서를 확인하기 전이라 `source`는 `simulation`이다.

```
{"schema_version":"1.0","packet_type":"environment","node_id":"env_01","boot_id":"boot_1a2b","seq":6,"source":"simulation","uptime_ms":30000,"payload":{"air_temperature_c":24.4,"humidity_pct":52,"light_raw":1930,"heartbeat_interval_ms":30000,"sensor_status":{"dht11":"ok","light":"ok","sound":"ok","flame":"ok","shock":"ok","reed":"ok"},"sound_detected":true,"flame_detected":false,"shock_detected":false,"reed_closed":true},"transport":{"gateway_id":"env_01","route":"simulation","hop_count":0,"relay_id":null,"rssi_dbm":null}}
{"schema_version":"1.0","packet_type":"event","node_id":"env_01","boot_id":"boot_1a2b","seq":61,"source":"simulation","uptime_ms":286000,"payload":{"event_id":"env_01:boot_1a2b:heat_exposure:1","event_type":"heat_exposure","mode":"normal"},"transport":{"gateway_id":"env_01","route":"simulation","hop_count":0,"relay_id":null,"rssi_dbm":null}}
{"schema_version":"1.0","packet_type":"anchor_observation","node_id":"env_01","boot_id":"boot_1a2b","seq":2,"source":"simulation","uptime_ms":5000,"payload":{"anchor_id":"env_01","observed_node_id":"halo_01","observed_boot_id":"boot_00b7","observed_seq":5,"rssi_dbm":-62,"observation_age_ms":0},"transport":{"gateway_id":"env_01","route":"simulation","hop_count":0,"relay_id":null,"rssi_dbm":null}}
```

| 줄 | 상황 |
|---|---|
| `environment` | 가상 시나리오 30초 지점의 큰 소리 감지. 감지라서 바로 보내는 패킷이다. 6개 센서를 모두 보고하고, 열 노출이 아닐 때 보고 주기는 30초 |
| `event` | 공기 온도가 35°C를 넘은 순간(시나리오 약 285초)의 열 노출 주의. 환경 모듈이 만들고, `mode`는 항상 `normal` |
| `anchor_observation` | 앵커 시험 모드에서 A의 가상 병사 방송(`halo_01`)을 관측한 보고. 관측이 가상이라 `simulation`이다 |

앵커 관측 줄은 실제 BLE 스캔에서 나온 것이 아니다. 시험 코드가 가상 병사 방송 수신을 관측 표에 넣었고, 관측 표·보고 순서·JSON은 펌웨어 코드가 만들었다.

검사 결과

| 검사 | 환경 | 열 노출 사건 | 앵커 관측 |
|---|---|---|---|
| C 시험 서버 규격 v1 검사기 | 오류·경고 0 | 오류·경고 0 | 오류·경고 0 |
| 팀장 서버 `core/state.mjs` ingest(`input.mode` = `simulation`) | **받음** | "미등록 병사 노드" | "지원하지 않는 패킷 유형" |
| 같은 ingest(`input.mode` = `device`) | source 불일치(의도) | 〃 | 〃 |

## 3. 연결 방식

펌웨어는 **두 경로로 동시에** 내보낸다. 같은 패킷(같은 `seq`)이 두 경로로 나간다.

| 경로 | 무엇이 나가나 | 지금 상태 |
|---|---|---|
| **① WROOM USB 직결 → PC** | 보낸 패킷마다 규격 v1 JSON 한 줄(115200bps NDJSON). 진단 줄은 기본 꺼짐이라 USB에는 데이터 줄만 나간다 | **지금 연동 기준.** 펌웨어 출력은 PC 시험으로 확인했고, 보드 실물은 미검증 |
| ② BLE 광고 → 게이트웨이(1안 NU40 첫 번째 / 2안 C3) → USB JSON | 같은 패킷을 부록 A 초안 바이트로 비연결 광고(회사 ID 0xFFFF, 공통 머리 11B, 환경 21B·사건 15B·앵커 19B) | 펌웨어에 들어 있음. 게이트웨이의 해석·JSON 변환은 B 담당이고 부록 A는 B 확정 대기 → **미검증** |

- 기획서 3장의 기본 흐름은 ②(환경 노드 방송 → 게이트웨이 → USB JSON)다. ①은 B의 게이트웨이가 준비될 때까지의 연동·시험·예비 경로다.
- 두 경로가 모두 서버에 들어와도 중복 제거 키(`source + node_id + boot_id + seq`)가 같아 두 번째는 중복으로 걸러진다.
- 직결(①)에서는 `transport.gateway_id`가 `env_01`이고 `rssi_dbm`은 `null`이다. 게이트웨이(②)를 거치면 B의 변환에 따라 `gateway_01`과 수신 RSSI가 붙는다.

①로 팀장 서버에 넣는 방법(팀장 서버 코드·설정 변경 없음, 기본 `input.mode` = `simulation`)

| 방법 | 실행 | 비고 |
|---|---|---|
| C 검증 후 전달(권장, 역할 분담대로) | `python pc/server.py --serial COMx --forward-lead http://<팀장 서버>:8080/api/ingest` | C가 규격 검사·중복 제거를 통과한 새 가상 데이터만 넘긴다. VS Code 실행 목록 11번 |
| 팀장 브리지 직접 | `system.json`의 `serial.port` = WROOM COM, `python communication/serial_bridge.py` | 진단 줄이 없어 SKIP 없이 모두 넘어간다 |

## 4. 팀장 서버 확장 때 참고 (요청이 아니라 위 결과에서 나온 것)

| 패킷 | 지금 팀장 서버 | 참고 |
|---|---|---|
| 열 노출 `event` | "미등록 병사 노드" | 환경 노드 사건이다. `node_id` = `env_01`이고 병사 배정이 없으며, SOS 병합 대상이 아니다 |
| `anchor_observation` | "지원하지 않는 패킷 유형" | 규격 9장. 보관 키는 (anchor_id, observed_node_id, source)이고, 관측 시각 = 수신 시각 − `observation_age_ms` |
| 예비 `env_02` | 미등록 | 교체할 때 `environment.node_ids`에 추가 |

## 5. 함께 넣은 파일

| 파일 | 내용 |
|---|---|
| `samples_env_module.ndjson` | 위 세 줄 |
| `virtual_11min.ndjson` | 같은 실행의 11분 전체 144줄(환경 51·열 노출 사건 2·앵커 관측 91). 서버 확장 시험용 |
| `env_module/` (ZIP 안) | 펌웨어 폴더 전체(커밋 `fc7781e`와 같음) |
| `appendix_a_ble.md` (ZIP 안) | BLE 바이트 배치 초안(B 확정 대기) |
