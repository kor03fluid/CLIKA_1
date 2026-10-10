#include "io_sensors.h"
#include "config.h"
#include <Arduino.h>
#include <DHT.h>
#include <RBD_LightSensor.h>

static DHT s_dht(PIN_DHT, DHT11);
static RBD::LightSensor* s_light = nullptr;

// ----- 두 태스크(센싱·보고)가 같이 쓰는 값: s_lock 안에서만(잠금 안에서는 계산·복사만, 입출력 없음) -----
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static EnvJudge s_judge;
static VirtualBoard s_vboard;
static bool s_virtual = true;
static uint8_t s_realUse = 0;
static bool s_refresh = true;  // 다음 센싱에서 DHT·조도를 바로 읽는다(출처가 바뀐 직후)
static bool s_lightMvRequest = false;
static IoSensorStats s_stats = {};

// ----- 센싱 태스크만 쓰는 값 -----
static bool s_dhtEver = false;
static bool s_lightEver = false;
static uint32_t s_lastDhtMs = 0;
static uint32_t s_lastLightMs = 0;

// ----- 소리·불꽃·충격은 짧은 펄스라 인터럽트로 래치한다(실제 센서일 때만) -----
static portMUX_TYPE s_isrMux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint8_t s_isrDet = 0;
static volatile uint32_t s_isrEdges[3] = {0, 0, 0};
static uint8_t s_attached = 0;  // 인터럽트를 붙인 센서(보고 루프에서만 바꾼다)

static void IRAM_ATTR isrLatch(uint8_t bit, uint8_t i) {
  portENTER_CRITICAL_ISR(&s_isrMux);
  s_isrDet |= bit;
  s_isrEdges[i] = s_isrEdges[i] + 1;
  portEXIT_CRITICAL_ISR(&s_isrMux);
}
static void IRAM_ATTR isrSound() { isrLatch(DET_SOUND, 0); }
static void IRAM_ATTR isrFlame() { isrLatch(DET_FLAME, 1); }
static void IRAM_ATTR isrShock() { isrLatch(DET_SHOCK, 2); }

static int edgeFor(int activeLevel) { return activeLevel == HIGH ? RISING : FALLING; }

// 실제 핀을 읽는 켠 센서에만 인터럽트를 붙인다. 가상 모드나 꺼진 센서의 떠 있는 핀 잡음이 감지·부담이 되지 않게.
static void applyInterrupts(uint8_t want) {
  struct Pin { uint8_t bit; uint8_t pin; void (*fn)(); int level; };
  static const Pin pins[] = {
    {DET_SOUND, PIN_SOUND, isrSound, SOUND_ACTIVE_LEVEL},
    {DET_FLAME, PIN_FLAME, isrFlame, FLAME_ACTIVE_LEVEL},
    {DET_SHOCK, PIN_SHOCK, isrShock, SHOCK_ACTIVE_LEVEL},
  };
  for (const Pin& p : pins) {
    const bool on = want & p.bit, was = s_attached & p.bit;
    if (on && !was) attachInterrupt(digitalPinToInterrupt(p.pin), p.fn, edgeFor(p.level));
    else if (!on && was) detachInterrupt(digitalPinToInterrupt(p.pin));
  }
  s_attached = want & (DET_SOUND | DET_FLAME | DET_SHOCK);
  portENTER_CRITICAL(&s_isrMux);
  s_isrDet &= s_attached;
  portEXIT_CRITICAL(&s_isrMux);
}

void sensorsBegin(bool virtualMode, uint8_t realUse) {
  analogReadResolution(12);  // light_raw는 12bit 원시값(0~4095)
  s_dht.begin();
  s_light = new RBD::LightSensor(PIN_LIGHT);  // getRawValue()만 쓴다(백분율 계산은 10bit 기준이라 안 씀)
  pinMode(PIN_SOUND, INPUT);
  pinMode(PIN_FLAME, INPUT);
  pinMode(PIN_SHOCK, INPUT);
  pinMode(PIN_REED, INPUT_PULLUP);
  const uint32_t now = millis();
  s_virtual = virtualMode;
  s_realUse = realUse & DET_ALL;
  s_vboard.begin(now);
  s_judge.begin(s_virtual ? DET_ALL : s_realUse, s_virtual, now);
  applyInterrupts(s_virtual ? 0 : s_realUse);
}

void sensorsPoll(uint32_t now) {
  portENTER_CRITICAL(&s_lock);
  const bool virt = s_virtual;
  const uint8_t use = s_realUse;
  const bool refresh = s_refresh;
  s_refresh = false;
  const bool wantMv = s_lightMvRequest;
  s_lightMvRequest = false;
  portEXIT_CRITICAL(&s_lock);

  const bool dhtDue = refresh || !s_dhtEver || now - s_lastDhtMs >= DHT_READ_MS;
  const bool lightDue = refresh || !s_lightEver || now - s_lastLightMs >= LIGHT_READ_MS;
  if (dhtDue) {
    s_dhtEver = true;
    s_lastDhtMs = now;
  }
  if (lightDue) {
    s_lightEver = true;
    s_lastLightMs = now;
  }

  RawSample s = {};
  if (virt) {
    portENTER_CRITICAL(&s_lock);
    s = s_vboard.sample(now, dhtDue, lightDue);
    portEXIT_CRITICAL(&s_lock);
  } else {
    s.now_ms = now;
    if (dhtDue) {  // DHT11 읽기는 수십 ms 걸리므로 잠금 밖에서 한다
      s.has_dht = true;
      s.dht_temp = s_dht.readTemperature();
      s.dht_hum = s_dht.readHumidity();
    }
    if (lightDue) {
      s.has_light = true;
      s.light_raw = (uint16_t)s_light->getRawValue();
    }
    s.reed_closed = (use & DET_REED) ? digitalRead(PIN_REED) != REED_OPEN_LEVEL : true;
    s.flame_active = (use & DET_FLAME) && digitalRead(PIN_FLAME) == FLAME_ACTIVE_LEVEL;
    portENTER_CRITICAL(&s_isrMux);
    s.isr_det = s_isrDet;
    s_isrDet = 0;
    portEXIT_CRITICAL(&s_isrMux);
  }
  uint16_t mv = 0;
  if (wantMv) {  // 점검은 가상 모드에서도 실제 조도 핀을 잰다(배선 확인용)
    uint32_t sum = 0;
    for (int i = 0; i < CHECK_ADC_SAMPLES; i++) sum += analogReadMilliVolts(PIN_LIGHT);
    mv = (uint16_t)(sum / CHECK_ADC_SAMPLES);
  }

  portENTER_CRITICAL(&s_isrMux);
  const uint32_t e0 = s_isrEdges[0], e1 = s_isrEdges[1], e2 = s_isrEdges[2];
  portEXIT_CRITICAL(&s_isrMux);

  portENTER_CRITICAL(&s_lock);
  if (virt == s_virtual) s_judge.update(s);  // 그사이 출처가 바뀌었으면 버린다(다음 센싱이 새 출처로)
  s_stats.polls++;
  if (s.has_dht) {
    s_stats.dht_reads++;
    if (isnan(s.dht_temp) || isnan(s.dht_hum)) s_stats.dht_fails++;
  }
  s_stats.sound_edges = e0;
  s_stats.flame_edges = e1;
  s_stats.shock_edges = e2;
  if (wantMv) {
    s_stats.light_mv = mv;
    s_stats.light_mv_seq++;
  }
  portEXIT_CRITICAL(&s_lock);
}

EnvReading sensorsLatest() {
  portENTER_CRITICAL(&s_lock);
  const EnvReading r = s_judge.reading();
  portEXIT_CRITICAL(&s_lock);
  return r;
}

uint8_t sensorsPendingDetections() {
  portENTER_CRITICAL(&s_lock);
  const uint8_t d = s_judge.pending();
  portEXIT_CRITICAL(&s_lock);
  return d;
}

uint8_t sensorsTakeDetections() {
  portENTER_CRITICAL(&s_lock);
  const uint8_t d = s_judge.takeDetections();
  portEXIT_CRITICAL(&s_lock);
  return d;
}

bool sensorsTakeHeatOnset(bool* simulated) {
  portENTER_CRITICAL(&s_lock);
  const bool onset = s_judge.takeHeatOnset(simulated);
  portEXIT_CRITICAL(&s_lock);
  return onset;
}

void sensorsSetVirtualMode(bool on) {
  const uint32_t now = millis();
  portENTER_CRITICAL(&s_lock);
  if (on == s_virtual) {
    portEXIT_CRITICAL(&s_lock);
    return;
  }
  s_virtual = on;
  if (on) s_vboard.begin(now);  // 시나리오를 처음부터
  s_judge.setVirtualSensors(on);
  s_judge.setUse(on ? DET_ALL : s_realUse);
  s_refresh = true;
  const uint8_t use = s_realUse;
  portEXIT_CRITICAL(&s_lock);
  applyInterrupts(on ? 0 : use);
}

bool sensorsVirtualMode() {
  portENTER_CRITICAL(&s_lock);
  const bool v = s_virtual;
  portEXIT_CRITICAL(&s_lock);
  return v;
}

void sensorsSetRealUse(uint8_t mask) {
  mask &= DET_ALL;
  portENTER_CRITICAL(&s_lock);
  s_realUse = mask;
  const bool virt = s_virtual;
  if (!virt) s_judge.setUse(mask);
  portEXIT_CRITICAL(&s_lock);
  if (!virt) applyInterrupts(mask);
}

uint8_t sensorsRealUse() {
  portENTER_CRITICAL(&s_lock);
  const uint8_t u = s_realUse;
  portEXIT_CRITICAL(&s_lock);
  return u;
}

void sensorsSetVirtualTemp(float c) {
  portENTER_CRITICAL(&s_lock);
  s_judge.setVirtualTemp(c);
  portEXIT_CRITICAL(&s_lock);
}

float sensorsVirtualTemp() {
  portENTER_CRITICAL(&s_lock);
  const float v = s_judge.virtualTemp();
  portEXIT_CRITICAL(&s_lock);
  return v;
}

bool sensorsInject(uint8_t det) {
  det &= DET_ALL;
  portENTER_CRITICAL(&s_lock);
  const bool ok = s_virtual && det;
  if (ok) s_vboard.inject(det);
  portEXIT_CRITICAL(&s_lock);
  return ok;
}

void sensorsSetScenario(bool on) {
  portENTER_CRITICAL(&s_lock);
  s_vboard.setScenario(on);
  portEXIT_CRITICAL(&s_lock);
}

bool sensorsScenario() {
  portENTER_CRITICAL(&s_lock);
  const bool on = s_vboard.scenario();
  portEXIT_CRITICAL(&s_lock);
  return on;
}

const char* sensorsScenarioPhase() {
  const uint32_t now = millis();
  portENTER_CRITICAL(&s_lock);
  const char* name = s_vboard.scenario() ? VirtualBoard::phaseName(s_vboard.offset(now)) : "steady";
  portEXIT_CRITICAL(&s_lock);
  return name;
}

void sensorsRequestLightMv() {
  portENTER_CRITICAL(&s_lock);
  s_lightMvRequest = true;
  portEXIT_CRITICAL(&s_lock);
}

IoSensorStats sensorsStats() {
  portENTER_CRITICAL(&s_lock);
  const IoSensorStats s = s_stats;
  portEXIT_CRITICAL(&s_lock);
  return s;
}

uint8_t sensorsDhtFailRun() {
  portENTER_CRITICAL(&s_lock);
  const uint8_t n = s_judge.dhtFailRun();
  portEXIT_CRITICAL(&s_lock);
  return n;
}
