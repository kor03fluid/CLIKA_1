// 환경 모듈 펌웨어의 보드 설정(NVS)·원본 식별 시험: settings.cpp·ident.cpp를 키-값 NVS 대체로 빌드한다.
// 같은 펌웨어로 예비 WROOM을 env_02로 바꾸는 흐름과 boot_id·seq 규칙(규격 4장)을 "이름 값" 줄로 낸다.
#include <cstdio>
#include "config.h"
#include "env_logic.h"
#include "settings.h"
#include "ident.h"
#include "Preferences.h"

HostSerial Serial;
uint32_t g_millis = 0;
std::map<std::string, uint32_t> g_nvs_kv;

static void out(const char* name, long v) { printf("%s %ld\n", name, v); }

static void boot() {  // 전원을 다시 넣은 것처럼 NVS에서 읽고 새 부팅을 시작한다
  settingsBegin();
  identBegin();
}

static PktHeader next(uint8_t type, uint8_t flags) {
  PktHeader h = {};
  g_millis += 1000;
  identFillHeader(h, type, flags);
  return h;
}

int main() {
  boot();  // 처음: NVS 비어 있음
  const Settings& s = settings();
  out("first_node", identNodeId());
  out("first_virtual", s.virtual_sensors);
  out("first_use", s.use_mask);
  out("first_anchor", s.anchor);
  out("first_diag", s.diag);
  out("first_boot", identBootId());  // esp_random 대체 → 0x1a2b
  // seq는 종류·출처를 통틀어 하나의 번호열, 1부터
  const uint8_t kinds[][2] = {{PKT_ENVIRONMENT, PKT_FLAG_SIMULATION}, {PKT_EVENT, PKT_FLAG_EVENT | PKT_FLAG_SIMULATION},
                              {PKT_ANCHOR_OBS, 0}, {PKT_ENVIRONMENT, 0}};
  for (int i = 0; i < 4; i++) {
    PktHeader h = next(kinds[i][0], kinds[i][1]);
    printf("seq%d %u %u %u %u\n", i, (unsigned)h.seq, (unsigned)h.boot_id, (unsigned)h.node_id, (unsigned)h.uptime_ms);
  }
  // 65535 다음에는 새 boot_id로(같은 부팅에서 seq 재사용 금지)
  for (int i = 0; i < 65535 - 4; i++) { PktHeader h = {}; identFillHeader(h, PKT_ENVIRONMENT, 0); }
  PktHeader w = next(PKT_ENVIRONMENT, 0);
  out("wrap_seq", w.seq); out("wrap_boot", w.boot_id);

  // 예비 WROOM: 같은 펌웨어에 "id env_02" → 저장, 이번 부팅은 그대로, 재시작 후 env_02
  uint8_t id = 0;
  out("parse_env_02", parseEnvNodeName("env_02", &id) ? id : -1);
  out("parse_env_15", parseEnvNodeName("env_15", &id) ? id : -1);
  out("parse_env_16", parseEnvNodeName("env_16", &id) ? 1 : 0);
  out("parse_env_00", parseEnvNodeName("env_00", &id) ? 1 : 0);
  out("parse_env_2", parseEnvNodeName("env_2", &id) ? 1 : 0);
  out("parse_halo_01", parseEnvNodeName("halo_01", &id) ? 1 : 0);
  out("set_halo", settingsSetNodeId(0x01) ? 1 : 0);
  out("set_env_02", settingsSetNodeId(0x32) ? 1 : 0);
  out("running_after_set", identNodeId());
  out("saved_after_set", settingsSavedNodeId());
  settingsSetUse(DET_SOUND | DET_REED);
  settingsSetVirtual(false);
  settingsSetDiag(true);
  const unsigned before = identBootId();
  boot();
  out("reboot_node", identNodeId());
  out("reboot_boot_next", identBootId() == ((before + 1) & 0xFFFF));
  out("reboot_use", settings().use_mask);
  out("reboot_virtual", settings().virtual_sensors);
  out("reboot_diag", settings().diag);
  PktHeader h = next(PKT_ENVIRONMENT, 0);
  out("reboot_seq", h.seq); out("reboot_header_node", h.node_id);
  // 범위 밖 ID가 NVS에 있으면 기본(env_01)
  g_nvs_kv["node"] = 0x40;
  boot();
  out("bad_nvs_node", identNodeId());
  // 공장 초기화: 설정은 기본으로, 부팅 번호는 남는다
  const unsigned b2 = identBootId();
  settingsFactory();
  boot();
  out("factory_node", identNodeId());
  out("factory_virtual", settings().virtual_sensors);
  out("factory_use", settings().use_mask);
  out("factory_boot_kept", identBootId() == ((b2 + 1) & 0xFFFF));
  return 0;
}
