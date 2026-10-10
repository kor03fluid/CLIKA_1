// PC 시험용 NVS(Preferences) 대체: 키 하나("boot")만 메모리에 둔다.
#pragma once
#include <cstdint>
#include <cstring>

struct HostNvs {
  bool has = false;
  uint16_t boot = 0;
};
extern HostNvs g_nvs;

class Preferences {
 public:
  bool begin(const char*, bool) { return true; }
  void end() {}
  bool isKey(const char* key) { return strcmp(key, "boot") == 0 && g_nvs.has; }
  uint16_t getUShort(const char*) { return g_nvs.boot; }
  size_t putUShort(const char*, uint16_t v) {
    g_nvs.has = true;
    g_nvs.boot = v;
    return 2;
  }
};
