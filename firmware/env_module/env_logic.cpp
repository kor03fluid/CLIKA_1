#include "env_logic.h"
#include "config.h"
#include <stdlib.h>

// ===== 가상 센서 보드 =====
#define VB_PERIOD_MS 600000UL  // 시나리오 10분 반복

// 시나리오 구간(시작 ms, 이름). 경계는 시험(pc/tests)과 README 표에 같은 값으로 적는다.
struct Phase { uint32_t from; const char* name; };
static const Phase PHASES[] = {
  {0, "normal"},
  {30000, "sound_pulse"},     // 30s 큰 소리 펄스
  {60000, "shock_pulse"},     // 60s 설치물 충격 펄스
  {90000, "reed_open"},       // 90~100s 리드 열림
  {100000, "normal"},
  {150000, "flame"},          // 150~160s 불꽃 반응
  {160000, "normal"},
  {200000, "heat_rise"},      // 200~300s 24 → 37°C (약 285s에 35°C: 열 노출 주의)
  {300000, "heat_hold"},      // 300~360s 37°C 유지
  {360000, "heat_fall"},      // 360~420s 37 → 24°C (약 374s에 34°C: 해제)
  {420000, "normal"},
  {480000, "dht_fail"},       // 480~500s DHT11 읽기 실패(약 6초 뒤 측정 불가 null)
  {500000, "normal"},
  {520000, "dark"},           // 520~560s 어두워짐(조도 원시값 약 200)
  {560000, "normal"},
};

static float wave(uint32_t t, uint32_t period_ms) {
  return sinf(6.2831853f * (float)(t % period_ms) / (float)period_ms);
}

void VirtualBoard::begin(uint32_t now) {
  start_ = now;
  last_ = now;
  started_ = true;
  injected_ = 0;
  reedManualOpen_ = false;
}

uint32_t VirtualBoard::offset(uint32_t now) const { return (now - start_) % VB_PERIOD_MS; }

const char* VirtualBoard::phaseName(uint32_t off) {
  const char* name = PHASES[0].name;
  for (const Phase& p : PHASES) {
    if (off >= p.from) name = p.name;
  }
  return name;
}

void VirtualBoard::inject(uint8_t det) {
  if (det & DET_REED) reedManualOpen_ = !reedManualOpen_;
  injected_ |= det & (DET_SOUND | DET_FLAME | DET_SHOCK);
}

// 시나리오 시각 off(시작 후 경과 elapsed 기준)에 처음 도달했는가: (last, now] 사이에 있었는가
static bool crossed(uint32_t lastElapsed, uint32_t nowElapsed, uint32_t off) {
  auto count = [off](uint32_t e) -> uint32_t { return e >= off ? (e - off) / VB_PERIOD_MS + 1 : 0; };
  return count(nowElapsed) > count(lastElapsed);
}

RawSample VirtualBoard::sample(uint32_t now, bool dhtDue, bool lightDue) {
  if (!started_) begin(now);
  RawSample s = {};
  s.now_ms = now;
  const uint32_t off = offset(now);
  const uint32_t e = now - start_, le = last_ - start_;
  last_ = now;

  float temp = VSENSOR_TEMP_C + 0.4f * wave(off, 120000);
  float hum = VTEMP_HUMIDITY_PCT + 2.0f * wave(off, 150000);
  float light = VSENSOR_LIGHT_RAW + 150.0f * wave(off, 90000);
  bool dhtFail = false;
  bool reedOpen = false;
  bool flame = false;
  uint8_t pulse = 0;
  if (scenario_) {
    const float peak = 37.0f;
    if (off >= 200000 && off < 300000) {
      const float k = (off - 200000) / 100000.0f;
      temp = VSENSOR_TEMP_C + (peak - VSENSOR_TEMP_C) * k;
      hum = VTEMP_HUMIDITY_PCT - 15.0f * k;
    } else if (off >= 300000 && off < 360000) {
      temp = peak;
      hum = VTEMP_HUMIDITY_PCT - 15.0f;
    } else if (off >= 360000 && off < 420000) {
      const float k = (off - 360000) / 60000.0f;
      temp = peak - (peak - VSENSOR_TEMP_C) * k;
      hum = VTEMP_HUMIDITY_PCT - 15.0f * (1.0f - k);
    }
    dhtFail = off >= 480000 && off < 500000;
    if (off >= 520000 && off < 560000) light = 200.0f + 20.0f * wave(off, 7000);
    reedOpen = off >= 90000 && off < 100000;
    flame = off >= 150000 && off < 160000;
    if (crossed(le, e, 30000)) pulse |= DET_SOUND;
    if (crossed(le, e, 60000)) pulse |= DET_SHOCK;
    if (crossed(le, e, 150000)) pulse |= DET_FLAME;
  }
  s.has_dht = dhtDue;
  s.dht_temp = dhtFail ? NAN : temp;
  s.dht_hum = dhtFail ? NAN : hum;
  s.has_light = lightDue;
  s.light_raw = (uint16_t)lroundf(light < 0 ? 0 : light > 4095 ? 4095 : light);
  s.reed_closed = !(reedOpen != reedManualOpen_);  // 손으로 연 상태에서 시나리오가 열면 닫힘으로 본다
  s.flame_active = flame;
  s.isr_det = pulse | injected_;
  injected_ = 0;
  return s;
}

// ===== 상태 판단 =====
void EnvJudge::begin(uint8_t use, bool virtualSensors, uint32_t now) {
  *this = EnvJudge();
  use_ = use & DET_ALL;
  vsensor_ = virtualSensors;
  reedRawSince_ = now;
  cur_.temp_c = NAN;
  cur_.humidity = NAN;
  judge();
}

void EnvJudge::update(const RawSample& s) {
  if (s.has_dht) {
    if (!isnan(s.dht_temp) && !isnan(s.dht_hum)) {
      dhtFails_ = 0;
      dhtTemp_ = s.dht_temp;
      dhtHum_ = s.dht_hum;
    } else if (dhtFails_ < 255) {
      dhtFails_++;
    }
  }
  if (s.has_light) {
    lightRaw_ = s.light_raw;
    lightSeen_ = true;
  }
  // 리드: 켠 경우만. 디바운스 후 바뀌면 감지로 래치한다.
  if (use_ & DET_REED) {
    if (!reedTracking_) {
      reedTracking_ = true;
      reedClosed_ = reedRaw_ = s.reed_closed;
      reedRawSince_ = s.now_ms;
    } else if (s.reed_closed != reedRaw_) {
      reedRaw_ = s.reed_closed;
      reedRawSince_ = s.now_ms;
    } else if (s.reed_closed != reedClosed_ && s.now_ms - reedRawSince_ >= REED_DEBOUNCE_MS) {
      reedClosed_ = s.reed_closed;
      latched_ |= DET_REED;
    }
  } else {
    reedTracking_ = false;
  }
  latched_ |= s.isr_det & use_ & (DET_SOUND | DET_FLAME | DET_SHOCK);
  flameActive_ = s.flame_active;
  judge();
}

void EnvJudge::judge() {
  EnvReading r = cur_;  // heat는 이어 간다
  r.virtual_sensors = vsensor_;
  r.simulated = simulating();
  r.use_mask = use_;
  // DHT11은 가끔 한 번씩 읽기(체크섬)가 실패한다. 연달아 DHT_FAIL_LIMIT번 실패해야 측정 불가(그동안은 직전 값).
  const bool dhtOk = dhtFails_ < DHT_FAIL_LIMIT && !isnan(dhtTemp_) && !isnan(dhtHum_);
  if (!isnan(vtemp_)) {
    // vtemp 시험: 온도는 시험값, 습도는 측정값(없으면 가상 습도). 규격 7장 "dht11 ok ⇔ 온습도 모두 숫자"
    r.dht_ok = true;
    r.temp_c = vtemp_;
    r.humidity = dhtOk ? dhtHum_ : VTEMP_HUMIDITY_PCT;
  } else {
    r.dht_ok = dhtOk;
    r.temp_c = dhtOk ? dhtTemp_ : NAN;
    r.humidity = dhtOk ? dhtHum_ : NAN;
  }
  r.light_ok = lightSeen_;  // TODO: 단선·포화 판정 기준은 실물 로그로 정한다("check"가 핀 전압으로 경고)
  r.light_raw = lightRaw_;
  r.flame_now = (use_ & DET_FLAME) && flameActive_;
  r.reed_closed = reedClosed_;
  // 열 노출 주의(측정 불가면 직전 상태 유지)
  if (!isnan(r.temp_c)) {
    if (!r.heat && r.temp_c >= HEAT_ON_C) {
      r.heat = true;
      heatOnset_ = true;
      heatOnsetSim_ = r.simulated;
    } else if (r.heat && r.temp_c <= HEAT_OFF_C) {
      r.heat = false;
    }
  }
  cur_ = r;
}

uint8_t EnvJudge::takeDetections() {
  const uint8_t d = latched_;
  latched_ = 0;
  return d;
}

bool EnvJudge::takeHeatOnset(bool* simulated) {
  const bool onset = heatOnset_;
  if (onset && simulated) *simulated = heatOnsetSim_;
  heatOnset_ = false;
  return onset;
}

void EnvJudge::setUse(uint8_t mask) {
  use_ = mask & DET_ALL;
  latched_ &= use_;
  judge();
}

// 실측 ↔ 가상이 바뀔 때: 실측 열 노출 상태를 맡아 두고 가상값으로 새로 판정하며, 끝나면 되돌린다
// (실측이 이미 더워도 가상 사건이 생기고, 끝난 뒤 같은 실측 노출로 사건이 또 생기지 않게).
void EnvJudge::simulationChanged(bool was) {
  const bool now = simulating();
  if (!was && now) {
    realHeat_ = cur_.heat;
    cur_.heat = false;
    heatOnset_ = false;
  } else if (was && !now) {
    cur_.heat = realHeat_;
    heatOnset_ = false;
  }
  judge();
}

void EnvJudge::setVirtualTemp(float c) {
  const bool was = simulating();
  vtemp_ = c;
  simulationChanged(was);
}

void EnvJudge::setVirtualSensors(bool on) {
  if (on == vsensor_) return;
  const bool was = simulating();
  vsensor_ = on;
  // 출처가 바뀌므로 이전 출처의 측정값·감지를 버리고 다음 원시값부터 새로 판단한다
  latched_ = 0;
  dhtFails_ = 0;
  dhtTemp_ = NAN;
  dhtHum_ = NAN;
  lightSeen_ = false;
  flameActive_ = false;
  reedTracking_ = false;
  simulationChanged(was);
}

// ===== 보고 정책 =====
uint32_t ReportPolicy::declaredIntervalMs(const EnvReading& r) const {
  if (!adaptive_) return TX_FIXED_INTERVAL_MS;
  return (r.heat || r.flame_now) ? ENV_ALERT_INTERVAL_MS : ENV_HEARTBEAT_MS;
}

SendKind ReportPolicy::decide(uint32_t now, const EnvReading& r, uint8_t pendingDet) const {
  if (!sentOnce_) return now > DHT_READ_MS + 1000 ? SEND_NORMAL : SEND_NONE;  // DHT 안정화·두 번째 측정 후
  const uint32_t since = now - lastEnvTx_;
  if (!adaptive_) return since >= TX_FIXED_INTERVAL_MS ? SEND_NORMAL : SEND_NONE;
  if (pendingDet) {
    // 감지는 반복 광고가 붙은 패킷으로만 보낸다. 최소 간격 동안은 다른 송신도 미룬다.
    return now - lastDetectTx_ >= EVENT_MIN_GAP_MS ? SEND_URGENT : SEND_NONE;
  }
  const uint32_t interval = declaredIntervalMs(r);
  if (since >= ENV_MIN_GAP_MS && envChangedEnough(buildEnvironment(r, 0, interval), last_)) return SEND_NORMAL;
  return since >= interval ? SEND_NORMAL : SEND_NONE;
}

void ReportPolicy::markSent(uint32_t now, SendKind kind, const PktEnvironment& p) {
  sentOnce_ = true;
  lastEnvTx_ = now;
  if (kind == SEND_URGENT) lastDetectTx_ = now;
  last_ = p;
}

// ===== environment 본문 =====
static uint8_t tri(bool v) { return v ? TB_TRUE : TB_FALSE; }

PktEnvironment buildEnvironment(const EnvReading& r, uint8_t det, uint32_t intervalMs) {
  PktEnvironment p = {};
  const bool dhtOk = r.dht_ok && !isnan(r.temp_c) && !isnan(r.humidity);  // ok ⇔ 온도·습도 모두 숫자
  if (dhtOk) {
    p.air_temp_c10 = (int16_t)lroundf(r.temp_c * 10);
    const long h = lroundf(r.humidity);
    p.humidity_pct = (uint8_t)(h < 0 ? 0 : h > 100 ? 100 : h);  // 규격 7장: 0~100
  } else {
    p.air_temp_c10 = ENV_TEMP_NULL;
    p.humidity_pct = ENV_HUM_NULL;
  }
  p.light_raw = r.light_ok ? r.light_raw : ENV_LIGHT_NULL;
  p.heartbeat_s = intervalMs / 1000;
  uint16_t ss = (dhtOk ? SS_OK : SS_UNAVAILABLE) << ENV_SS_DHT11;
  ss |= (r.light_ok ? SS_OK : SS_UNAVAILABLE) << ENV_SS_LIGHT;
  uint8_t dt = 0;
  // 소리·충격: 직전 보고 이후 반응(래치). 불꽃: 현재 반응 또는 직전 보고 이후 반응. 리드: 현재 닫힘 여부.
  // 끈 센서는 TB_OMIT → JSON에서 필드와 sensor_status 키를 모두 뺀다(규격 3장 6: 선택 필드 생략).
  if (r.use_mask & DET_SOUND) dt |= tri(det & DET_SOUND) << ENV_DT_SOUND;
  else { dt |= TB_OMIT << ENV_DT_SOUND; ss |= SS_DISABLED << ENV_SS_SOUND; }
  if (r.use_mask & DET_FLAME) dt |= tri((det & DET_FLAME) || r.flame_now) << ENV_DT_FLAME;
  else { dt |= TB_OMIT << ENV_DT_FLAME; ss |= SS_DISABLED << ENV_SS_FLAME; }
  if (r.use_mask & DET_SHOCK) dt |= tri(det & DET_SHOCK) << ENV_DT_SHOCK;
  else { dt |= TB_OMIT << ENV_DT_SHOCK; ss |= SS_DISABLED << ENV_SS_SHOCK; }
  if (r.use_mask & DET_REED) dt |= tri(r.reed_closed) << ENV_DT_REED_CLOSED;
  else { dt |= TB_OMIT << ENV_DT_REED_CLOSED; ss |= SS_DISABLED << ENV_SS_REED; }
  p.sensor_status = ss;
  p.detected = dt;
  return p;
}

bool envChangedEnough(const PktEnvironment& now, const PktEnvironment& last) {
  if (now.sensor_status != last.sensor_status || now.heartbeat_s != last.heartbeat_s) return true;
  // 감지 값 중 리드(현재 상태)만 비교한다. 소리·충격·불꽃은 래치라 감지 송신 다음 비교에서 참→거짓으로 보여
  // 쓸데없는 패킷이 한 번 더 나간다. 감지는 래치가 즉시 송신하고, 불꽃이 계속되는 동안은 선언 주기(10초)가 맡는다.
  auto reed = [](const PktEnvironment& p) { return (p.detected >> ENV_DT_REED_CLOSED) & 3; };
  if (reed(now) != reed(last)) return true;
  if ((now.air_temp_c10 == ENV_TEMP_NULL) != (last.air_temp_c10 == ENV_TEMP_NULL)) return true;
  if (now.air_temp_c10 != ENV_TEMP_NULL && abs(now.air_temp_c10 - last.air_temp_c10) >= DELTA_TEMP_C * 10)
    return true;
  if ((now.humidity_pct == ENV_HUM_NULL) != (last.humidity_pct == ENV_HUM_NULL)) return true;
  if (now.humidity_pct != ENV_HUM_NULL && abs(now.humidity_pct - last.humidity_pct) >= DELTA_HUM_PCT)
    return true;
  if ((now.light_raw == ENV_LIGHT_NULL) != (last.light_raw == ENV_LIGHT_NULL)) return true;
  if (now.light_raw != ENV_LIGHT_NULL && last.light_raw != ENV_LIGHT_NULL &&
      abs((int)now.light_raw - (int)last.light_raw) >= DELTA_LIGHT_RAW)
    return true;
  return false;
}

// ===== 내보내기 전 검사 =====
const char* checkHeader(const PktHeader& h, uint8_t expectType, uint8_t selfNodeId) {
  if (pktVersion(h) != PKT_VERSION) return "header version";
  if (pktType(h) != expectType) return "header packet type";
  if (h.node_id != selfNodeId || h.node_id < 0x31 || h.node_id > 0x3F) return "header node_id is not this env node";
  if (h.flags & ~(PKT_FLAG_SIMULATION | PKT_FLAG_EVENT)) return "header flags (origin must not set relayed)";
  if (h.seq == 0) return "header seq starts at 1";
  return nullptr;
}

static uint8_t two(uint16_t v, int shift) { return (v >> shift) & 3; }

const char* checkEnvironment(const PktEnvironment& p, uint8_t selfNodeId) {
  if (const char* e = checkHeader(p.h, PKT_ENVIRONMENT, selfNodeId)) return e;
  const bool tNull = p.air_temp_c10 == ENV_TEMP_NULL, hNull = p.humidity_pct == ENV_HUM_NULL;
  if (!tNull && (p.air_temp_c10 < -400 || p.air_temp_c10 > 1000)) return "air_temperature_c out of -40..100";
  if (!hNull && p.humidity_pct > 100) return "humidity_pct out of 0..100";
  if (tNull != hNull) return "dht11 temperature and humidity must be both numbers or both null";
  const uint8_t dhtSs = two(p.sensor_status, ENV_SS_DHT11);
  if ((dhtSs == SS_OK) != !tNull) return "sensor_status.dht11 ok <=> values present";
  const bool lNull = p.light_raw == ENV_LIGHT_NULL;
  if (!lNull && p.light_raw > 4095) return "light_raw out of 0..4095 (12bit ADC)";
  if ((two(p.sensor_status, ENV_SS_LIGHT) == SS_OK) != !lNull) return "sensor_status.light ok <=> value present";
  if (p.heartbeat_s == 0) return "heartbeat_interval_ms must be positive";
  static const int SS[4] = {ENV_SS_SOUND, ENV_SS_FLAME, ENV_SS_SHOCK, ENV_SS_REED};
  static const int DT[4] = {ENV_DT_SOUND, ENV_DT_FLAME, ENV_DT_SHOCK, ENV_DT_REED_CLOSED};
  for (int i = 0; i < 4; i++) {
    const uint8_t d = (p.detected >> DT[i]) & 3, ss = two(p.sensor_status, SS[i]);
    if ((d == TB_OMIT) != (ss == SS_DISABLED)) return "optional sensor field and sensor_status key must go together";
    if (d == TB_NULL && ss == SS_OK) return "optional sensor null needs status unavailable";
  }
  return nullptr;
}

const char* checkEvent(const PktEvent& p, uint8_t selfNodeId) {
  if (const char* e = checkHeader(p.h, PKT_EVENT, selfNodeId)) return e;
  if (p.event_type != EV_HEAT_EXPOSURE) return "env node creates heat_exposure only";
  if (p.mode != MODE_NORMAL) return "env node has no covert mode";
  if (p.event_no == 0) return "event number starts at 1";
  return nullptr;
}

const char* checkAnchorObs(const PktAnchorObs& p, uint8_t selfNodeId) {
  if (const char* e = checkHeader(p.h, PKT_ANCHOR_OBS, selfNodeId)) return e;
  if (p.observed_node < 0x01 || p.observed_node > 0x1F) return "observed node is not a soldier node";
  if (p.rssi_dbm > 0) return "rssi_dbm must be a received level (<= 0)";
  return nullptr;
}

// ===== 배선 점검 판정 =====
#define CHECK_NOISY_EDGES 20  // 점검 시간(2초) 동안 이보다 많으면 떠 있는 핀·감도 과다 의심

uint8_t checkEvaluate(const CheckInput& in, const char** out, uint8_t max) {
  uint8_t n = 0;
  auto add = [&](const char* w) { if (n < max) out[n++] = w; };
  if (in.light_mv_valid && in.light_mv >= CHECK_ADC_HIGH_MV) add("light pin near 3.3V: divider output too high or ADC saturated");
  if (in.light_mv_valid && in.light_mv <= CHECK_ADC_LOW_MV) add("light pin near 0V: open wire, short to GND or very dark");
  if (!in.light_mv_valid) add("light pin voltage not measured yet");
  if (in.virtual_mode) return n;  // 가상 모드: 실제 센서 판정은 하지 않는다(조도 핀 전압만 참고)
  if (in.dht_fail_run >= DHT_FAIL_LIMIT || (in.dht_reads > 0 && in.dht_fails == in.dht_reads))
    add("dht11 no reading: check DATA pin, 3.3V supply and pull-up");
  struct D { uint8_t bit; bool active; uint32_t edges; const char* held; const char* noisy; };
  const D ds[] = {
    {DET_SOUND, in.sound_active, in.sound_edges, "sound output held at active level: check SOUND_ACTIVE_LEVEL or threshold",
     "sound output noisy: floating pin or threshold too sensitive"},
    {DET_FLAME, in.flame_active, in.flame_edges, "flame output active now: real light source or wrong FLAME_ACTIVE_LEVEL",
     "flame output noisy: floating pin or threshold too sensitive"},
    {DET_SHOCK, in.shock_active, in.shock_edges, "shock output held at active level: check SHOCK_ACTIVE_LEVEL",
     "shock output noisy: floating pin or threshold too sensitive"},
  };
  for (const D& d : ds) {
    if (!(in.real_use & d.bit)) continue;
    if (d.edges > CHECK_NOISY_EDGES) add(d.noisy);
    else if (d.active && d.edges == 0) add(d.held);
  }
  return n;
}
