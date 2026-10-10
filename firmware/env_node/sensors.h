#pragma once
// 환경 센서: DHT11·조도(필수), 소리·불꽃·충격·리드스위치(추가).
#include <stdint.h>

// 직전 환경 보고 이후 감지(래치). sound/flame/shock_detected, 리드 변화
#define DET_SOUND 0x01
#define DET_FLAME 0x02
#define DET_SHOCK 0x04
#define DET_REED  0x08

struct EnvReading {
  bool     dht_ok;       // DHT11 값 있음(가상 시험 중이면 가상값으로 채움)
  float    temp_c;       // 공기 온도(가상 시험 중이면 가상값). 없으면 NAN
  float    humidity;     // 습도. 실측이 없으면 NAN, 가상 시험 중이면 가상값
  bool     light_ok;
  uint16_t light_raw;    // ADC 12bit 원시값
  bool     heat;         // 환경 열 노출 주의 상태(공기 온도 기준, 개인 체온 아님)
  bool     flame_now;    // 불꽃 센서 현재 반응
  bool     reed_closed;  // 리드 접점 닫힘
  bool     simulated;       // 가상 시험 중(vtemp 또는 가상 센서 모드) → 패킷 source "simulation"
  bool     virtual_sensors; // 가상 센서 모드(모든 센서 값이 가상)
};

void sensorsBegin();
void sensorsPoll(uint32_t now);
const EnvReading& sensorsLatest();
uint8_t sensorsPendingDetections();  // DET_* (지우지 않음)
uint8_t sensorsTakeDetections();     // DET_*를 읽고 지움
bool sensorsTakeHeatOnset();         // 열 노출 주의가 새로 시작됐으면 true(한 번만)
// 시험용 가상 온도. NAN이면 해제.
void sensorsSetVirtualTemp(float c);
// 가상 센서 모드(시리얼 "vsensor on|off"): 센서가 없을 때 DHT11·조도는 가상값, 추가 센서는 실제 핀을 읽지 않고
// sensorsInjectDetection으로만 감지를 넣는다. 켜져 있는 동안 모든 환경 패킷·사건은 source "simulation".
void sensorsSetVirtualSensors(bool on);
bool sensorsVirtualSensors();
float sensorsVirtualTemp();  // vtemp 값, 없으면 NAN
// 가상 감지 넣기(DET_*). 가상 센서 모드에서만 받는다(false면 무시). DET_REED는 리드 열림·닫힘을 바꾼다.
bool sensorsInjectDetection(uint8_t det);
