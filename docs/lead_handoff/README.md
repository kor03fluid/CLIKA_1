# C → 팀장: 환경 노드·앵커 연동 자료

기준 2026-10-10 · 팀장 코드 `SQUAD_LINK_step1.zip` 확인 후 작성.

**펌웨어 기준 커밋**: `kor03fluid/CLIKA_1` `main` **`1ef7cd429cd92df99c340db61b798bcef5d64d65`** (`1ef7cd4`), 펌웨어 판 `fw` = `0.4.0`.
`env_node_src/`는 이 커밋의 `firmware/env_node/`를 그대로 담은 것이다(Arduino 스케치 폴더, 빌드 방법은 그 안의 README).

## 1. 요청하신 자료

| 파일 | 내용 |
|---|---|
| `packet.h` | 환경 노드가 지금 쓰는 무선 규격(BLE 패킷 정의, 초안 v2). `env_node_src/packet.h`와 같음 |
| `env_node_src/` | 위 커밋의 환경 노드 펌웨어 소스 전체 |
| `samples_device.ndjson` | JSON 원문 한 줄씩: ① `environment` ② 열 노출 사건 `event` ③ `anchor_observation` (실측, `source: "device"`) |
| `samples_simulation.ndjson` | 같은 세 줄의 가상판(`vtemp` 시험·앵커 시험 모드, `source`·`route` = `"simulation"`). 개발 서버가 simulation 모드라 바로 넣어 볼 수 있음 |
| `anchor_receive_reference.py` | C 시험 서버의 기존 `anchor_observation` 수신 코드 발췌(검사·보관·화면 출력)와 규칙 요약 |
| `appendix_a_ble.md` | 공통 규격 부록 A 초안(BLE 바이트 배치·숫자 ID·JSON 변환). B와 확정 중 |

세 예시 줄은 모두 환경 노드 펌웨어의 실제 JSON 출력 코드(`json_out.cpp`)를 PC에서 빌드해 만든 것이다. 아래는 같은 줄을
생략 없이 펼친 것이다(USB로는 한 줄 NDJSON으로 나간다).

### 환경 (`environment`, 실측)

```json
{
  "schema_version": "1.0",
  "packet_type": "environment",
  "node_id": "env_01",
  "boot_id": "boot_1a2b",
  "seq": 140,
  "source": "device",
  "uptime_ms": 812400,
  "payload": {
    "air_temperature_c": 36.2,
    "humidity_pct": 41,
    "light_raw": 2210,
    "heartbeat_interval_ms": 10000,
    "sensor_status": {
      "dht11": "ok",
      "light": "ok",
      "sound": "ok",
      "flame": "ok",
      "shock": "ok",
      "reed": "ok"
    },
    "sound_detected": false,
    "flame_detected": false,
    "shock_detected": false,
    "reed_closed": true
  },
  "transport": {
    "gateway_id": "env_01",
    "route": "direct",
    "hop_count": 0,
    "relay_id": null,
    "rssi_dbm": null
  }
}
```

### 환경 열 노출 사건 (`event`, `heat_exposure`, 실측)

```json
{
  "schema_version": "1.0",
  "packet_type": "event",
  "node_id": "env_01",
  "boot_id": "boot_1a2b",
  "seq": 141,
  "source": "device",
  "uptime_ms": 812450,
  "payload": {
    "event_id": "env_01:boot_1a2b:heat_exposure:1",
    "event_type": "heat_exposure",
    "mode": "normal"
  },
  "transport": {
    "gateway_id": "env_01",
    "route": "direct",
    "hop_count": 0,
    "relay_id": null,
    "rssi_dbm": null
  }
}
```

### 앵커 관측 (`anchor_observation`, 실측)

```json
{
  "schema_version": "1.0",
  "packet_type": "anchor_observation",
  "node_id": "env_01",
  "boot_id": "boot_1a2b",
  "seq": 142,
  "source": "device",
  "uptime_ms": 813100,
  "payload": {
    "anchor_id": "env_01",
    "observed_node_id": "halo_01",
    "observed_boot_id": "boot_3c41",
    "observed_seq": 208,
    "rssi_dbm": -61,
    "observation_age_ms": 420
  },
  "transport": {
    "gateway_id": "env_01",
    "route": "direct",
    "hop_count": 0,
    "relay_id": null,
    "rssi_dbm": null
  }
}
```

가상판(`samples_simulation.ndjson`)은 `source`·`transport.route`가 `"simulation"`이고, 가상 센서 모드라 습도 50%,
앵커 관측은 시험 모드에서 A의 가상 방송을 관측한 것이다. 그 밖의 필드 구성은 같다.

## 2. 확정·반영한 것

| 항목 | 내용 |
|---|---|
| 열 노출 사건 | 환경 노드가 만들고 서버는 받기만 한다. 공기 온도 35°C 이상 생성, 34°C 이하 해제. `event_id` = `env_01:boot_xxxx:heat_exposure:<번호>`, `mode`는 항상 `normal` |
| 가상 패킷 `route` | 가상(`source: "simulation"`) 패킷은 `route: "simulation"`으로 바꿨다. 이전에는 `direct`라서 팀장 서버 입력 검사에 걸렸다 |
| `vtemp` 중 습도 | DHT11 실측이 없으면 가상 습도 50%로 채우고 `dht11: "ok"`(팀장 서버의 "dht11 ok ↔ 온습도 모두 숫자" 규칙) |
| 센서 없는 시험 | 시리얼 `vsensor on`이면 DHT11·조도가 가상값, 추가 센서는 `vdetect`로만 감지를 넣는다. 켜져 있는 동안 모든 환경 패킷·사건은 `source: "simulation"`. 부팅·`stats` 진단 줄에 `fw`·`vsensor`·`vtemp`·`anchor_test`가 나와 시험 조건을 남긴다 |
| 앵커 시험 모드 | 시리얼 `anchor test on`이면 가상 표시가 있는 병사 원본 방송(A의 가상 센서 BLE)도 관측해 `source: "simulation"` 관측으로 보고한다. 실제·가상 관측은 따로 보관. 중계 패킷 제외는 유지. `anchor test off`로 끄면 가상 관측을 지움. 기본은 꺼짐 |
| `seq` | 부팅 안에서 패킷 종류·실측/가상을 통틀어 하나의 번호열(팀장 서버의 노드 단위 순서 검사와 맞음) |

## 3. 팀장 서버(`core/state.mjs` `ingest`)에 넣어 본 결과

| 줄 | `input.mode=device` | `input.mode=simulation` | 필요한 서버 확장 |
|---|---|---|---|
| `environment` 실측 | 받음 | source 불일치(의도) | — |
| `environment` 가상(`vtemp`) | source 불일치(의도) | 받음 | — |
| 열 노출 `event` | "미등록 병사 노드" | "미등록 병사 노드" | 환경 노드(`environment.node_ids`)의 `heat_exposure` 사건 받기 |
| `anchor_observation` | "지원하지 않는 패킷 유형" | "지원하지 않는 패킷 유형" | 규격 9장 수신(참고: `anchor_receive_reference.py`) |
| `environment` `env_02` | "미등록 환경 노드" | 〃 | 예비 노드를 쓸 때 `environment.node_ids`에 `env_02` 추가 |

## 4. 서버 확장 때 참고할 점

- **환경 노드 사건**: 환경 노드는 병사가 아니므로 사건 `node_id`는 `env_01`이고 `soldier_id`가 없다. SOS 병합 대상이 아니다(종류가 `heat_exposure`).
- **앵커 관측**: 노드의 연결·최신값·출처 선택을 바꾸지 않는다. 보관 키 `(anchor_id, observed_node_id, source)`, 관측 시각 = 수신 시각 − `observation_age_ms`, 더 최근 관측이 있으면 버림. 앵커 노드의 `seq`로 중복·순서를 거른다(관측마다 `seq`가 다름).
- **출처와 입력 모드**: 환경 노드는 `vtemp` 시험 중 실측·가상 패킷을 한 번호열로 섞어 보낸다(앵커 관측은 실측). 서버가 한 출처만 받으면, 받지 않는 출처의 번호가 순번 공백(`sequence_gap_observed`)으로 보일 수 있다. 손실이 아니다.
- **진단 줄**: 환경 노드의 `# {...}` 줄은 장치 진단이다. 브리지가 `SKIP: invalid NDJSON`으로 넘기면 정상이다.
- **USB 포트 두 개**: 환경 노드 USB와 게이트웨이 USB를 같이 쓰려면 브리지를 포트마다 하나씩 켜야 한다. 지금 `serial_bridge.py`는 `config/system.json`의 `serial.port` 하나만 연다. 예를 들어 `--port` 인자를 두면 같은 설정으로 두 개를 띄울 수 있다(팀장 판단).
- **송신 순서**: 사건·감지 패킷은 환경 노드 송신 큐에서 일반 패킷보다 먼저 나간다. BLE 경로에서는 낮은 `seq`가 나중에 도착할 수 있다(`out_of_order`로 버려도 그 값은 이미 더 새 패킷으로 반영됨). USB 직결 경로는 `seq` 순서대로다.

## 5. B와 확정 중 (부록 A)

공통 머리 11B·종류 값·플래그, 숫자 ID 표(`env_02` = `0x32` 제안), 회사 ID(`0xFFFF` 시험용 유지), 중계기 ID 전달 방법, `soldier_status`·`gps` 본문.
확정되면 `appendix_a_ble.md`를 공통 규격 문서의 부록 A로 넣는 것을 제안한다.
