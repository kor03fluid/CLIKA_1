#include "sensors.h"
#include "config.h"
#include <DHT.h>
#include <RBD_LightSensor.h>

static DHT s_dht(PIN_DHT, DHT11);
static RBD::LightSensor* s_light = nullptr;

static EnvReading s_cur = {};
static uint8_t s_latched = 0;
static bool s_heatOnset = false;
static uint32_t s_lastDhtMs = 0;
static uint32_t s_lastLightMs = 0;
static float s_virtualTemp = NAN;
static bool s_realHeat = false;   // vtemp 동안 맡아 둔 실측 열 노출 상태
static uint8_t s_dhtFails = 0;    // 연속 읽기 실패 수
static float s_dhtTemp = NAN;     // 마지막으로 읽은 실측값
static float s_dhtHum = NAN;

// 소리·불꽃·충격은 짧은 펄스라 인터럽트로 래치한다.
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint8_t s_isrDetections = 0;

static void IRAM_ATTR isrLatch(uint8_t bit) {
  portENTER_CRITICAL_ISR(&s_mux);
  s_isrDetections |= bit;
  portEXIT_CRITICAL_ISR(&s_mux);
}
static void IRAM_ATTR isrSound() { isrLatch(DET_SOUND); }
static void IRAM_ATTR isrFlame() { isrLatch(DET_FLAME); }
static void IRAM_ATTR isrShock() { isrLatch(DET_SHOCK); }

static int edgeFor(int activeLevel) { return activeLevel == HIGH ? RISING : FALLING; }

#if USE_REED
static bool s_reedClosed = true;
static bool s_reedRaw = true;
static uint32_t s_reedRawSince = 0;
static bool readReedClosed() { return digitalRead(PIN_REED) != REED_OPEN_LEVEL; }
#endif

void sensorsBegin() {
  analogReadResolution(12);  // light_raw는 12bit 원시값(0~4095)
  s_dht.begin();
  s_light = new RBD::LightSensor(PIN_LIGHT);  // getRawValue()만 쓴다(백분율 계산은 10bit 기준이라 안 씀)

#if USE_SOUND
  pinMode(PIN_SOUND, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_SOUND), isrSound, edgeFor(SOUND_ACTIVE_LEVEL));
#endif
#if USE_FLAME
  pinMode(PIN_FLAME, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_FLAME), isrFlame, edgeFor(FLAME_ACTIVE_LEVEL));
#endif
#if USE_SHOCK
  pinMode(PIN_SHOCK, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_SHOCK), isrShock, edgeFor(SHOCK_ACTIVE_LEVEL));
#endif
#if USE_REED
  pinMode(PIN_REED, INPUT_PULLUP);
  s_reedClosed = s_reedRaw = readReedClosed();
  s_reedRawSince = millis();
  s_cur.reed_closed = s_reedClosed;
#endif

  s_cur.temp_c = NAN;
  s_cur.humidity = NAN;
}

static void updateHeat() {
  if (isnan(s_cur.temp_c)) return;  // 측정 실패 시 직전 상태 유지
  if (!s_cur.heat && s_cur.temp_c >= HEAT_ON_C) {
    s_cur.heat = true;
    s_heatOnset = true;
  } else if (s_cur.heat && s_cur.temp_c <= HEAT_OFF_C) {
    s_cur.heat = false;
  }
}

void sensorsPoll(uint32_t now) {
  if (now - s_lastDhtMs >= DHT_READ_MS || s_lastDhtMs == 0) {
    s_lastDhtMs = now;
    float t = s_dht.readTemperature();
    float h = s_dht.readHumidity();
    if (!isnan(t) && !isnan(h)) {
      s_dhtFails = 0;
      s_dhtTemp = t;
      s_dhtHum = h;
    } else if (s_dhtFails < 255) {
      s_dhtFails++;
    }
    // DHT11은 가끔 한 번씩 읽기(체크섬)가 실패한다. 한 번 실패로 null·unavailable을 보내면 패킷이 두 번 더
    // 나가므로, 연달아 DHT_FAIL_LIMIT번 실패해야 측정 불가로 본다(그동안은 직전 값).
    bool realOk = s_dhtFails < DHT_FAIL_LIMIT && !isnan(s_dhtTemp);
    s_cur.virtual_temp = !isnan(s_virtualTemp);
    if (s_cur.virtual_temp) {
      // 가상 시험: 온도는 가상값, 습도는 실측이 있으면 실측·없으면 가상값. 패킷 전체가 simulation이라
      // DHT11을 아직 연결하지 않아도 "dht11 ok = 온습도 모두 숫자" 규칙으로 받을 수 있다.
      s_cur.dht_ok = true;
      s_cur.temp_c = s_virtualTemp;
      s_cur.humidity = realOk ? s_dhtHum : VTEMP_HUMIDITY_PCT;
    } else {
      s_cur.dht_ok = realOk;
      s_cur.temp_c = realOk ? s_dhtTemp : NAN;
      s_cur.humidity = realOk ? s_dhtHum : NAN;
    }
    updateHeat();
  }

  if (now - s_lastLightMs >= LIGHT_READ_MS || s_lastLightMs == 0) {
    s_lastLightMs = now;
    // TODO: 단선·포화 판정 기준을 실물 로그로 정한다. 현재는 항상 유효로 본다.
    s_cur.light_raw = (uint16_t)s_light->getRawValue();
    s_cur.light_ok = true;
  }

#if USE_FLAME
  s_cur.flame_now = digitalRead(PIN_FLAME) == FLAME_ACTIVE_LEVEL;
#endif

#if USE_REED
  bool raw = readReedClosed();
  if (raw != s_reedRaw) {
    s_reedRaw = raw;
    s_reedRawSince = now;
  } else if (raw != s_reedClosed && now - s_reedRawSince >= REED_DEBOUNCE_MS) {
    s_reedClosed = raw;
    s_latched |= DET_REED;
  }
  s_cur.reed_closed = s_reedClosed;
#endif

  portENTER_CRITICAL(&s_mux);
  s_latched |= s_isrDetections;
  s_isrDetections = 0;
  portEXIT_CRITICAL(&s_mux);
}

const EnvReading& sensorsLatest() { return s_cur; }

uint8_t sensorsPendingDetections() { return s_latched; }

uint8_t sensorsTakeDetections() {
  uint8_t d = s_latched;
  s_latched = 0;
  return d;
}

bool sensorsTakeHeatOnset() {
  bool onset = s_heatOnset;
  s_heatOnset = false;
  return onset;
}

void sensorsSetVirtualTemp(float c) {
  if (!isnan(c) && isnan(s_virtualTemp)) {
    // 가상 시험 시작: 실측 열 노출 상태를 맡아 두고 가상값으로 새로 판정한다
    // (실측이 이미 더워도 가상 사건이 생기고, 끝난 뒤 같은 실측 노출로 사건이 또 생기지 않게).
    s_realHeat = s_cur.heat;
    s_cur.heat = false;
    s_heatOnset = false;
  } else if (isnan(c) && !isnan(s_virtualTemp)) {
    // 가상 시험 끝: 가상값으로 생긴 상태를 버리고 실측 상태로 돌아간다. 다음 측정에서 이어서 판정된다.
    s_cur.heat = s_realHeat;
    s_heatOnset = false;
  }
  s_virtualTemp = c;
  s_lastDhtMs = 0;  // 다음 poll에서 즉시 반영
}
