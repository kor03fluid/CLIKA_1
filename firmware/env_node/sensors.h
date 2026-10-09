#pragma once
// 환경 센서: DHT11·조도(필수), 소리·불꽃·충격·리드스위치(추가).
#include <stdint.h>

struct EnvReading {
  bool    dht_ok;
  float   temp_c;
  float   humidity;
  bool    light_ok;
  uint8_t light_pct;
  uint8_t installed;  // ENV_HAS_* (추가 센서)
  uint8_t state;      // ENV_ST_*
  bool    virtual_temp;
};

void sensorsBegin();
void sensorsPoll(uint32_t now);
const EnvReading& sensorsLatest();
uint8_t sensorsPendingEvents();  // 래치된 ENV_EV_* (지우지 않음)
uint8_t sensorsTakeEvents();     // 래치된 ENV_EV_*를 읽고 지움
// 시험용 가상 온도. NAN이면 해제. 설정 중에는 패킷에 PKT_FLAG_VIRTUAL이 붙는다.
void sensorsSetVirtualTemp(float c);
