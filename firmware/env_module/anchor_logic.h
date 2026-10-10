#pragma once
// 고정 앵커의 공통 판단 코드 (기획서 10장: 보드 입출력과 분리). Arduino·BLE API를 쓰지 않는다.
// 규격 9장: 앵커는 병사 방송을 직접 수신한 RSSI를 보고한다. 중계된 병사 패킷으로 관측을 만들지 않는다.
// 실제 앵커는 실제 병사 패킷만 관측한다. 팀장 지시(가상 시험): 시험 모드에서만 A의 가상(simulation) 원본 방송도
// 관측하고, 그 관측은 simulation으로 보고하며 실제 관측과 따로 보관한다. 중계 제외는 시험 모드에서도 유지한다.
// 무선 바이트 배치는 B의 규격(부록 A, packet.h)을 따른다. 기획서 8장: 앵커 관측은 별도 보고 패킷이며
// 구역 변경(RSSI 변화) 또는 제한된 주기로 묶어서 보낸다.
#include <stddef.h>
#include <stdint.h>
#include "config.h"
#include "packet.h"

enum AdvVerdict : uint8_t {
  ADV_NOT_OURS = 0,    // 회사 ID·버전·길이가 맞지 않음
  ADV_NOT_SOLDIER,     // 병사 노드(0x01~0x1F)의 soldier_status·gps·event가 아님
  ADV_RELAYED,         // 중계된 패킷(flags 0x01) → 관측하지 않음
  ADV_SIM_SKIPPED,     // 가상 원본인데 시험 모드가 꺼져 있음
  ADV_ACCEPT,          // 실제 병사 원본 → 관측
  ADV_ACCEPT_SIM,      // 시험 모드의 가상 병사 원본 → 가상 관측
};

// 스캔에서 받은 제조사 데이터(회사 ID 2B + 페이로드)를 판정한다. 받아들이면 hdr에 머리를 담는다.
AdvVerdict anchorClassify(const uint8_t* md, size_t len, bool testMode, PktHeader* hdr);

struct SoldierObs {
  bool     used;
  uint8_t  id;
  bool     sim;          // 가상 원본 관측(같은 ID라도 실제와 따로)
  uint16_t boot_id;
  uint16_t last_seq;
  int8_t   rssi_last;    // 마지막으로 직접 받은 패킷(last_seq)의 RSSI
  float    rssi_avg;     // 평활값(보고 시점 판단용. 보고하는 값은 rssi_last, 평활은 서버가 한다)
  uint8_t  samples;      // 직전 보고 이후 표본 수
  uint32_t last_ms;
  bool     reported;     // 지금 보이는 동안 보고했는가(사라졌다 돌아오면 false)
  int8_t   reported_avg;
  uint32_t last_report_ms;
};

struct AnchorDue {
  SoldierObs obs;
  uint8_t    rank;    // 0 새로 보임, 1 RSSI 변화, 2 주기
  uint32_t   waited;  // 마지막 보고 후 경과
};

class AnchorTable {
 public:
  void clear();
  void clearSim();  // 시험 모드를 끄면 가상 관측을 지운다
  // false면 표가 가득 차 버림
  bool record(uint8_t id, bool sim, uint16_t boot, uint16_t seq, int rssi, uint32_t now);
  // 보고할 차례인 병사를 우선순위 순으로 담는다(새로 보임 > 변화 > 오래 기다림). 오래 안 보인 병사는 뺀다.
  uint8_t due(uint32_t now, AnchorDue* out, uint8_t max);
  void markReported(const AnchorDue* d, uint8_t n, uint32_t now);
  uint8_t size() const;

 private:
  SoldierObs tab_[ANCHOR_MAX_SOLDIERS] = {};
};

// 관측 하나로 anchor_observation 본문을 채운다(머리는 부르는 쪽이 앵커 자신의 값으로).
// age는 관측부터 이 패킷 생성(uptime_ms)까지. 16bit를 넘으면 65535.
void fillAnchorObs(PktAnchorObs& p, const SoldierObs& o, uint32_t ageMs);

// now가 then보다 앞서면(다른 태스크가 더 늦은 시각을 기록) 0으로 본다
inline uint32_t elapsedMs(uint32_t now, uint32_t then) {
  int32_t d = (int32_t)(now - then);
  return d > 0 ? (uint32_t)d : 0;
}
