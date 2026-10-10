#pragma once
// BLE 비연결 광고 송신. 패킷 하나를 짧은 광고 창(TX_WINDOW_MS) 동안 내보내고 멈춘다.
#include <stdint.h>

struct TxStats {
  uint32_t packets;         // 새 패킷 수(seq 기준)
  uint32_t windows;         // 광고 창 수(반복 포함)
  uint32_t est_adv_events;  // 추정 광고 이벤트 수(창 길이 / 광고 간격). 실측은 스니퍼로
  uint32_t payload_bytes;   // 새 패킷 페이로드 합
  uint32_t dropped;         // 큐 가득 참
};

void bleTxBegin();
// windows: 같은 내용을 광고할 창 수(이벤트 반복). false면 큐가 가득 차 버려짐
bool bleTxQueue(const uint8_t* payload, uint8_t len, uint8_t windows);
void bleTxLoop(uint32_t now);
uint8_t bleTxFree();  // 큐에 남은 칸 수
const TxStats& bleTxStats();
