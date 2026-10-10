#include "sensors.h"
#include "config.h"
#include "packet.h"
#include <DHT.h>
#include <RBD_LightSensor.h>

static DHT s_dht(PIN_DHT, DHT11);
static RBD::LightSensor* s_light = nullptr;

static EnvReading s_cur = {};
static uint8_t s_latched = 0;
static uint32_t s_lastDhtMs = 0;
static uint32_t s_lastLightMs = 0;
static float s_virtualTemp = NAN;

// 소리·불꽃·충격은 짧은 펄스라 인터럽트로 래치한다.
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint8_t s_isrEvents = 0;

static void IRAM_ATTR isrLatch(uint8_t bit) {
  portENTER_CRITICAL_ISR(&s_mux);
  s_isrEvents |= bit;
  portEXIT_CRITICAL_ISR(&s_mux);
}
static void IRAM_ATTR isrSound() { isrLatch(ENV_EV_SOUND); }
static void IRAM_ATTR isrFlame() { isrLatch(ENV_EV_FLAME); }
static void IRAM_ATTR isrShock() { isrLatch(ENV_EV_SHOCK); }

static int edgeFor(int activeLevel) { return activeLevel == HIGH ? RISING : FALLING; }

#if USE_REED
static bool s_reedOpen = false;
static bool s_reedRaw = false;
static uint32_t s_reedRawSince = 0;
static bool readReedOpen() { return digitalRead(PIN_REED) == REED_OPEN_LEVEL; }
#endif

void sensorsBegin() {
  analogReadResolution(10);  // RBD_LightSensor는 10bit(0~1023) 기준으로 계산한다
  s_dht.begin();
  s_light = new RBD::LightSensor(PIN_LIGHT);

#if USE_SOUND
  pinMode(PIN_SOUND, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_SOUND), isrSound, edgeFor(SOUND_ACTIVE_LEVEL));
  s_cur.installed |= ENV_HAS_SOUND;
#endif
#if USE_FLAME
  pinMode(PIN_FLAME, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_FLAME), isrFlame, edgeFor(FLAME_ACTIVE_LEVEL));
  s_cur.installed |= ENV_HAS_FLAME;
#endif
#if USE_SHOCK
  pinMode(PIN_SHOCK, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_SHOCK), isrShock, edgeFor(SHOCK_ACTIVE_LEVEL));
  s_cur.installed |= ENV_HAS_SHOCK;
#endif
#if USE_REED
  pinMode(PIN_REED, INPUT_PULLUP);
  s_reedOpen = s_reedRaw = readReedOpen();
  s_reedRawSince = millis();
  s_cur.installed |= ENV_HAS_REED;
#endif

  s_cur.temp_c = NAN;
  s_cur.humidity = NAN;
}

static void updateHeat() {
  bool heat = (s_cur.state & ENV_ST_HEAT) != 0;
  if (!s_cur.dht_ok) return;  // 측정 실패 시 직전 상태 유지
  if (!heat && s_cur.temp_c >= HEAT_ON_C) {
    s_cur.state |= ENV_ST_HEAT;
    s_latched |= ENV_EV_HEAT;
  } else if (heat && s_cur.temp_c <= HEAT_OFF_C) {
    s_cur.state &= ~ENV_ST_HEAT;
  }
}

void sensorsPoll(uint32_t now) {
  if (now - s_lastDhtMs >= DHT_READ_MS || s_lastDhtMs == 0) {
    s_lastDhtMs = now;
    float t = s_dht.readTemperature();
    float h = s_dht.readHumidity();
    s_cur.dht_ok = !isnan(t) && !isnan(h);
    s_cur.temp_c = t;
    s_cur.humidity = h;
    s_cur.virtual_temp = !isnan(s_virtualTemp);
    if (s_cur.virtual_temp) {
      s_cur.temp_c = s_virtualTemp;
      if (isnan(s_cur.humidity)) s_cur.humidity = 50.0f;
      s_cur.dht_ok = true;
    }
    updateHeat();
  }

  if (now - s_lastLightMs >= LIGHT_READ_MS || s_lastLightMs == 0) {
    s_lastLightMs = now;
    // TODO: 단선·포화 판정 기준을 실물 로그로 정한다. 현재는 항상 유효로 본다.
    s_cur.light_pct = LIGHT_INVERT ? s_light->getInversePercentValue() : s_light->getPercentValue();
    s_cur.light_ok = true;
  }

#if USE_FLAME
  if (digitalRead(PIN_FLAME) == FLAME_ACTIVE_LEVEL) s_cur.state |= ENV_ST_FLAME;
  else s_cur.state &= ~ENV_ST_FLAME;
#endif

#if USE_REED
  bool raw = readReedOpen();
  if (raw != s_reedRaw) {
    s_reedRaw = raw;
    s_reedRawSince = now;
  } else if (raw != s_reedOpen && now - s_reedRawSince >= REED_DEBOUNCE_MS) {
    s_reedOpen = raw;
    s_latched |= ENV_EV_REED;
  }
  if (s_reedOpen) s_cur.state |= ENV_ST_REED_OPEN;
  else s_cur.state &= ~ENV_ST_REED_OPEN;
#endif

  portENTER_CRITICAL(&s_mux);
  s_latched |= s_isrEvents;
  s_isrEvents = 0;
  portEXIT_CRITICAL(&s_mux);
}

const EnvReading& sensorsLatest() { return s_cur; }

uint8_t sensorsPendingEvents() { return s_latched; }

uint8_t sensorsTakeEvents() {
  uint8_t ev = s_latched;
  s_latched = 0;
  return ev;
}

void sensorsSetVirtualTemp(float c) {
  if (isnan(c) && !isnan(s_virtualTemp)) {
    // 가상값으로 생긴 열 노출 상태를 지운다. 실측이 실패하는 중이면 직전 상태 유지 규칙 때문에
    // 가상 상태가 실측처럼 남는다. 실측이 성공하면 다음 측정에서 다시 판정된다.
    s_cur.state &= ~ENV_ST_HEAT;
  }
  s_virtualTemp = c;
  s_lastDhtMs = 0;  // 다음 poll에서 즉시 반영
}
