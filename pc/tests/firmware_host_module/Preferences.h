// PC 시험용 NVS(Preferences) 대체(환경 모듈 펌웨어): 이름공간 하나를 키-값 표로 메모리에 둔다.
#pragma once
#include <cstdint>
#include <map>
#include <string>

extern std::map<std::string, uint32_t> g_nvs_kv;

class Preferences {
 public:
  bool begin(const char*, bool) { return true; }
  void end() {}
  bool isKey(const char* key) { return g_nvs_kv.count(key) > 0; }
  bool remove(const char* key) { return g_nvs_kv.erase(key) > 0; }
  uint8_t getUChar(const char* key, uint8_t def = 0) { return isKey(key) ? (uint8_t)g_nvs_kv[key] : def; }
  size_t putUChar(const char* key, uint8_t v) { g_nvs_kv[key] = v; return 1; }
  uint16_t getUShort(const char* key, uint16_t def = 0) { return isKey(key) ? (uint16_t)g_nvs_kv[key] : def; }
  size_t putUShort(const char* key, uint16_t v) { g_nvs_kv[key] = v; return 2; }
};
