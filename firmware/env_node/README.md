# 환경 노드 펌웨어 (ESP32 WROOM)

SQUAD LINK T4-3 환경 노드 뼈대. 담당: 팀원 C.

- DHT11·조도(필수), 소리·불꽃·충격·리드스위치(추가) 측정
- 환경 패킷을 BLE 비연결 광고로 송신. 고정 5초(기준)와 적응 주기를 시리얼 명령으로 전환
- 고정 앵커 역할: 병사 노드의 **직접** 방송을 패시브 스캔해 RSSI를 묶어서 보고. 중계 패킷은 버림
- 송신한 모든 패킷을 USB 시리얼에 JSON 한 줄로 출력(PC 직접 수신·로그·시험용)

**검증 상태: 빌드 검증만 완료** (arduino-esp32 3.3.12, `esp32:esp32:esp32`). 실물 센서·무선 동작은 미검증.

## 파일

| 파일 | 내용 |
|---|---|
| `env_node.ino` | setup/loop, 송신 정책, 시리얼 JSON·명령 |
| `config.h` | 노드 ID, 핀, 임계값, 주기, 광고·스캔 설정 |
| `packet.h` | 공통 패킷 초안 (**팀원 B와 확정 필요**) |
| `node.cpp/.h` | boot_id(NVS 부팅 카운터)·seq |
| `sensors.cpp/.h` | 센서 읽기, 이벤트 래치, 열 노출 판단, 가상 온도 |
| `ble_tx.cpp/.h` | 광고 송신 큐, 송신량 통계 |
| `anchor.cpp/.h` | 병사 RSSI 관측·평활·보고 |

## 핀 (ESP32 DevKit 기준, 실물 확인 후 `config.h` 수정)

| 기능 | GPIO | 비고 |
|---|---|---|
| DHT11 DATA | 4 | 3.3V 공급, 모듈에 풀업 없으면 10kΩ |
| 조도 (분압 출력) | 34 | ADC1 입력 전용. 10bit로 읽음 |
| 소리 DO | 27 | 활성 레벨 `SOUND_ACTIVE_LEVEL` |
| 불꽃 DO | 26 | 활성 레벨 `FLAME_ACTIVE_LEVEL` |
| 충격 DO | 25 | 활성 레벨 `SHOCK_ACTIVE_LEVEL` |
| 리드스위치 | 33 | 핀–GND, 내부 풀업 |
| 상태 LED | 2 | 광고 창 동안 켜짐 |

- 전원은 USB 5V. **5V 출력 신호를 GPIO·ADC에 직접 넣지 않는다.** 모듈은 3.3V로 공급하거나 분압·레벨 변환.
- 디지털 모듈의 활성 레벨(HIGH/LOW)은 모듈마다 다르므로 실물로 확인.
- 추가 센서는 `USE_SOUND` 등을 0으로 끄면 코드에서 제외된다.

## 빌드

Arduino IDE: 보드 매니저에서 **esp32 by Espressif 3.x** 설치 → 보드 `ESP32 Dev Module` → 저장소의
`DHT-sensor-library`, `Adafruit_Sensor`, `RBD_LightSensor` 폴더를 Arduino `libraries`에 복사 → `env_node.ino` 열기.

arduino-cli (저장소 루트에서):

```sh
arduino-cli compile --fqbn esp32:esp32:esp32 \
  --library DHT-sensor-library --library Adafruit_Sensor --library RBD_LightSensor \
  firmware/env_node
```

예비 WROOM은 `NODE_ID`를 `0x32`로 바꿔 빌드한다.

## 패킷 초안 (`packet.h`)

BLE 레거시 광고, 제조사 데이터(회사 ID `0xFFFF` = SIG 시험용) 안에 넣는다. 페이로드 최대 24B, little-endian.

공통 머리 7B: `ver_type`(버전 4bit·종류 4bit) · `flags` · `node_id` · `boot_id`(2B) · `seq`(2B)
- 중복 제거 키는 `node_id + boot_id + seq`. 이벤트 반복 광고는 같은 seq를 쓴다.
- flags: `0x01` 중계됨 · `0x02` 가상 데이터 · `0x04` 이벤트 즉시 송신
- 종류: `1` 병사 상태 · `2` 병사 위치 · `3` 환경 · `4` 앵커 보고

| 종류 | 크기 | 내용 |
|---|---|---|
| 환경 (3) | 14B | 온도×10(int16) · 습도% · 상대 밝기% · valid · events(래치) · state |
| 앵커 보고 (4) | 22B | count + 병사 2명분 × (ID · last_seq · RSSI · RSSI 평균 · 표본 수 · 경과 0.1초) |

병사가 3명 이상이면 앵커 보고를 여러 패킷으로 나눠 보낸다. 앵커는 병사 패킷의 머리만 해석하므로
병사 패킷 본문 형식과 무관하게 동작한다(종류 1·2, 중계 아님 조건만 본다).

## 송신 정책

| 모드 | 동작 |
|---|---|
| `fixed` (기준) | 5초마다 송신. 이벤트는 다음 패킷에 실림 |
| `adaptive` (기본) | 이벤트 즉시(3회 반복, 최소 간격 2초) · 값 변화(온도 1°C·습도 5%·밝기 10%, 최소 3초) · 열 노출/불꽃 상태 중 10초 · 평상시 30초 |

앵커 보고: 새 병사 또는 RSSI 평균 6dB 이상 변화 시 보고(최소 2초), 변화 없어도 15초마다 묶어 보고.
45초 동안 못 받은 병사는 보고에서 빠진다(PC에서 구역 미확보 처리).

`est_adv_events`는 창 길이/광고 간격으로 계산한 **추정치**다. 실제 광고 이벤트 수는 스니퍼 등으로 측정한다.

## 시리얼 (115200bps)

출력 예:

```json
{"type":"env","node":49,"boot":3,"seq":12,"reason":"heartbeat","tx_mode":"adaptive","temp":24.0,"hum":41,"light":63,"valid":63,"events":[],"state":[],"virtual":false,"ms":61234}
{"type":"anchor","anchor":49,"boot":3,"seq":13,"obs":[{"soldier":1,"last_seq":88,"rssi":-61,"rssi_avg":-63,"n":7,"age_ms":400}],"ms":62010}
```

명령(줄 단위):

| 명령 | 동작 |
|---|---|
| `stats` | 송신량·앵커 수신 통계 JSON |
| `mode fixed` / `mode adaptive` | 송신 정책 전환 |
| `vtemp 38` / `vtemp off` | 가상 온도 주입/해제. 주입 중 패킷에 가상 플래그 |
| `send` | 환경 패킷 즉시 1회 송신 |

## 남은 일

- [ ] 팀원 B와 패킷 형식·노드 ID 대역·회사 ID 확정 (`packet.h`, `config.h`)
- [ ] 실물 핀·센서 전압·활성 레벨 확인
- [ ] 조도 단선·포화 판정 기준 (현재 항상 유효)
- [ ] 열 노출 임계값·변화 기준을 센서 로그로 조정
- [ ] 송신 출력(`BLE_TX_POWER`) 실측으로 선정
- [ ] 센싱·스캔·보고 동시 운용 시 수신 누락 시험, 스캔·보고로 늘어난 소비전류·송신량 기록
- [ ] 예비 WROOM에 같은 펌웨어(`NODE_ID 0x32`) 업로드
