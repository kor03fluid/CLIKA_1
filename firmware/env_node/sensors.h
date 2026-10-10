#pragma once
// 환경 센서: DHT11·조도(필수), 소리·불꽃·충격·리드스위치(추가).
#include <stdint.h>

// 직전 환경 보고 이후 감지(래치). sound/flame/shock_detected, 리드 변화
#define DET_SOUND 0x01
#define DET_FLAME 0x02
#define DET_SHOCK 0x04
#define DET_REED  0x08

struct EnvReading {
  bool     dht_ok;       // 실제 DHT11 읽기 성공
  float    temp_c;       // 공기 온도(가상 온도 시험 중이면 그 값). 없으면 NAN
  float    humidity;     // 실제 측정값만. 없으면 NAN(가상으로 지어내지 않음)
  bool     light_ok;
  uint16_t light_raw;    // ADC 12bit 원시값
  bool     heat;         // 환경 열 노출 주의 상태(공기 온도 기준, 개인 체온 아님)
  bool     flame_now;    // 불꽃 센서 현재 반응
  bool     reed_closed;  // 리드 접점 닫힘
  bool     virtual_temp; // 가상 온도 시험 중 → 패킷 source "simulation"
};

void sensorsBegin();
void sensorsPoll(uint32_t now);
const EnvReading& sensorsLatest();
uint8_t sensorsPendingDetections();  // DET_* (지우지 않음)
uint8_t sensorsTakeDetections();     // DET_*를 읽고 지움
bool sensorsTakeHeatOnset();         // 열 노출 주의가 새로 시작됐으면 true(한 번만)
// 시험용 가상 온도. NAN이면 해제.
void sensorsSetVirtualTemp(float c);
