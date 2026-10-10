// 환경 노드 boot_id·seq 시험: node.cpp로 머리를 채우고 "출처 boot seq uptime"을 한 줄씩 출력한다.
// pc/tests/test_firmware_contract.py가 빌드·실행해 출처마다 seq가 이어지는지 확인한다.
#include <cstdio>
#include "node.h"
#include "Preferences.h"

HostSerial Serial;
HostNvs g_nvs;
uint32_t g_millis = 0;

static void emit(uint8_t flags) {
  PktHeader h = {};
  g_millis += 1000;
  nodeFillHeader(h, PKT_ENVIRONMENT, flags);
  printf("%s %04x %u %u\n", (h.flags & PKT_FLAG_SIMULATION) ? "simulation" : "device", h.boot_id,
         (unsigned)h.seq, (unsigned)h.uptime_ms);
}

int main() {
  nodeBegin();  // NVS 비어 있음 → 무작위 시작(0x1a2b)
  // 실측과 vtemp(가상) 패킷이 섞여도 출처마다 1, 2, 3 ...
  const uint8_t mix[] = {0, 0, PKT_FLAG_SIMULATION, 0, PKT_FLAG_SIMULATION | PKT_FLAG_EVENT,
                         PKT_FLAG_EVENT, PKT_FLAG_SIMULATION};
  for (uint8_t f : mix) emit(f);
  // 실측 seq를 65535까지 채운 뒤(지금 4) 다음 패킷 → 새 boot_id, 두 출처 모두 1부터
  for (int i = 0; i < 65535 - 4; i++) {
    PktHeader h = {};
    nodeFillHeader(h, PKT_ENVIRONMENT, 0);
  }
  emit(0);
  emit(PKT_FLAG_SIMULATION);
  // 재부팅: NVS 값 + 1
  nodeBegin();
  emit(0);
  return 0;
}
