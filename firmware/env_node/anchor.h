#pragma once
// 고정 앵커: 병사 노드의 직접 방송을 패시브 스캔해 RSSI를 모으고 묶어서 보고한다.
// 중계(PKT_FLAG_RELAYED) 패킷의 RSSI는 위치 추정에 쓰지 않으므로 버린다.
#include <stdint.h>

struct AnchorStats {
  uint32_t rx_total;          // 스캔에서 본 모든 광고
  uint32_t rx_soldier;        // 받아들인 병사 직접 방송
  uint32_t rx_relayed_skip;   // 중계 패킷이라 버림
  uint32_t table_full_skip;   // 병사 표가 가득 차 버림
  uint32_t reports;           // 보고 패킷 수
  uint32_t queue_full_skip;   // 송신 큐가 가득 차 보고를 미룸
};

void anchorBegin();
void anchorLoop(uint32_t now);
const AnchorStats& anchorStats();
