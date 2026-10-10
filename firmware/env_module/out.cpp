#include "out.h"
#include "config.h"
#include "env_logic.h"
#include "ident.h"
#include "json_out.h"
#include "ble_tx.h"

static OutStats s_stats = {};

// 검사용 임시 머리: seq를 쓰기 전에 본문과 머리 규칙을 확인한다
static void probeHeader(PktHeader& h, uint8_t type, uint8_t flags) {
  h = {};
  h.ver_type = (PKT_VERSION << 4) | (type & 0x0F);
  h.flags = flags;
  h.node_id = identNodeId();
  h.seq = 1;
}

static bool blocked(const char* why) {
  if (!why) return false;
  s_stats.blocked++;
  s_stats.last_block = why;
  return true;
}

bool outEnvironment(PktEnvironment& p, uint8_t flags, uint8_t windows, bool urgent) {
  if (bleTxFree() == 0) return false;
  probeHeader(p.h, PKT_ENVIRONMENT, flags);
  if (blocked(checkEnvironment(p, identNodeId()))) return true;  // 버림(다시 시도해도 같으므로 보낸 것으로 친다)
  identFillHeader(p.h, PKT_ENVIRONMENT, flags);
  bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), windows, urgent);  // 자리는 위에서 확인
  printEnvironmentJson(p);
  s_stats.lines++;
  return true;
}

bool outEvent(PktEvent& p, uint8_t flags) {
  if (bleTxFree() == 0) return false;
  probeHeader(p.h, PKT_EVENT, flags);
  if (blocked(checkEvent(p, identNodeId()))) return true;
  identFillHeader(p.h, PKT_EVENT, flags);
  bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), EVENT_REPEATS, true);
  printEventJson(p);
  s_stats.lines++;
  return true;
}

bool outAnchorObs(PktAnchorObs& p, uint8_t flags) {
  if (bleTxFree() == 0) return false;
  probeHeader(p.h, PKT_ANCHOR_OBS, flags);
  if (blocked(checkAnchorObs(p, identNodeId()))) return true;
  identFillHeader(p.h, PKT_ANCHOR_OBS, flags);
  bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), 1);
  printAnchorObsJson(p);
  s_stats.lines++;
  return true;
}

const OutStats& outStats() { return s_stats; }
