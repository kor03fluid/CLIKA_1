#include "ident.h"
#include "settings.h"
#include "json_out.h"
#include <Preferences.h>
#include <esp_random.h>

static uint8_t s_nodeId = 0x31;
static uint16_t s_bootId = 0;
static uint16_t s_seq = 0;

// 새 boot_id를 정해 NVS에 남긴다. 1씩 올려 바로 앞 값과 겹치지 않게 하고, NVS가 비어 있으면
// (첫 부팅·플래시 초기화) 무작위 값에서 시작해 초기화 전에 쓰던 번호와 겹칠 가능성을 줄인다.
static void newBootId() {
  Preferences p;
  p.begin("envmod", false);
  s_bootId = p.isKey("boot") ? p.getUShort("boot") + 1 : (uint16_t)esp_random();
  p.putUShort("boot", s_bootId);
  p.end();
  s_seq = 0;
}

void identBegin() {
  s_nodeId = settings().node_id;
  newBootId();
}

uint8_t identNodeId() { return s_nodeId; }

uint16_t identBootId() { return s_bootId; }

void identName(char* out, size_t len) { nodeName(s_nodeId, out, len); }

void identFillHeader(PktHeader& h, uint8_t type, uint8_t flags) {
  h.ver_type = (PKT_VERSION << 4) | (type & 0x0F);
  h.flags = flags;
  h.node_id = s_nodeId;
  // seq(16bit)가 한 바퀴 돌면 같은 boot에서 번호가 재사용되므로 새 boot_id로 넘어간다(서버는 재부팅처럼 받는다).
  if (s_seq == 0xFFFF) newBootId();
  h.boot_id = s_bootId;
  h.seq = ++s_seq;
  h.uptime_ms = millis();
}
