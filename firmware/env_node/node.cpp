#include "node.h"
#include "config.h"
#include <Preferences.h>
#include <esp_random.h>

static uint16_t s_bootId = 0;
static uint16_t s_seq = 0;

// 새 boot_id를 정해 NVS에 남긴다. 1씩 올려 바로 앞 값과 겹치지 않게 하고, NVS가 비어 있으면
// (첫 부팅·플래시 초기화) 무작위 값에서 시작해 초기화 전에 쓰던 번호와 겹칠 가능성을 줄인다.
static void newBootId() {
  Preferences prefs;
  prefs.begin("envnode", false);
  s_bootId = prefs.isKey("boot") ? prefs.getUShort("boot") + 1 : (uint16_t)esp_random();
  prefs.putUShort("boot", s_bootId);
  prefs.end();
  s_seq = 0;
}

void nodeBegin() { newBootId(); }

uint16_t nodeBootId() { return s_bootId; }

void nodeFillHeader(PktHeader& h, uint8_t type, uint8_t flags) {
  h.ver_type = (PKT_VERSION << 4) | (type & 0x0F);
  h.flags = flags;
  h.node_id = NODE_ID;
  // seq(16bit)가 한 바퀴 돌면 같은 boot에서 번호가 재사용되므로(규격 4장 위반) 새 boot_id로 넘어간다.
  // 서버는 이를 재부팅처럼 새 스트림으로 받는다. 약 6패킷/분이면 일주일 이상 걸린다.
  if (s_seq == 0xFFFF) newBootId();
  h.boot_id = s_bootId;
  h.seq = ++s_seq;
  h.uptime_ms = millis();
}
