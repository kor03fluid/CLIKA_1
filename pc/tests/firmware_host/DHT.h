// PC 시험용 DHT 대체: 시험이 정한 값을 돌려준다(NAN이면 읽기 실패).
#pragma once
#include <cmath>
#define DHT11 11
extern float g_dht_temp, g_dht_hum;
class DHT {
 public:
  DHT(int, int) {}
  void begin() {}
  float readTemperature() { return g_dht_temp; }
  float readHumidity() { return g_dht_hum; }
};
