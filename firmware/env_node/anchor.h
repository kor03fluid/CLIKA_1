#pragma once
// 고정 앵커: 병사 노드의 직접 방송을 패시브 스캔해 RSSI를 모으고 묶어서 보고한다.
// 중계(PKT_FLAG_RELAYED) 패킷의 RSSI는 위치 추정에 쓰지 않으므로 버린다.
#include <stdint.h>

struct AnchorStats {
  uint32_t rx_total;          // 스캔에서 본 모든 광고
  uint32_t rx_soldier;        // 받아들인 병사 직접 방송
  uint32_t rx_relayed_skip;   // 중계 패킷이라 버림
  uint32_t rx_simulation_skip; // 가상(시험) 병사 패킷이라 버림
  uint32_t table_full_skip;   // 병사 표가 가득 차 버림
  uint32_t reports;           // 관측 보고 패킷 수(병사 하나당 하나)
  uint32_t queue_full_skip;   // 송신 큐 자리가 모자라 보고를 미룬 횟수(미룬 묶음당 1)
  uint32_t scan_restarts;     // 끝 알림 없이 멈춘 스캔을 다시 시작한 횟수
};

void anchorBegin();
void anchorLoop(uint32_t now);
// 실행 중 스캔·보고 켜고 끄기(시리얼 "anchor on|off"). 스캔으로 늘어난 전류·송신량 비교 시험용.
// 끄면 스캔을 멈추고 병사 표를 비운다. 다시 켜면 처음 본 병사처럼 보고한다.
void anchorSetEnabled(bool on);
bool anchorEnabled();
const AnchorStats& anchorStats();
