# SQUAD LINK 공통 데이터 규격 v1

작성일: 2026년 10월 10일  
규격 버전: `1.0`  
대상: 팀장 신현호, 팀원 A, B, C

이 문서는 착용형 노드, 환경 노드, 게이트웨이, 서버, 관제가 같은 의미로 데이터를 처리하기 위한 팀 공통 구현 기준이다. 앞서 대화에서 정한 필드에 자료형·단위·허용값과 전달 구조를 보완했다. 이 문서의 JSON은 PC로 전달하는 형식이며 BLE 무선 패킷의 바이트 배치를 지정하지 않는다.

## 1. 이번 구현의 범위

- 분대원 8명을 등록한다.
- 병사 01·02에 헤일로팟을 한 개씩 배정한다.
- 병사 03~08은 장치 미배정으로 표시한다. 미배정 인원을 통신 두절이나 정상 측정 인원으로 집계하지 않는다.
- 하드웨어 도착 전에는 가상 노드 두 개로 정상 → 병사 01 SOS → 병사 02 통신 두절을 시험한다.
- 노트북과 휴대폰은 같은 서버 상태를 받는다.
- 체온 실측은 미구현이다. 가상 체온은 시험용으로만 사용한다.
- GPS, 추가 환경센서, 앵커 구역 추정은 해당 기능의 검증 후 적용한다.
- UI 꾸미기는 데이터 연결과 상태 처리 구현 이후 진행한다.

## 2. 전달 구조와 담당 경계

| 담당 | 책임 | 다음 담당에게 전달하는 결과 |
|---|---|---|
| A · 하드웨어/임베디드 | 병사 상태·심박·IMU·SOS·모드 데이터 생성, 센서 상태 처리 | B와 합의한 압축 무선 패킷 |
| B · 무선통신/임베디드 | BLE·중계·게이트웨이, 패킷 해석, 앵커 관측 규격, USB 출력 | 이 문서의 JSON을 한 줄씩 출력 |
| C · 백엔드/IoT | 환경·앵커 수신과 보고, USB JSON 입력, 검증·중복 제거·서버 저장 | 관제용 상태와 사건, 로그 |
| 신현호 · 팀장/프론트엔드 | 관제·PMVP·분대원 등록, 구역 추정과 사건 조작 UI, 통합 | 노트북·휴대폰의 동일한 서버 상태 표시 |

병사·환경 데이터 → BLE 종류별 바이너리 패킷 → 게이트웨이 USB JSON → 서버 상태 처리 → 관제 화면 순서다. 환경 노드의 앵커 관측도 B의 무선 규격을 사용한다.

USB 출력은 **UTF-8 NDJSON**이다. JSON 객체 하나를 한 줄에 출력하고 줄바꿈으로 끝낸다. 아래 여러 줄 예시는 가독성을 위한 표현이다. 실제 출력에서는 한 줄로 직렬화한다. 디버그 문구를 JSON 데이터 스트림에 섞지 않는다.

## 3. 기본 규칙

1. 필드 이름은 영어 `snake_case`를 사용한다. 단위는 필드 이름 또는 이 문서에 명시한다.
2. 측정 불가·미구현 값은 `null`로 표현한다. 심박 `0`, 좌표 `0,0`, 빈 문자열을 측정 불가의 뜻으로 쓰지 않는다.
3. `0`과 `false`는 실제로 측정·판단한 유효값일 수 있다. `null`과 구분한다.
4. `NaN`, `Infinity`는 허용하지 않는다. 숫자로 변환할 수 없는 값은 `null`과 품질 상태로 처리한다.
5. 한 패킷에는 해당 종류의 `payload`만 넣는다. 모든 센서 정보를 매번 전송하지 않는다.
6. 필수 필드는 항상 존재해야 한다. 선택 필드는 생략할 수 있다. 활성화한 선택 필드가 측정되지 않으면 `null`로 보낸다.
7. 예시는 모두 가상 시험 데이터다. 실측 완료나 정확도 검증을 의미하지 않는다.
8. enum은 아래 소문자 값만 사용한다. `정상`, `Normal`, `NORMAL` 등으로 임의 변경하지 않는다.

## 4. JSON 공통 구조

모든 USB 입력 객체는 아래 구조를 사용한다.

| 필드 | 자료형 | 필수 | 의미 |
|---|---|---|---|
| `schema_version` | string | O | 현재 `"1.0"` |
| `packet_type` | string enum | O | 아래 5개 패킷 종류 중 하나 |
| `node_id` | string | O | 원본을 생성한 노드 ID |
| `boot_id` | string | O | 원본 노드의 부팅 식별자 |
| `seq` | integer | O | 해당 부팅 내 원본 패킷 순번. 0 이상 |
| `source` | string enum | O | `device` 또는 `simulation` |
| `uptime_ms` | integer | O | 원본 노드가 패킷을 생성했을 때의 부팅 후 경과 시간, ms |
| `payload` | object | O | 패킷 종류별 내용 |
| `transport` | object | O | 게이트웨이가 추가한 수신 경로 정보 |

### 패킷 종류

| `packet_type` | 목적 | 생성 담당 |
|---|---|---|
| `soldier_status` | 병사 상태와 다음 보고 주기 | A |
| `event` | SOS·충격 등 사건 | A 또는 C |
| `environment` | 설치 지점의 환경 | C |
| `gps` | 선택 기능인 위치 측정 | A |
| `anchor_observation` | 고정 앵커의 병사 직접 수신 RSSI | B·C |

### ID와 원본 식별

| 대상 | ID 예시 |
|---|---|
| 병사 01 장치 | `halo_01` |
| 병사 02 장치 | `halo_02` |
| 환경 노드 | `env_01` |
| 게이트웨이 | `gateway_01` |
| 중계기 | `relay_01` |
| 서버 분대원 | `soldier_01`~`soldier_08` |

- `seq`는 패킷 종류를 통틀어 부팅 내에서 증가시킨다. 같은 부팅에서 재사용하지 않는다.
- 재부팅할 때 `boot_id`를 새로 만든다. 같은 `boot_id`로 `seq`만 초기화하지 않는다.
- 재송신·중계 시 원본 `node_id`, `boot_id`, `seq`, `uptime_ms`, `source`, `payload`를 유지한다.
- 중복 제거 키는 **`source + node_id + boot_id + seq`**다. 실제/가상 데이터가 섞여 같은 원본으로 취급되지 않도록 한다.
- 이전 부팅이나 이전 순번의 지연 패킷으로 최신 병사 상태를 덮어쓰지 않는다. 사건은 별도 사건 ID로 기록한다.
- v1 필드 추가·변경은 B와 C가 함께 확인하고 예시를 갱신한다. 자료형이나 의미가 바뀌면 버전도 변경한다.

### `transport` 구조

| 필드 | 자료형 | 필수 | 의미 |
|---|---|---|---|
| `gateway_id` | string | O | USB 출력 게이트웨이 ID |
| `route` | string enum | O | `direct`, `relay`, `simulation` |
| `hop_count` | integer | O | 직접/가상 0, 1단계 중계 1 |
| `relay_id` | string 또는 null | O | 중계 시 중계기 ID, 그 외 `null` |
| `rssi_dbm` | number 또는 null | O | 게이트웨이가 이번 무선 수신에서 관측한 RSSI. 가상 주입이면 `null` 가능 |

`transport.rssi_dbm`은 중계 경로에서 중계기 신호의 세기다. 병사 위치 추정에 그대로 사용하지 않는다. 병사 위치 추정은 `anchor_observation`의 직접 수신값을 사용한다.

## 5. 병사 상태 `soldier_status`

### `payload` 필드

| 필드 | 자료형 | 필수 | 단위·허용값·규칙 |
|---|---|---|---|
| `mode` | string enum | O | `normal`, `covert` |
| `heart_rate_bpm` | number 또는 null | O | bpm. 품질 `good`일 때만 유효한 측정값 |
| `heart_rate_quality` | string enum | O | `good`, `poor`, `no_contact`, `unavailable` |
| `motion_state` | string enum | O | `moving`, `still`, `unknown` |
| `heartbeat_interval_ms` | integer | O | 현재 노드가 선언하는 정상 보고 주기, ms. 양수 |
| `sensor_status` | object | O | 아래 센서별 상태 |
| `body_temperature_c` | number 또는 null | O | 예약 필드. 현재 실제 노드는 `null` |
| `battery_voltage_v` | number 또는 null | 선택 | V. 전압 측정 회로 구현·검증 후 사용 |

`motion_state`는 움직임 측정 결과다. `still`만으로 쓰러짐·무반응을 확정하지 않는다. 충격은 `event`로 보고하고, 장시간 무움직임 등의 판단에는 지속 시간과 측정 품질을 함께 사용한다.

`sensor_status`에는 `heart_rate`, `imu`, `body_temperature`, `gps` 키를 넣는다. 값은 `ok`, `unavailable`, `not_implemented`, `disabled` 중 하나다.

- 센서 미구현: `not_implemented`.
- 구현했지만 읽기 실패: `unavailable`.
- 선택 기능을 꺼둠: `disabled`.
- 센서 읽기 정상: `ok`. 심박 접촉 품질은 `heart_rate_quality`로 추가 구분한다.
- 심박 품질이 `good`이 아니면 `heart_rate_bpm`은 `null`로 보낸다.
- 실제 체온 센서가 없는 현재 구성은 `body_temperature_c: null`, `body_temperature: "not_implemented"`다.
- 배터리 전압 측정 회로가 없으면 배터리값이나 잔량을 만들어내지 않는다.

### 정상 상태 예시

```json
{
  "schema_version": "1.0",
  "packet_type": "soldier_status",
  "node_id": "halo_01",
  "boot_id": "boot_a1",
  "seq": 1,
  "source": "simulation",
  "uptime_ms": 10000,
  "payload": {
    "mode": "normal",
    "heart_rate_bpm": 78,
    "heart_rate_quality": "good",
    "motion_state": "moving",
    "heartbeat_interval_ms": 10000,
    "sensor_status": {
      "heart_rate": "ok",
      "imu": "ok",
      "body_temperature": "not_implemented",
      "gps": "disabled"
    },
    "body_temperature_c": null
  },
  "transport": {
    "gateway_id": "gateway_01",
    "route": "simulation",
    "hop_count": 0,
    "relay_id": null,
    "rssi_dbm": null
  }
}
```

## 6. 사건 `event`

| `payload` 필드 | 자료형 | 필수 | 의미 |
|---|---|---|---|
| `event_id` | string | O | 사건의 고유 ID |
| `event_type` | string enum | O | `sos`, `impact`, `prolonged_still`, `heat_exposure` |
| `mode` | string enum | O | 발생 당시 `normal` 또는 `covert` |

- SOS 버튼을 새로 누르면 새 `event_id`를 생성한다. 예: `halo_01:boot_a1:sos:1`.
- 동일 사건을 재보고해도 `event_id`는 유지한다. 원본 패킷을 그대로 재송신하면 `seq`도 유지한다. 새 패킷으로 같은 사건을 다시 알리는 경우에는 새 `seq`와 기존 `event_id`를 사용한다.
- 서버는 패킷 중복과 사건 중복을 각각 제거한다. 같은 사건으로 경보 행을 여러 개 만들지 않는다.
- `impact`는 충격 관측이며 부상을 확정하지 않는다. `prolonged_still`은 정해진 지속 조건을 만족한 경우에만 생성한다.
- `heat_exposure`는 환경 열 노출 주의다. 개인 체온 이상이나 개인 과열 진단으로 표시하지 않는다.
- 노드가 보고하는 사건에는 지휘관의 확인·해결 필드를 넣지 않는다.
- 추가 사건 유형은 B·C와 규격을 갱신한 뒤 사용한다.

### SOS 예시

```json
{
  "schema_version": "1.0",
  "packet_type": "event",
  "node_id": "halo_01",
  "boot_id": "boot_a1",
  "seq": 2,
  "source": "simulation",
  "uptime_ms": 12500,
  "payload": {
    "event_id": "halo_01:boot_a1:sos:1",
    "event_type": "sos",
    "mode": "normal"
  },
  "transport": {
    "gateway_id": "gateway_01",
    "route": "simulation",
    "hop_count": 0,
    "relay_id": null,
    "rssi_dbm": null
  }
}
```

## 7. 환경 `environment`

| `payload` 필드 | 자료형 | 필수 | 단위·규칙 |
|---|---|---|---|
| `air_temperature_c` | number 또는 null | O | 공기 온도, °C. 체온 아님 |
| `humidity_pct` | number 또는 null | O | 상대습도, 0~100 % |
| `light_raw` | integer 또는 null | O | ADC 원시값. 센서/보드 설정에 따라 범위 결정. lux로 표시하지 않음 |
| `heartbeat_interval_ms` | integer | O | 환경 노드 정상 보고 주기, ms. 양수 |
| `sensor_status` | object | O | `dht11`, `light` 상태. 병사 센서와 같은 상태 enum 사용 |
| `sound_detected` | boolean 또는 null | 선택 | 임계 조건에 따른 큰 소리 반응. 총성 판별 아님 |
| `flame_detected` | boolean 또는 null | 선택 | 센서 광학 반응. 화재 확정 아님 |
| `shock_detected` | boolean 또는 null | 선택 | 환경 설치물의 충격 |
| `reed_closed` | boolean 또는 null | 선택 | 리드 접점 닫힘 여부 |

추가 센서의 `false`는 유효하게 읽은 비활성 상태이고, `null`은 측정 불가다. 사용할 경우 `sensor_status`에 `sound`, `flame`, `shock`, `reed` 중 해당 키도 추가한다. 설치 지점 이름은 서버에 `env_01`과 연결해 등록한다. 이 값을 모든 병사의 개인 환경 측정값으로 복사하지 않는다.

```json
{
  "schema_version": "1.0",
  "packet_type": "environment",
  "node_id": "env_01",
  "boot_id": "boot_e1",
  "seq": 1,
  "source": "simulation",
  "uptime_ms": 10000,
  "payload": {
    "air_temperature_c": 24.5,
    "humidity_pct": 52,
    "light_raw": 1730,
    "heartbeat_interval_ms": 10000,
    "sensor_status": {"dht11": "ok", "light": "ok"}
  },
  "transport": {
    "gateway_id": "gateway_01",
    "route": "simulation",
    "hop_count": 0,
    "relay_id": null,
    "rssi_dbm": null
  }
}
```

## 8. GPS `gps` 선택 기능

| `payload` 필드 | 자료형 | 필수 | 단위·범위 |
|---|---|---|---|
| `fix_valid` | boolean | O | 위치 측정값의 유효 여부 |
| `latitude_deg` | number 또는 null | O | 위도, -90~90도 |
| `longitude_deg` | number 또는 null | O | 경도, -180~180도 |
| `hdop` | number 또는 null | O | 수신기 제공 품질 지표. 미제공이면 `null` |

`fix_valid: false`일 때 좌표와 `hdop`은 `null`이다. 서버는 과거 유효 위치가 있다면 별도 시각과 함께 보관하고 오래된 위치로 표시한다. 과거 좌표를 새 유효 측정처럼 재전송하지 않는다. 위치 기능을 사용하지 않으면 GPS 패킷을 보내지 않고 병사 상태의 `gps`를 `disabled`로 둔다.

```json
{
  "schema_version": "1.0",
  "packet_type": "gps",
  "node_id": "halo_01",
  "boot_id": "boot_a1",
  "seq": 3,
  "source": "simulation",
  "uptime_ms": 20000,
  "payload": {
    "fix_valid": false,
    "latitude_deg": null,
    "longitude_deg": null,
    "hdop": null
  },
  "transport": {
    "gateway_id": "gateway_01",
    "route": "simulation",
    "hop_count": 0,
    "relay_id": null,
    "rssi_dbm": null
  }
}
```

## 9. 앵커 관측 `anchor_observation` 선택 기능

고정된 환경 노드와 게이트웨이가 병사 방송을 직접 수신한다. 환경 노드는 관측을 보고 패킷으로 전달하고, 게이트웨이의 자체 직접 관측은 같은 JSON 형식으로 PC에 출력한다.

| `payload` 필드 | 자료형 | 필수 | 의미 |
|---|---|---|---|
| `anchor_id` | string | O | 고정 앵커 ID. 원본 `node_id`와 동일 |
| `observed_node_id` | string | O | 직접 수신한 병사 노드 |
| `observed_boot_id` | string | O | 관측한 병사 패킷의 부팅 ID |
| `observed_seq` | integer | O | 관측한 병사 패킷 순번 |
| `rssi_dbm` | number | O | 앵커가 병사 신호를 직접 수신한 RSSI, dBm |
| `observation_age_ms` | integer | O | 관측 이후 보고 생성까지의 경과 시간, ms. 0 이상 |

앵커 보고의 공통 `boot_id`, `seq`, `uptime_ms`는 앵커의 값이다. 병사 패킷 식별자는 `observed_*` 필드에 넣는다.

중계된 병사 패킷으로 앵커 관측을 만들지 않는다. 실제 보고 패킷이 중계기를 거쳐 PC에 도착하는 것은 허용하지만, `payload.rssi_dbm`은 원래 앵커의 직접 관측값을 유지한다. 실제 앵커는 실제 병사 패킷만 관측 대상으로 사용한다. 가상 앵커 예시는 모두 `simulation`으로 표시한다.

```json
{
  "schema_version": "1.0",
  "packet_type": "anchor_observation",
  "node_id": "env_01",
  "boot_id": "boot_e1",
  "seq": 2,
  "source": "simulation",
  "uptime_ms": 10300,
  "payload": {
    "anchor_id": "env_01",
    "observed_node_id": "halo_01",
    "observed_boot_id": "boot_a1",
    "observed_seq": 1,
    "rssi_dbm": -58,
    "observation_age_ms": 300
  },
  "transport": {
    "gateway_id": "gateway_01",
    "route": "simulation",
    "hop_count": 0,
    "relay_id": null,
    "rssi_dbm": null
  }
}
```

同じ病사 패킷의 각 앵커 관측을 비교하면 시간 차이를 줄일 수 있다. 서버는 유효 관측값을 평활화하고 전환 지연을 적용해 추정 구역을 표시한다. 값이 없거나 오래되면 구역 미확보다. 앵커 보고·스캔·송신 증가도 전력·송신량 평가에 포함한다.

## 10. 서버가 관리하는 필드

센서 노드가 아래 필드를 보내도록 요구하지 않는다. C의 서버가 생성·저장하고 관제에 전달한다.

| 필드 | 자료형 | 의미 |
|---|---|---|
| `soldier_id` | string | `soldier_01`~`soldier_08` |
| `assigned_node_id` | string 또는 null | 배정 노드. 병사 03~08은 `null` |
| `source` | string 또는 null | 현재 표시 데이터의 실제/가상 출처. 무자료는 `null` |
| `received_at` | string | 이번 수신의 서버 UTC ISO 8601 시각 |
| `last_seen_at` | string 또는 null | 마지막으로 수용한 새로운 노드 데이터의 수신 시각 |
| `connection_state` | string enum | `unassigned`, `waiting`, `connected`, `lost` |
| `data_stale` | boolean | 측정값을 최신값으로 제시할 수 없는 상태 |
| `estimated_zone_id` | string 또는 null | 유효 앵커로 추정한 구역 |
| `location_updated_at` | string 또는 null | 표시 위치가 갱신된 서버 시각 |
| `event_id` | string | 노드 사건 ID 또는 서버 생성 사건 ID |
| `event_state` | string enum | `open`, `acknowledged`, `resolved` |
| `first_received_at` | string | 사건 최초 수신 시각 |
| `acknowledged_at` | string 또는 null | 지휘관 확인 시각 |
| `resolved_at` | string 또는 null | 지휘관 조치 종료 시각 |

UTC 예시: `2026-10-10T01:49:00Z`. 관제는 한국 시간으로 표시한다. `uptime_ms`를 UTC 발생 시각이라고 표시하지 않는다. 시간 동기화 전에는 사건 최초 수신 시각을 기본으로 보여준다. 통신 두절 경과 계산에는 서버의 단조 증가 시간을 사용해 PC 시계 조정 영향을 줄인다.

### 통신 상태

| `connection_state` | 조건 | 관제 표시 |
|---|---|---|
| `unassigned` | 배정 노드 없음 | 장치 미배정 |
| `waiting` | 배정했지만 유효 상태 패킷을 아직 수신하지 않음 | 연결 대기 |
| `connected` | 유효 신규 데이터가 정해진 시간 내 수신됨 | 연결 |
| `lost` | 마지막 수신 이후 누락 기준 초과 | 통신 두절 |

초기 누락 기준은 서버 설정값으로 아래 공식을 사용한다.

```text
timeout_ms = max(15000, 3 × heartbeat_interval_ms + 2000)
```

이는 팀의 초기 구현 기준이며 실측으로 조정한다. 보고 주기 5초는 17초, 10초는 32초, 30초는 92초 후 두절이다. 시연에서 빠른 전환이 필요하면 가상 노드의 보고 주기를 함께 조정한다. 정상 보고 주기 30초인데 두절을 고정 5초로 판정하지 않는다.

- 현재 보고 주기는 가장 최근 유효 `soldier_status` 또는 `environment`에서 얻는다.
- 신규 직접·중계 패킷은 수신 기록을 갱신한다. 동일 패킷 중복으로 `last_seen_at`을 계속 갱신하지 않는다.
- 앵커 관측이나 지휘관의 사건 확인 조작은 해당 병사 노드의 생존 수신 기록을 갱신하지 않는다.
- 첫 상태 수신 전에는 `waiting`이며, 주기 정보가 없으므로 `lost`로 바로 바꾸지 않는다.
- 전원 OFF인지 무선 장애인지 송신 누락인지 수신만으로 단정하지 않는다.
- 재연결되면 연결 상태와 데이터 최신성을 갱신한다. SOS를 자동으로 해결하지 않는다.
- 서버는 두절 전환마다 사건을 한 번 생성하고 반복 검사로 사건을 추가하지 않는다.

### 사건 확인과 해결

| 동작 | 변화 | 유지할 정보 |
|---|---|---|
| SOS 수신 | `event_state: open` | 원본 사건 ID·발생 노드·최초 수신 시각 |
| 지휘관 확인 | `acknowledged`, 확인 시각 저장 | SOS 활성 사건과 연결 상태 |
| 현장 조치 후 종료 | `resolved`, 조치 종료 시각 저장 | 기록 이력과 별도 측정 상태 |
| 통신 복구 | `connection_state: connected` | SOS 사건 상태 |

사건이 해결됐다는 이유만으로 심박 측정 불가·무움직임·통신 두절을 정상으로 덮어쓰지 않는다. 관제는 측정 상태, 연결 상태, 사건 상태를 별도로 표시한다. 반복 수신된 같은 `event_id`는 확인·해결 상태를 초기화하지 않는다. 새 사건 ID는 새로운 미확인 사건이다.

## 11. 시연 입력과 예상 결과

| 단계 | 입력/조작 | 노트북·휴대폰의 공통 결과 |
|---|---|---|
| 1 정상 | `halo_01`, `halo_02` 상태를 선언한 주기로 전송 | 2명 연결, 가상 시험 표시. 나머지 6명 미배정 |
| 2 SOS | 병사 01 `event_type: sos` 한 사건 생성 | 병사 01 SOS·미확인 사건 표시 |
| 3 확인 | 지휘관이 병사 01 사건 확인 | 확인 시각 표시. SOS 자동 정상화 없음 |
| 4 통신 두절 | 병사 02의 모든 송신 중단 | 누락 기준 이후 병사 02 두절·값 오래됨. 병사 01 SOS 유지 |
| 5 복구 | 병사 02가 신규 상태 전송 | 병사 02 연결 복구. SOS 사건 유지 |
| 6 조치 종료 | 병사 01 사건 종료 | 사건은 이력에 남음. 측정·연결 상태는 각각 유지 |

추가 검증: 중복 수신, 같은 사건의 새 패킷 보고, 재부팅 후 새 `boot_id`, 심박 접촉 해제, GPS 미수신, 앵커 미수신, 일반/기도비닉 상태 표시를 시험한다.

## 12. 구현 우선순위와 인계 체크리스트

### 먼저 구현

1. 공통 헤더·`transport`, `soldier_status`, SOS `event`.
2. NDJSON 입력 검증·중복 제거·분대원 배정·통신 두절·사건 상태 저장.
3. `environment`의 DHT11·조도.
4. 노트북·휴대폰에서 같은 서버 상태 반영.
5. 하드웨어 입력 연결과 일반/기도비닉 검증.

### 선택 기능 검증 후 추가

`gps`, `anchor_observation`, 추가 환경센서, 배터리 전압 측정. 가상 체온 로직은 시험 출처를 유지한다. 송신량 비교 통계는 별도 로그로 준비한다. 서버 수신 수·논리적 송신 호출 수를 실제 무선 광고 이벤트 수나 RF 방출량으로 이름 붙이지 않는다.

### 팀원이 맞춰야 할 항목

- [ ] ID 목록과 `schema_version: "1.0"` 확인
- [ ] 필드 이름·자료형·단위·enum 확인
- [ ] JSON 예시를 각 구현에서 파싱할 수 있는지 확인
- [ ] 측정 불가 `null`과 센서 상태 확인
- [ ] `boot_id` 생성, `seq` 증가와 중복 제거 확인
- [ ] SOS 반복 보고에서 `event_id` 유지 확인
- [ ] 보고 주기와 서버 누락 기준 확인
- [ ] 실제/가상 출처가 변환·중계·관제까지 유지되는지 확인
- [ ] 일반/기도비닉 출력 조건은 노드에서 적용하고 서버 표시와 일치시키기
- [ ] 규격을 바꾸면 B·C·관제 담당에게 동시에 알리고 문서·예시 갱신

각 담당은 이 규격을 기준으로 작업한다. 아직 결정하지 않은 BLE 바이트 배치·구체적인 센서 임계값·서버 API 주소는 구현 담당이 확정한 뒤 같은 문서의 부록 또는 별도 구현 문서로 인계한다.
