#include "settings.h"
#include "config.h"
#include "env_logic.h"
#include <Preferences.h>
#include <stdlib.h>
#include <string.h>

#define NVS_NS "envmod"

static Settings s_set = {};
static uint8_t s_savedNodeId = DEFAULT_NODE_ID;

bool validEnvNodeId(uint8_t id) { return id >= 0x31 && id <= 0x3F; }

bool parseEnvNodeName(const char* s, uint8_t* id) {
  if (strncmp(s, "env_", 4) != 0) return false;
  const char* d = s + 4;
  if (!(d[0] >= '0' && d[0] <= '9' && d[1] >= '0' && d[1] <= '9' && d[2] == '\0')) return false;  // 두 자리
  int n = (d[0] - '0') * 10 + (d[1] - '0');
  if (n < 1 || n > 15) return false;
  *id = (uint8_t)(0x30 + n);
  return true;
}

static void defaults(Settings& s) {
  s.node_id = DEFAULT_NODE_ID;
  s.virtual_sensors = DEFAULT_VIRTUAL;
  s.use_mask = DEFAULT_USE_MASK & DET_ALL;
  s.anchor = DEFAULT_ANCHOR;
  s.adaptive = DEFAULT_ADAPTIVE;
  s.diag = DEFAULT_DIAG;
}

void settingsBegin() {
  defaults(s_set);
  Preferences p;
  p.begin(NVS_NS, true);
  uint8_t id = p.getUChar("node", DEFAULT_NODE_ID);
  if (validEnvNodeId(id)) s_set.node_id = id;
  s_set.virtual_sensors = p.getUChar("virtual", s_set.virtual_sensors) != 0;
  s_set.use_mask = p.getUChar("use", s_set.use_mask) & DET_ALL;
  s_set.anchor = p.getUChar("anchor", s_set.anchor) != 0;
  s_set.adaptive = p.getUChar("adaptive", s_set.adaptive) != 0;
  s_set.diag = p.getUChar("diag", s_set.diag) != 0;
  p.end();
  s_savedNodeId = s_set.node_id;
}

const Settings& settings() { return s_set; }

static void putU8(const char* key, uint8_t v) {
  Preferences p;
  p.begin(NVS_NS, false);
  p.putUChar(key, v);
  p.end();
}

bool settingsSetNodeId(uint8_t id) {
  if (!validEnvNodeId(id)) return false;
  putU8("node", id);
  s_savedNodeId = id;  // s_set.node_id(지금 부팅의 ID)는 재시작 때 바뀐다
  return true;
}

uint8_t settingsSavedNodeId() { return s_savedNodeId; }

void settingsSetVirtual(bool on) {
  s_set.virtual_sensors = on;
  putU8("virtual", on);
}

void settingsSetUse(uint8_t mask) {
  s_set.use_mask = mask & DET_ALL;
  putU8("use", s_set.use_mask);
}

void settingsSetAnchor(bool on) {
  s_set.anchor = on;
  putU8("anchor", on);
}

void settingsSetAdaptive(bool on) {
  s_set.adaptive = on;
  putU8("adaptive", on);
}

void settingsSetDiag(bool on) {
  s_set.diag = on;
  putU8("diag", on);
}

void settingsFactory() {
  Preferences p;
  p.begin(NVS_NS, false);
  p.remove("node");
  p.remove("virtual");
  p.remove("use");
  p.remove("anchor");
  p.remove("adaptive");
  p.remove("diag");
  p.end();
  uint8_t current = s_set.node_id;
  defaults(s_set);
  s_savedNodeId = s_set.node_id;
  s_set.node_id = current;  // 지금 부팅의 ID는 재시작 때 바뀐다
}
