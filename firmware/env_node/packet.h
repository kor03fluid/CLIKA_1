#pragma once
// 공통 패킷 초안. 형식은 팀원 B(패킷 정의)와 확정하며 A·C가 같은 정의를 사용한다.
// BLE 레거시 광고 31B 중 Flags(3B)와 제조사 데이터 머리(길이·타입·회사 ID 4B)를 빼면
// 페이로드는 최대 24B. 모든 다바이트 필드는 little-endian.
#include <stdint.h>

#define PKT_COMPANY_ID  0xFFFF  // Bluetooth SIG 시험용 ID. 제품용 ID 아님
#define PKT_VERSION     1
#define PKT_MAX_PAYLOAD 24

enum PacketType : uint8_t {
  PKT_SOLDIER_STATUS = 0x1,
  PKT_SOLDIER_POS    = 0x2,
  PKT_ENV            = 0x3,
  PKT_ANCHOR_REPORT  = 0x4,
};

// PktHeader.flags
#define PKT_FLAG_RELAYED 0x01  // 중계기가 재방송함. 이 패킷의 RSSI는 위치 추정에 쓰지 않음
#define PKT_FLAG_VIRTUAL 0x02  // 가상(시험) 데이터
#define PKT_FLAG_EVENT   0x04  // 이벤트로 인한 즉시 송신

// 원본 식별·중복 제거 키: node_id + boot_id + seq. 반복 광고는 같은 seq를 쓴다.
struct __attribute__((packed)) PktHeader {
  uint8_t  ver_type;  // 상위 4bit 버전, 하위 4bit PacketType
  uint8_t  flags;
  uint8_t  node_id;
  uint16_t boot_id;
  uint16_t seq;
};

inline uint8_t pktVersion(const PktHeader& h) { return h.ver_type >> 4; }
inline uint8_t pktType(const PktHeader& h) { return h.ver_type & 0x0F; }

// ----- 환경 패킷 (PKT_ENV) -----
// valid: 센서 설치·유효
#define ENV_OK_DHT    0x01
#define ENV_OK_LIGHT  0x02
#define ENV_HAS_SOUND 0x04
#define ENV_HAS_FLAME 0x08
#define ENV_HAS_SHOCK 0x10
#define ENV_HAS_REED  0x20
// events: 직전 환경 패킷 이후 발생(래치)
#define ENV_EV_SOUND 0x01  // 큰 소리. 총성 판별 아님
#define ENV_EV_FLAME 0x02  // 광학 반응. 화재 확정 아님
#define ENV_EV_SHOCK 0x04  // 설치물 자체 충격
#define ENV_EV_REED  0x08  // 덮개 열림·닫힘 변화
#define ENV_EV_HEAT  0x10  // 열 노출 주의 시작
// state: 송신 시점 상태
#define ENV_ST_HEAT      0x01
#define ENV_ST_FLAME     0x02
#define ENV_ST_REED_OPEN 0x04

#define ENV_TEMP_INVALID  INT16_MIN
#define ENV_BYTE_INVALID  0xFF

struct __attribute__((packed)) PktEnv {
  PktHeader h;
  int16_t temp_c10;   // 공기 온도 ×10. 체온 대체 불가
  uint8_t humidity;   // %RH
  uint8_t light_pct;  // 상대 밝기 0~100. 보정 전이라 lux 아님
  uint8_t valid;
  uint8_t events;
  uint8_t state;
};

// ----- 앵커 관측 보고 (PKT_ANCHOR_REPORT) -----
// 병사 노드의 직접 방송(중계 아님)을 이 앵커가 수신한 결과.
// 수신 시각은 시계 동기가 없으므로 송신 시점 기준 경과 시간으로 보낸다.
struct __attribute__((packed)) AnchorEntry {
  uint8_t  soldier_id;
  uint16_t last_seq;   // 마지막으로 직접 수신한 패킷 seq
  int8_t   rssi_last;  // dBm
  int8_t   rssi_avg;   // dBm, EMA
  uint8_t  samples;    // 직전 보고 이후 수신 횟수(255 포화)
  uint8_t  age_ds;     // 마지막 수신 후 경과, 0.1초 단위(255 = 25.5초 이상)
};

#define ANCHOR_ENTRIES_PER_PKT 2

struct __attribute__((packed)) PktAnchorReport {
  PktHeader   h;
  uint8_t     count;
  AnchorEntry e[ANCHOR_ENTRIES_PER_PKT];
};

static_assert(sizeof(PktHeader) == 7, "header size");
static_assert(sizeof(PktEnv) <= PKT_MAX_PAYLOAD, "env packet too large");
static_assert(sizeof(PktAnchorReport) <= PKT_MAX_PAYLOAD, "anchor packet too large");
