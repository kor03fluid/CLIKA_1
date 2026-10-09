#include "node.h"
#include "config.h"
#include <Preferences.h>

static uint16_t s_bootId = 0;
static uint16_t s_seq = 0;

void nodeBegin() {
  Preferences prefs;
  prefs.begin("envnode", false);
  s_bootId = prefs.getUShort("boot", 0) + 1;
  prefs.putUShort("boot", s_bootId);
  prefs.end();
}

uint16_t nodeBootId() { return s_bootId; }

void nodeFillHeader(PktHeader& h, uint8_t type, uint8_t flags) {
  h.ver_type = (PKT_VERSION << 4) | (type & 0x0F);
  h.flags = flags;
  h.node_id = NODE_ID;
  h.boot_id = s_bootId;
  h.seq = ++s_seq;
}
