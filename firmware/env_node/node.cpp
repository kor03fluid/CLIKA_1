#include "node.h"
#include "config.h"
#include <Preferences.h>
#include <esp_random.h>

static uint16_t s_bootId = 0;
// seq는 출처마다 따로 센다([0] device, [1] simulation). 서버는 출처별 스트림에서 번호가 이어지는지로
// 누락을 세므로, 한 카운터를 같이 쓰면 vtemp 시험 중에 양쪽 모두 가짜 누락이 생긴다.
static uint16_t s_seq[2] = {};

// 새 boot_id를 정해 NVS에 남긴다. 1씩 올려 바로 앞 값과 겹치지 않게 하고, NVS가 비어 있으면
// (첫 부팅·플래시 초기화) 무작위 값에서 시작해 초기화 전에 쓰던 번호와 겹칠 가능성을 줄인다.
static void newBootId() {
  Preferences prefs;
  prefs.begin("envnode", false);
  s_bootId = prefs.isKey("boot") ? prefs.getUShort("boot") + 1 : (uint16_t)esp_random();
  prefs.putUShort("boot", s_bootId);
  prefs.end();
  s_seq[0] = s_seq[1] = 0;
}

void nodeBegin() { newBootId(); }

uint16_t nodeBootId() { return s_bootId; }

void nodeFillHeader(PktHeader& h, uint8_t type, uint8_t flags) {
  h.ver_type = (PKT_VERSION << 4) | (type & 0x0F);
  h.flags = flags;
  h.node_id = NODE_ID;
  uint16_t& seq = s_seq[(flags & PKT_FLAG_SIMULATION) ? 1 : 0];
  // seq(16bit)가 한 바퀴 돌면 같은 boot에서 번호가 재사용되므로(규격 4장 위반) 새 boot_id로 넘어간다.
  // 서버는 이를 재부팅처럼 새 스트림으로 받는다. 약 6패킷/분이면 일주일 이상 걸린다.
  if (seq == 0xFFFF) newBootId();
  h.boot_id = s_bootId;
  h.seq = ++seq;
  h.uptime_ms = millis();
}
