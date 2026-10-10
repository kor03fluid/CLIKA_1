// 환경 노드 송신 큐 시험: ble_tx.cpp로 패킷을 넣고 광고 창이 나간 순서를 출력한다.
// pc/tests/test_firmware_contract.py가 빌드·실행해 사건·감지 패킷이 앞서는지 확인한다.
#include <cstdio>
#include <string>
#include "ble_tx.h"
#include "BLEDevice.h"

HostSerial Serial;
BLEAdvertising g_adv;
uint32_t g_millis = 0;

static void put(char id, uint8_t windows, bool urgent) {
  uint8_t b = (uint8_t)id;
  if (!bleTxQueue(&b, 1, windows, urgent)) printf("drop %c\n", id);
}

static void runFor(uint32_t ms) {
  for (uint32_t end = g_millis + ms; g_millis < end; g_millis += 10) bleTxLoop(g_millis);
}

static void dump(const char* name) {
  std::string order;
  for (auto& md : g_adv.started) order += md[2];  // 앞 2바이트는 회사 ID
  printf("%s %s\n", name, order.c_str());
  g_adv.started.clear();
}

int main() {
  bleTxBegin();
  // 1) 광고 중인 A는 끊지 않고, 뒤에 쌓인 일반 B·C 앞에 사건 U(3회)가 들어간다
  put('A', 1, false);
  bleTxLoop(g_millis);
  put('B', 1, false);
  put('C', 1, false);
  put('U', 3, true);
  runFor(10000);
  dump("active");
  // 2) 아직 광고 전이면 맨 앞. 먼저 들어온 사건 순서는 지킨다
  put('X', 1, false);
  put('V', 2, true);
  put('W', 1, true);
  runFor(10000);
  dump("idle");
  // 3) 큐 6칸이 차면 버린다
  for (char c = 'a'; c < 'a' + 7; c++) put(c, 1, false);
  runFor(10000);
  dump("full");
  // 4) 광고 시작 실패는 창으로 세지 않고 같은 패킷을 다시 보낸다
  const TxStats before = bleTxStats();
  g_adv.fail_starts = 2;
  put('F', 1, false);
  runFor(10000);
  dump("fail");
  const TxStats& s = bleTxStats();
  printf("stats adv_fail=%lu windows=%lu dropped=%lu\n", (unsigned long)(s.adv_fail - before.adv_fail),
         (unsigned long)(s.windows - before.windows), (unsigned long)s.dropped);
  return 0;
}
