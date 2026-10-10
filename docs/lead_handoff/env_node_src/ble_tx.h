#pragma once
// BLE 비연결 광고 송신. 패킷 하나를 짧은 광고 창(TX_WINDOW_MS) 동안 내보내고 멈춘다.
#include <stdint.h>

struct TxStats {
  uint32_t packets;         // 새 패킷 수(seq 기준)
  uint32_t windows;         // 광고 창 수(반복 포함)
  uint32_t est_adv_events;  // 추정 광고 이벤트 수(창 길이 / 광고 간격). 실측은 스니퍼로
  uint32_t payload_bytes;   // 새 패킷 페이로드 합
  uint32_t dropped;         // 큐 가득 참
  uint32_t adv_fail;        // 광고 시작 실패(창으로 세지 않고 잠시 뒤 다시 시도)
};

void bleTxBegin();
// windows: 같은 내용을 광고할 창 수(이벤트 반복). false면 큐가 가득 차 버려짐.
// urgent(사건·감지): 이미 큐에 있는 일반 패킷(앵커 보고·주기 환경) 앞에 넣는다. 지금 광고 중인 것과
// 먼저 들어온 urgent 패킷의 순서는 지킨다. 서버는 늦게 나간 낮은 seq를 지연 패킷으로 처리한다.
bool bleTxQueue(const uint8_t* payload, uint8_t len, uint8_t windows, bool urgent = false);
void bleTxLoop(uint32_t now);
uint8_t bleTxFree();  // 큐에 남은 칸 수
const TxStats& bleTxStats();
