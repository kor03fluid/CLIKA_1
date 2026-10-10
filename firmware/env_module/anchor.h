#pragma once
// 보드 입출력(ESP32 BLE): 고정 앵커 스캔과 관측 보고. 판정·보고 순서는 anchor_logic(공통 코드)이 한다.
// 5장: 고정 앵커 역할에서는 병사 방송을 스캔해 직접 수신 RSSI를 보고한다. 앵커 관측의 무선 형식은 B의 규격(부록 A).
#include <stdint.h>

struct AnchorStats {
  uint32_t rx_total;            // 스캔에서 본 모든 광고
  uint32_t rx_soldier;          // 받아들인 병사 직접 방송(실제 + 시험 모드 가상)
  uint32_t rx_relayed_skip;     // 중계 패킷이라 버림
  uint32_t rx_simulation_skip;  // 가상 원본인데 시험 모드가 꺼져 있어 버림
  uint32_t rx_simulation;       // 시험 모드에서 받아들인 가상 병사 원본
  uint32_t table_full_skip;     // 병사 표가 가득 차 버림
  uint32_t reports;             // 관측 보고 패킷 수(병사 하나당 하나)
  uint32_t queue_full_skip;     // 송신 큐 자리가 모자라 보고를 미룬 횟수(미룬 묶음당 1)
  uint32_t scan_restarts;       // 끝 알림 없이 멈춘 스캔을 다시 시작한 횟수
};

void anchorBegin();
void anchorLoop(uint32_t now);
// 스캔·보고 켜고 끄기. 끄면 스캔을 멈추고 병사 표를 비운다. 다시 켜면 처음 본 병사처럼 보고한다.
void anchorSetEnabled(bool on);
bool anchorEnabled();
// 시험 모드(팀장 지시): A의 가상 센서 보드처럼 simulation 표시가 있는 병사 원본 방송도 관측해 simulation 관측으로
// 보고한다. 실제·가상 관측은 따로 보관. 중계 패킷은 시험 모드에서도 관측하지 않는다. 끄면 가상 관측을 지운다.
void anchorSetTestMode(bool on);
bool anchorTestMode();
const AnchorStats& anchorStats();
