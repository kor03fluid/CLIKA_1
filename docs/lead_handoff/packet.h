#pragma once
// BLE 무선 패킷 초안 v2. 바이트 배치는 팀원 B가 확정한다(공통 규격 v1은 PC로 가는 JSON만 정함).
// 부록 A 초안: docs/appendix_a_ble.md (오프셋·숫자 ID·JSON 변환·확정할 것)
// 게이트웨이는 이 바이너리를 docs/data_spec_v1.md의 JSON으로 바꾼다. 변환표는 README 참고.
// BLE 레거시 광고 31B 중 Flags(3B)와 제조사 데이터 머리(4B)를 빼면 페이로드 최대 24B. little-endian.
#include <stdint.h>

#define PKT_COMPANY_ID  0xFFFF  // Bluetooth SIG 시험용 ID. 제품용 ID 아님
#define PKT_VERSION     2
#define PKT_MAX_PAYLOAD 24

enum PacketType : uint8_t {   // JSON packet_type
  PKT_SOLDIER_STATUS = 0x1,   // soldier_status (A·B)
  PKT_GPS            = 0x2,   // gps (A·B)
  PKT_ENVIRONMENT    = 0x3,   // environment
  PKT_ANCHOR_OBS     = 0x4,   // anchor_observation
  PKT_EVENT          = 0x5,   // event
};

// PktHeader.flags
#define PKT_FLAG_RELAYED    0x01  // 중계기가 재방송 → transport.route "relay". 이 RSSI는 위치 추정에 쓰지 않음
#define PKT_FLAG_SIMULATION 0x02  // source·route "simulation" (없으면 "device"). 앵커는 시험 모드에서만 관측
#define PKT_FLAG_EVENT      0x04  // 즉시 송신(반복 광고)

// 원본 식별·중복 제거: source + node_id + boot_id + seq. 반복 광고·중계는 같은 머리를 그대로 쓴다.
struct __attribute__((packed)) PktHeader {
  uint8_t  ver_type;   // 상위 4bit 버전, 하위 4bit PacketType
  uint8_t  flags;
  uint8_t  node_id;    // 숫자 ID → 문자열 node_id (README 변환표)
  uint16_t boot_id;    // 부팅마다 새 값. JSON boot_id = "boot_%04x"
  uint16_t seq;        // 부팅 내 순번(모든 종류·출처 공통, 재사용 없음). 65535에 이르면 새 boot_id
  uint32_t uptime_ms;  // 패킷 생성 시 부팅 후 경과 ms → JSON uptime_ms
};

inline uint8_t pktVersion(const PktHeader& h) { return h.ver_type >> 4; }
inline uint8_t pktType(const PktHeader& h) { return h.ver_type & 0x0F; }

// 센서 상태 2bit 값 (JSON sensor_status)
enum SensorState : uint8_t { SS_OK = 0, SS_UNAVAILABLE = 1, SS_NOT_IMPLEMENTED = 2, SS_DISABLED = 3 };
// 선택 boolean 2bit 값
enum TriBool : uint8_t { TB_FALSE = 0, TB_TRUE = 1, TB_OMIT = 2, TB_NULL = 3 };

// ----- 환경 (PKT_ENVIRONMENT) -----
// sensor_status 2bit 위치
#define ENV_SS_DHT11 0
#define ENV_SS_LIGHT 2
#define ENV_SS_SOUND 4
#define ENV_SS_FLAME 6
#define ENV_SS_SHOCK 8
#define ENV_SS_REED  10
// detected 2bit 위치 (TB_OMIT이면 JSON에서 필드와 sensor_status 키를 모두 뺀다)
#define ENV_DT_SOUND 0
#define ENV_DT_FLAME 2
#define ENV_DT_SHOCK 4
#define ENV_DT_REED_CLOSED 6

#define ENV_TEMP_NULL  INT16_MIN
#define ENV_HUM_NULL   0xFF
#define ENV_LIGHT_NULL 0xFFFF

struct __attribute__((packed)) PktEnvironment {
  PktHeader h;
  int16_t  air_temp_c10;   // 공기 온도 ×10 → air_temperature_c. 체온 아님
  uint8_t  humidity_pct;   // → humidity_pct
  uint16_t light_raw;      // ADC 원시값(12bit) → light_raw. lux 아님
  uint16_t heartbeat_s;    // 선언한 정상 보고 주기(초) → heartbeat_interval_ms = ×1000
  uint16_t sensor_status;  // 2bit × 6 (ENV_SS_*)
  uint8_t  detected;       // 2bit × 4 (ENV_DT_*)
};

// ----- 사건 (PKT_EVENT) -----
enum EventType : uint8_t { EV_SOS = 1, EV_IMPACT = 2, EV_PROLONGED_STILL = 3, EV_HEAT_EXPOSURE = 4 };
enum Mode : uint8_t { MODE_NORMAL = 0, MODE_COVERT = 1 };

struct __attribute__((packed)) PktEvent {
  PktHeader h;
  uint8_t  event_type;  // EventType
  uint8_t  mode;        // Mode
  uint16_t event_no;    // JSON event_id = "<node_id>:<boot_id>:<event_type>:<event_no>"
};

// ----- 앵커 관측 (PKT_ANCHOR_OBS) -----
// 병사 노드의 직접 방송(중계·가상 아님)을 이 앵커가 받은 결과. 패킷 하나에 관측 하나
// (JSON에서 관측마다 앵커의 seq가 달라야 중복 제거에 걸리지 않는다).
struct __attribute__((packed)) PktAnchorObs {
  PktHeader h;
  uint8_t  observed_node;  // → observed_node_id
  uint16_t observed_boot;  // → observed_boot_id
  uint16_t observed_seq;   // → observed_seq
  int8_t   rssi_dbm;       // 그 패킷의 직접 수신 RSSI → rssi_dbm
  uint16_t age_ms;         // 관측 후 보고 생성까지 → observation_age_ms
};

static_assert(sizeof(PktHeader) == 11, "header size");
static_assert(sizeof(PktEnvironment) <= PKT_MAX_PAYLOAD, "environment packet too large");
static_assert(sizeof(PktEvent) <= PKT_MAX_PAYLOAD, "event packet too large");
static_assert(sizeof(PktAnchorObs) <= PKT_MAX_PAYLOAD, "anchor packet too large");
