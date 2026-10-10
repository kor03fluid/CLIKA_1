#pragma once
// 보드 입출력 코드(ESP32 WROOM): 센서 읽기와 가상 센서 보드. 판단은 env_logic(EnvJudge)이 한다.
// sensorsPoll은 센싱 태스크에서, 나머지는 보고 루프에서 부른다. 두 태스크가 같이 쓰는 값은 안에서 잠근다.
//
// 데이터 출처
//   가상(기본): 실물 센서를 확인하기 전. VirtualBoard가 6개 센서 값을 만들고 패킷은 source "simulation"
//   실제: 센서를 연결·확인한 뒤 "sensors real". 켠 추가 센서(use)만 보고한다
#include <stdint.h>
#include "env_logic.h"

struct IoSensorStats {
  uint32_t polls;         // 센싱 횟수
  uint32_t dht_reads;     // DHT11 읽기(가상 포함)
  uint32_t dht_fails;     // 그중 실패
  uint32_t sound_edges;   // 실제 핀 반응 펄스 수(인터럽트)
  uint32_t flame_edges;
  uint32_t shock_edges;
  uint16_t light_mv;      // 점검 요청 때 조도 핀 전압 평균(mV)
  uint32_t light_mv_seq;  // 점검 결과가 나올 때마다 1씩
};

void sensorsBegin(bool virtualMode, uint8_t realUse);
void sensorsPoll(uint32_t now);  // 센싱 태스크

EnvReading sensorsLatest();  // 복사본
uint8_t sensorsPendingDetections();
uint8_t sensorsTakeDetections();
bool sensorsTakeHeatOnset(bool* simulated);

void sensorsSetVirtualMode(bool on);  // 가상 ↔ 실제 센서
bool sensorsVirtualMode();
void sensorsSetRealUse(uint8_t mask); // 실제 센서 중 켤 추가 센서(가상 모드에서는 6개 모두)
uint8_t sensorsRealUse();
void sensorsSetVirtualTemp(float c);  // 시리얼 "vtemp". NAN이면 해제
float sensorsVirtualTemp();
bool sensorsInject(uint8_t det);      // 가상 모드에서만(실측 패킷에 가상 감지를 섞지 않는다)
void sensorsSetScenario(bool on);
bool sensorsScenario();
const char* sensorsScenarioPhase();

void sensorsRequestLightMv();  // 점검: 다음 센싱에서 조도 핀 전압을 잰다(ADC는 센싱 태스크만 쓴다)
IoSensorStats sensorsStats();
uint8_t sensorsDhtFailRun();
