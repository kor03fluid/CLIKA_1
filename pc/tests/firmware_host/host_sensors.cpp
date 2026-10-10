// 환경 노드 센서 처리 시험: sensors.cpp로 실측·vtemp·가상 센서 모드를 돌려 "단계 키=값 ..."을 한 줄씩 출력한다.
// pc/tests/test_firmware_contract.py가 빌드·실행해 확인한다.
#include <cstdio>
#include "config.h"
#include "sensors.h"

HostSerial Serial;
uint32_t g_millis = 0;
int g_pin_level[64] = {};
void (*g_isr[64])() = {};
float g_dht_temp = NAN, g_dht_hum = NAN;
int g_light_raw = 3333;  // 센서 없는 ADC 핀이 아무 값이나 읽는 상황

static void run(uint32_t ms) {  // 10ms마다 poll
  for (uint32_t end = g_millis + ms; g_millis < end; g_millis += 10) sensorsPoll(g_millis);
}

static void dump(const char* step) {
  const EnvReading& r = sensorsLatest();
  printf("%s dht_ok=%d temp=%.1f hum=%.1f light=%u heat=%d onset=%d sim=%d vsensor=%d reed=%d det=%u\n", step,
         r.dht_ok, isnan(r.temp_c) ? -999.0 : r.temp_c, isnan(r.humidity) ? -999.0 : r.humidity, r.light_raw,
         r.heat, sensorsTakeHeatOnset(), r.simulated, r.virtual_sensors, r.reed_closed, sensorsTakeDetections());
}

int main() {
  g_pin_level[PIN_REED] = LOW;  // 리드 닫힘(풀업, 자석 붙음)
  g_pin_level[PIN_FLAME] = !FLAME_ACTIVE_LEVEL;
  sensorsBegin();
  run(10000);
  dump("nosensor");                       // DHT 없음 → 측정 불가, 조도는 떠 있는 값
  sensorsSetVirtualSensors(true);
  run(3000);
  g_isr[PIN_SOUND]();                     // 떠 있는 핀의 잡음 펄스
  run(100);
  dump("vsensor");                        // 가상값, 잡음 감지 무시
  printf("inject_off=%d\n", sensorsInjectDetection(DET_SOUND) ? 1 : 0);  // 켜져 있으니 1
  run(100);
  dump("vdetect_sound");
  sensorsInjectDetection(DET_REED);
  run(100);
  dump("vdetect_reed");                   // 리드 열림으로 바뀜
  sensorsSetVirtualTemp(38.0f);
  run(3000);
  dump("vtemp38");                        // 가상 열 노출 시작
  sensorsSetVirtualSensors(false);
  run(3000);
  dump("vsensor_off_vtemp_on");           // vtemp만 남음: 여전히 가상, 습도는 가상(실측 없음)
  sensorsSetVirtualTemp(NAN);
  run(3000);
  dump("all_off");                        // 실측으로 복귀, 가상 열 노출 상태는 버림
  printf("inject_device=%d\n", sensorsInjectDetection(DET_SOUND) ? 1 : 0);  // 실측 중에는 0
  // 실측이 이미 더울 때 vtemp: 가상 사건이 따로 생기고, 끝나면 실측 상태로 돌아가 사건이 또 생기지 않음
  g_dht_temp = 36.0f; g_dht_hum = 40.0f;
  run(3000);
  dump("real36");
  sensorsSetVirtualTemp(38.0f);
  run(3000);
  dump("real36_vtemp38");
  sensorsSetVirtualTemp(NAN);
  run(3000);
  dump("real36_back");
  // DHT 가끔 실패: 2번 연속은 직전 값 유지, 3번째에 측정 불가
  g_dht_temp = NAN;
  run(DHT_READ_MS * 2);
  dump("dht_fail2");
  run(DHT_READ_MS);
  dump("dht_fail3");
  return 0;
}
