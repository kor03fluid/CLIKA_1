#pragma once
// 보드 출력(ESP32): 검사 → seq 부여 → BLE 광고(부록 A 바이트) + USB JSON(규격 v1) 한 줄.
// 규격 값 규칙을 어긴 패킷은 내보내지 않는다(seq도 쓰지 않아 서버에 누락으로 보이지 않는다).
// 큐에 자리가 없으면 false(부른 쪽이 다음 루프에서 다시).
#include <stdint.h>
#include "packet.h"

struct OutStats {
  uint32_t lines;          // USB로 낸 규격 JSON 줄 수(= 새 패킷 수)
  uint32_t blocked;        // 검사에서 막은 패킷 수
  const char* last_block;  // 마지막으로 막은 이유
};

bool outEnvironment(PktEnvironment& p, uint8_t flags, uint8_t windows, bool urgent);
bool outEvent(PktEvent& p, uint8_t flags);
bool outAnchorObs(PktAnchorObs& p, uint8_t flags);
const OutStats& outStats();
