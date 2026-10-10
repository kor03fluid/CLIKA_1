# 환경 모듈 펌웨어 (ESP32 WROOM) — 기획서 5장 "환경 모듈과 예비 모듈"

담당: 팀원 C. 데이터 형식은 **공통 데이터 규격 v1**([`docs/data_spec_v1.md`](../../docs/data_spec_v1.md)),
무선 바이트 배치는 **부록 A 초안**([`docs/appendix_a_ble.md`](../../docs/appendix_a_ble.md), B 확정 대기)을 따른다.
기존 `firmware/env_node/`는 그대로 두고, 5장 요구와 역할 분담에 맞춰 따로 짠 펌웨어다.

**검증 상태**: 가상 데이터 시험과 빌드 검증까지 마쳤다. 실물 센서와 실물 무선은 아직 검증하지 않았다(기획서 10장 표기 규칙).

- 빌드: arduino-esp32 3.3.12, `esp32:esp32:esp32`, 경고 없음, 프로그램 공간 86%.
- 공통 판단 코드(`env_logic`, `anchor_logic`)와 출력 경로(`out`, `ident`, `settings`, `json_out`, `ble_tx`)는 PC에서 그대로 빌드해 시험한다(`pc/tests/test_env_module_contract.py`).
- 가상 센서 보드 11분 시나리오를 돌린 USB 줄을 세 곳에 넣어 본다: 규격 v1 검사기, C 시험 서버, 팀장 서버(`squad-link`) 입력 처리.

## 1. 역할과 데이터 흐름

```
보드 센서 값(기본: 가상) ─> 공통 판단 ─> 보드 검사 ─┬─> BLE 광고(부록 A) ─> 게이트웨이(B) ─> USB JSON
                                                      └─> USB JSON 한 줄(규격 v1) ─> C 시험 서버(검증·중복 제거·로그)
                                                                                     └─> 통과한 가상 데이터만 ─> 팀장 관제 서버
```

| 담당(기획서 10장) | 이 펌웨어에서 |
|---|---|
| C: 환경 펌웨어·앵커 RSSI 수신과 보고·PC 수신·로그 | 이 펌웨어 전체, PC 쪽 검증·전달(`pc/squadlink/forward.py`) |
| B: 무선 패킷·게이트웨이·**앵커 관측 패킷 정의**·USB JSON | 무선 바이트는 `packet.h`(부록 A) 한 곳만 쓴다. B가 확정하면 이 파일만 바꾼다(`env_node`와 같은 파일인지 시험이 확인) |
| A: 병사 노드 | A와 C는 공통 머리(11B)를 같이 쓴다. 앵커는 병사 패킷의 머리만 읽는다 |
| 팀장: 관제·구역 추정 | 서버는 고치지 않는다. 열 노출 사건은 환경 모듈이 만들고 서버는 받기만 한다 |

## 2. 파일 (보드 입출력 코드와 공통 판단 코드를 분리)

| 구분 | 파일 | 내용 |
|---|---|---|
| 공통 판단 (Arduino 없음, PC 시험) | `env_logic.*` | 가상 센서 보드(`VirtualBoard`), 상태 판단(`EnvJudge`), 보고 정책, environment 본문, 내보내기 전 검사, 배선 점검 판정 |
| | `anchor_logic.*` | 광고 판정(중계 제외, 시험 모드 가상 허용), 병사 관측 표, 보고 순서 |
| | `packet.h` | 부록 A 무선 바이트 배치(B 규격) |
| | `json_out.*` | 규격 v1 USB JSON. 데이터 줄은 이 파일만 낸다 |
| 보드 입출력 (ESP32) | `io_sensors.*` | DHT11·ADC·GPIO·인터럽트 읽기, 센싱 태스크와 보고 루프 사이 잠금 |
| | `ble_tx.*` | 광고 송신 큐(사건·감지 우선), 송신량 기록 |
| | `anchor.*` | BLE 패시브 스캔, 관측 보고 |
| | `out.*` | 검사 → seq 부여 → BLE + USB. 검사에 걸리면 내보내지 않는다(seq도 쓰지 않음) |
| | `settings.*` `ident.*` | NVS 설정(노드 ID·데이터 출처·추가 센서·앵커·보고 정책·진단 줄), boot_id·seq |
| | `env_module.ino` | 태스크, 송신 정책 연결, 시리얼 명령, 진단 줄 |

태스크는 세 개다. 센싱(20ms 주기), 보고 루프(정책·광고·앵커 보고·명령), BLE 스캔 콜백(BLE 태스크)이다.
USB 출력은 보고 루프만 쓰므로 JSON 줄이 섞이지 않는다.

## 3. 센서 (5장 표 → 규격 7장)

| 우선순위 | 부품 | 표시와 한계 | JSON | 화면 표시 |
|---|---|---|---|---|
| 필수 | DHT11 | 환경 공기 온도·습도. 체온 대체 불가 | `air_temperature_c`, `humidity_pct`, `sensor_status.dht11`. 3회 연속 실패면 둘 다 `null`·`unavailable` | 공기 온도, 습도 |
| 필수 | 조도 | 상대 밝기. 보정 없이 lux 표시 안 함 | `light_raw` (12bit ADC 원시값) | 조도 (ADC 원시값) |
| 추가 | 소리 한 개 | 큰 소리 이벤트. 총성 판별·dB 제외 | `sound_detected` | 큰 소리 감지 |
| 추가 | 불꽃감지 | 광학 반응 이벤트. 화재 확정 제외 | `flame_detected` | 불꽃 감지 |
| 추가 | 충격 | 설치물 자체의 충격 | `shock_detected` | 설치물 충격 감지 |
| 추가 | 리드 한 개 | 자석 부착 덮개 등의 열림·닫힘 | `reed_closed` (50ms 디바운스) | 리드 닫힘/열림 |

열 노출 주의(`event`, `heat_exposure`)는 공기 온도 35°C 이상에서 만들고, 34°C 이하에서 풀린다. 개인 체온이나 과열 판정이 아니다.
감지(소리·불꽃·충격·리드)는 적응 모드에서 바로 보내고, 같은 패킷을 광고 창 3개로 반복한다(같은 `seq`).

## 4. 데이터 출처: 가상(기본) → 실제

| 모드 | 언제 | 값 | `source` | 보고하는 추가 센서 |
|---|---|---|---|---|
| **가상**(기본, `sensors virtual`) | 실물 센서를 확인하기 전 | 보드가 6개 센서 값을 만든다(아래 시나리오) | `simulation` | 6개 모두 |
| 실제(`sensors real`) | 배선·전압·반응 레벨을 확인한 뒤 | 실제 핀 | `device`(`vtemp` 중에는 `simulation`) | `use`로 켠 것만(기본 없음, 규격 1·12장: 검증 후 적용) |

가상 값도 실제 값과 똑같이 공통 판단, 보고 정책, 보드 검사를 거친다. 가상 시나리오는 10분마다 반복한다(`scenario off`면 기준값만 유지).

| 시각(주기 안) | 구간 | 나오는 것 |
|---|---|---|
| 0s~ | normal | 24°C ±0.4, 습도 50% ±2, 조도 1800 ±150, 리드 닫힘 |
| 30s | sound_pulse | 큰 소리 감지 |
| 60s | shock_pulse | 설치물 충격 감지 |
| 90~100s | reed_open | 리드 열림 → 닫힘 |
| 150~160s | flame | 불꽃 반응(적응 보고 주기 10초) |
| 200~300s | heat_rise | 24 → 37°C. 약 285초에 35°C → `heat_exposure` 사건 |
| 300~360s | heat_hold | 37°C 유지(보고 주기 10초) |
| 360~420s | heat_fall | 37 → 24°C. 약 374초에 34°C → 해제 |
| 480~500s | dht_fail | DHT11 읽기 실패 → 약 6초 뒤 온도·습도 `null`, `dht11: "unavailable"` |
| 520~560s | dark | 조도 원시값 약 200 |

손으로 넣기: `vdetect sound|flame|shock|reed`(가상 모드에서만), `vtemp 38`/`vtemp off`(두 모드 모두, 켜져 있는 동안 `simulation`).

## 5. 보드와 핀 (실물 확인 후 `config.h` 수정)

같은 소스가 두 보드에서 빌드된다. 보드는 빌드할 때 자동으로 골라진다(`ARDUINO_NANO_ESP32`). 부팅 진단 줄의 `board`에 어느 쪽인지 나온다.

| 기능 | ESP32 WROOM DevKit (GPIO) | Arduino Nano ESP32 (보드 인쇄 이름 → GPIO) | 비고 |
|---|---|---|---|
| DHT11 DATA | 4 | **D2** → GPIO5 | 3V3 공급. 모듈에 풀업 없으면 10kΩ |
| 조도(분압 출력) | 34 | **A0** → GPIO1 | ADC1. 12bit 원시값 |
| 소리 DO | 27 | **D3** → GPIO6 | `SOUND_ACTIVE_LEVEL` HIGH |
| 불꽃 DO | 26 | **D4** → GPIO7 | `FLAME_ACTIVE_LEVEL` LOW |
| 충격 DO | 25 | **D5** → GPIO8 | `SHOCK_ACTIVE_LEVEL` HIGH |
| 리드스위치 | 33 | **D6** → GPIO9 | 핀–GND, 내부 풀업 |
| 상태 LED | 2 | **D13**(LED_BUILTIN) → GPIO48 | 광고 창 동안 켜짐 |
| 빌드 보드(FQBN) | `esp32:esp32:esp32` | `esp32:esp32:nano_nora` | 둘 다 arduino-esp32 3.3.12, 경고 없음 |

Nano ESP32 차이:

- ESP32-S3 칩이다. BLE는 NimBLE 스택이고 USB는 칩 자체 USB(CDC)다. 펌웨어가 두 경우를 나눠 처리하며, 데이터 형식과 판단은 같다.
- 3.3V 로직이다. 모듈 VCC는 **3V3** 핀에 연결한다. **VBUS**는 USB 5V이므로 5V 출력 신호를 핀에 넣지 않는다.
- Nano ESP32의 실물 동작은 아직 확인하지 않았다(빌드만 확인).

- 전원은 USB 5V로 넣는다. 모듈 VCC는 보드의 **3V3 핀**에 연결한다(5V·VIN 핀에 연결하지 않음).
- **5V 출력 신호를 GPIO·ADC에 직접 넣지 않는다.** 5V가 꼭 필요한 모듈은 분압(직렬 10kΩ + GND 쪽 20kΩ)이나 레벨 변환을 거친다.
- 만능기판은 배선과 고정용이다. GPIO를 늘리는 칩은 쓰지 않는다(센서 6개를 GPIO 6개에 직결).
- 모듈 전압은 GPIO에 꽂기 전에 멀티미터로 잰다. 측정표는 [`docs/c_sec5_env_module.md`](../../docs/c_sec5_env_module.md) 2절에 있다.
- `check` 명령은 꽂은 뒤 신호가 3.3V 범위에서 정상인지만 본다. 조도 핀 전압, 계속 반응·잡음, DHT11 읽기를 확인한다.

## 6. 시리얼 명령 (115200bps, 줄 끝 Newline)

USB에는 규격 JSON 줄만 나간다(규격 2장). 진단 줄(`# {...}`)은 `diag on`일 때(부팅·경고)와 직접 보낸 명령의 응답일 때만 나간다.

| 명령 | 하는 일 | 저장 |
|---|---|---|
| `help` · `config` · `stats` | 명령 목록 · 설정 · 송신량·수신·오류 기록 | — |
| `check` | 배선 점검(2초): 조도 핀 mV, 핀 반응·잡음, DHT11 | — |
| `id env_02` | 노드 ID 바꾸기(예비 WROOM). 저장 후 재시작해 새 `boot_id`로 시작 | NVS |
| `sensors virtual` · `sensors real` | 데이터 출처(`vsensor on/off`와 같음) | NVS |
| `use sound on` · `use all` · `use none` | 실제 센서 모드에서 보고할 추가 센서 | NVS |
| `anchor on` · `anchor off` | 고정 앵커 역할(스캔·관측 보고) | NVS |
| `anchor test on` · `anchor test off` | A의 가상 방송도 관측(시험 모드, `simulation`으로 보고) | — |
| `mode fixed` · `mode adaptive` | 기준 고정 5초 / 적응 | NVS |
| `diag on` · `diag off` | 진단 줄(시험 보드는 켬) | NVS |
| `scenario` · `scenario on` · `scenario off` | 가상 시나리오 구간 보기 / 켜고 끄기 | — |
| `vdetect …` · `vtemp 38` · `vtemp off` | 손으로 넣는 가상 감지·온도 | — |
| `profile base` · `profile full` | 송신량·전력 비교 구간: 스캔 끔 / 켬. 앞뒤로 `stats`를 자동으로 남긴다 | — |
| `autostats 60` | 60초마다 `stats`(0이면 끔) | — |
| `send` · `reboot` · `factory` | 환경 패킷 바로 보내기 · 재시작 · 설정 초기화(부팅 번호는 유지) | — |

`stats`에는 다음 값이 담긴다. `report.py`와 C 시험 서버가 같은 키를 읽는다.

- 시험 조건: `fw`, `tx_mode`, `anchor_enabled`, `anchor_test`, `vsensor`, `vtemp`, `scenario`, `use`, `profile`
- 송신량: `tx.packets`, `tx.windows`, `tx.window_ms`, `tx.payload_bytes`, 종류별 수(`environment`, `event`, `anchor_observation`, `anchor_bytes`)
- 수신: `anchor.*`
- 오류: `tx.dropped`, `tx.adv_fail`, `out.blocked`, `anchor.scan_restarts`
- 동시 운용: `sense.max_ms`·`sense.overruns`, `loop.max_ms`·`loop.overruns`

송신량 수치는 펌웨어의 논리적 기록이다. 실제 무선 광고 이벤트 수나 RF 방출량으로 부르지 않는다(규격 12장). 그 값은 스니퍼로 잰다.

## 7. USB 출력 예 (가상 데이터, 시험에서 나온 줄 그대로)

```
{"schema_version":"1.0","packet_type":"environment","node_id":"env_01","boot_id":"boot_1a2b","seq":6,"source":"simulation","uptime_ms":30000,"payload":{"air_temperature_c":24.4,"humidity_pct":52,"light_raw":1930,"heartbeat_interval_ms":30000,"sensor_status":{"dht11":"ok","light":"ok","sound":"ok","flame":"ok","shock":"ok","reed":"ok"},"sound_detected":true,"flame_detected":false,"shock_detected":false,"reed_closed":true},"transport":{"gateway_id":"env_01","route":"simulation","hop_count":0,"relay_id":null,"rssi_dbm":null}}
{"schema_version":"1.0","packet_type":"event","node_id":"env_01","boot_id":"boot_1a2b","seq":61,"source":"simulation","uptime_ms":286000,"payload":{"event_id":"env_01:boot_1a2b:heat_exposure:1","event_type":"heat_exposure","mode":"normal"},"transport":{"gateway_id":"env_01","route":"simulation","hop_count":0,"relay_id":null,"rssi_dbm":null}}
{"schema_version":"1.0","packet_type":"environment","node_id":"env_01","boot_id":"boot_1a2b","seq":109,"source":"simulation","uptime_ms":484000,"payload":{"air_temperature_c":null,"humidity_pct":null,"light_raw":1904,"heartbeat_interval_ms":30000,"sensor_status":{"dht11":"unavailable","light":"ok","sound":"ok","flame":"ok","shock":"ok","reed":"ok"},"sound_detected":false,"flame_detected":false,"shock_detected":false,"reed_closed":true},"transport":{"gateway_id":"env_01","route":"simulation","hop_count":0,"relay_id":null,"rssi_dbm":null}}
{"schema_version":"1.0","packet_type":"anchor_observation","node_id":"env_01","boot_id":"boot_1a2b","seq":2,"source":"simulation","uptime_ms":5000,"payload":{"anchor_id":"env_01","observed_node_id":"halo_01","observed_boot_id":"boot_00b7","observed_seq":5,"rssi_dbm":-62,"observation_age_ms":0},"transport":{"gateway_id":"env_01","route":"simulation","hop_count":0,"relay_id":null,"rssi_dbm":null}}
```

팀장 서버 입력 처리 결과(시험): 가상 환경 패킷은 모두 받는다. 열 노출 사건(환경 노드 사건)과 앵커 관측은 팀장 서버가 아직 받지 않는다.
이 두 종류는 팀장이 서버를 확장하기로 했다.

## 8. 빌드·업로드

Arduino IDE 2:

1. 보드 매니저에서 **esp32 by Espressif 3.x**를 설치한다.
2. 라이브러리는 설치하지 않아도 된다. DHT11 읽기는 폴더 안의 `dht_reader.*`(Adafruit DHT sensor library, MIT, `dht_reader_LICENSE.txt`)이고, 조도는 `analogRead`로 읽는다.
3. `firmware/env_module/env_module.ino`를 열고, 보드를 `ESP32 Dev Module`(WROOM) 또는 `Arduino Nano ESP32`(esp32 by Espressif 목록 안)로 골라 업로드한다.

arduino-cli(저장소 루트):

```sh
arduino-cli compile --fqbn esp32:esp32:esp32 \
  firmware/env_module
```

**예비 WROOM**: 같은 펌웨어를 그대로 올린 뒤 시리얼에서 `id env_02`를 보낸다. NVS에 저장되고 재시작하면 `env_02`(0x32)로 동작한다.
소스를 고치지 않는다(5장: 같은 환경 펌웨어를 준비한 교체용). 교체할 때 팀장 서버의 `environment.node_ids`에 `env_02`를 넣는 일은 팀장 서버 설정이다.

## 9. 시험 순서 (실물이 오면)

| 순서 | 할 일 | 확인 |
|---|---|---|
| 1 | 업로드 → `diag on` → `reboot` | 부팅 진단 줄의 `fw":"env_module/1.0.0"`, `vsensor":true`, `reset` |
| 2 | C 시험 서버 + 팀장 서버 전달(VS Code 실행 10·11번) | C 화면에 env_01 "가상", 팀장 화면 "환경 · 위치"에 env_01 |
| 3 | 모듈 전압 측정 → 배선 → `sensors real` → `use …` → `check` | 경고 없음, 단독 확인([`docs/c_hw_test.md`](../../docs/c_hw_test.md) 2절) |
| 4 | 센싱·스캔·보고 동시 10분(`autostats 60`) | `report.py`의 누락 0, `sense.overruns`·`loop.overruns`·`out.blocked` 0 |
| 5 | `profile base` 10분 → `profile full` 10분 + USB 전류계 | 스캔·보고로 늘어난 송신량(`stats`)과 소비전력(V×mA) |
| 6 | 예비 WROOM `id env_02` | 부팅 줄 `node_id":"env_02"` |

## 10. 미해결

- 부록 A(공통 머리·ID 표·`env_02`=0x32·회사 ID·중계기 ID 전달)는 B의 확정을 기다린다. 확정되면 `packet.h`만 바꾼다.
- 팀장 서버의 열 노출 사건·앵커 관측 받기(팀장 확장 예정).
- 조도 `light` 상태의 단선·포화 판정 기준(실물 로그로 정함). 지금은 항상 `ok`이고, `check`가 전압으로 경고한다.
- 실물 센서·무선·전류는 미검증이다.
