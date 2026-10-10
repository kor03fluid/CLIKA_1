// SQUAD LINK 환경 노드 (ESP32 WROOM) — 공통 데이터 규격 v1 (docs/data_spec_v1.md)
// - DHT11·조도(필수), 소리·불꽃·충격·리드스위치(추가) 측정
// - environment·event(heat_exposure) 패킷을 BLE 비연결 광고로 송신 (고정 5초 / 적응 주기 비교)
// - 고정 앵커: 병사 직접 방송을 관측해 anchor_observation 보고
// - USB 시리얼: 보낸 패킷마다 규격 v1 JSON 한 줄(NDJSON). 진단은 "# "로 시작하는 줄로 따로 낸다
#include <BLEDevice.h>
#include "config.h"
#include "packet.h"
#include "node.h"
#include "json_out.h"
#include "sensors.h"
#include "ble_tx.h"
#include "anchor.h"

static bool s_adaptive = TX_MODE_ADAPTIVE_DEFAULT;
static uint32_t s_lastEnvTx = 0;
static uint32_t s_lastDetectTx = 0;
static bool s_sentOnce = false;
static bool s_heatPending = false;
static PktEnvironment s_lastSent = {};
static uint16_t s_eventNo[5] = {};  // EventType별 사건 번호(부팅마다 1부터)

static const char* modeName() { return s_adaptive ? "adaptive" : "fixed"; }

// ----- 진단 줄 ("# {...}", 데이터 스트림 아님) -----
static void diagBegin(const char* type) {
  char name[16];
  nodeName(NODE_ID, name, sizeof(name));
  Serial.printf("# {\"type\":\"%s\",\"node_id\":\"%s\",\"boot_id\":\"boot_%04x\"", type, name, nodeBootId());
}

// 사용자가 친 글자를 넣으므로 따옴표·역슬래시·제어문자를 바꿔 쓴다.
static void printWarn(const char* msg, const String& detail) {
  String safe;
  for (size_t i = 0; i < detail.length(); i++) {
    char c = detail[i];
    safe += (c == '"' || c == '\\' || (uint8_t)c < 0x20) ? '_' : c;
  }
  diagBegin("warn");
  Serial.printf(",\"msg\":\"%s: %s\"}\n", msg, safe.c_str());
}

// ----- environment -----
// 현재 선언하는 정상 보고 주기. 서버는 이것으로 두절 기준을 정한다.
static uint32_t declaredIntervalMs() {
  if (!s_adaptive) return TX_FIXED_INTERVAL_MS;
  const EnvReading& r = sensorsLatest();
  return (r.heat || r.flame_now) ? ENV_ALERT_INTERVAL_MS : ENV_HEARTBEAT_MS;
}

static uint8_t tri(bool v) { return v ? TB_TRUE : TB_FALSE; }

static PktEnvironment buildEnv(uint8_t det) {
  const EnvReading& r = sensorsLatest();
  PktEnvironment p = {};
  p.air_temp_c10 = isnan(r.temp_c) ? ENV_TEMP_NULL : (int16_t)lroundf(r.temp_c * 10);
  p.humidity_pct = isnan(r.humidity) ? ENV_HUM_NULL : (uint8_t)constrain(lroundf(r.humidity), 0, 100);
  p.light_raw = r.light_ok ? r.light_raw : ENV_LIGHT_NULL;
  p.heartbeat_s = declaredIntervalMs() / 1000;
  uint16_t ss = (r.dht_ok ? SS_OK : SS_UNAVAILABLE) << ENV_SS_DHT11;
  ss |= (r.light_ok ? SS_OK : SS_UNAVAILABLE) << ENV_SS_LIGHT;
  uint8_t dt = 0;
  // 소리·충격: 직전 보고 이후 반응(래치). 불꽃: 현재 반응 또는 직전 보고 이후 반응. 리드: 현재 닫힘 여부
#if USE_SOUND
  dt |= tri(det & DET_SOUND) << ENV_DT_SOUND;
#else
  dt |= TB_OMIT << ENV_DT_SOUND;
  ss |= SS_DISABLED << ENV_SS_SOUND;
#endif
#if USE_FLAME
  dt |= tri((det & DET_FLAME) || r.flame_now) << ENV_DT_FLAME;
#else
  dt |= TB_OMIT << ENV_DT_FLAME;
  ss |= SS_DISABLED << ENV_SS_FLAME;
#endif
#if USE_SHOCK
  dt |= tri(det & DET_SHOCK) << ENV_DT_SHOCK;
#else
  dt |= TB_OMIT << ENV_DT_SHOCK;
  ss |= SS_DISABLED << ENV_SS_SHOCK;
#endif
#if USE_REED
  dt |= tri(r.reed_closed) << ENV_DT_REED_CLOSED;
#else
  dt |= TB_OMIT << ENV_DT_REED_CLOSED;
  ss |= SS_DISABLED << ENV_SS_REED;
#endif
  p.sensor_status = ss;
  p.detected = dt;
  return p;
}

static void sendEnv(uint32_t now, bool urgent) {
  static bool warnedFull = false;
  if (bleTxFree() == 0) {
    // 큐가 비면 다음 loop에서 다시 시도한다. 감지 래치와 seq는 그대로 둔다.
    if (!warnedFull) printWarn("tx queue full", "environment");
    warnedFull = true;
    return;
  }
  warnedFull = false;
  PktEnvironment p = buildEnv(sensorsTakeDetections());
  uint8_t flags = urgent ? PKT_FLAG_EVENT : 0;
  if (sensorsLatest().virtual_temp) flags |= PKT_FLAG_SIMULATION;
  nodeFillHeader(p.h, PKT_ENVIRONMENT, flags);
  bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), urgent ? EVENT_REPEATS : 1);  // 자리는 위에서 확인
  printEnvironmentJson(p);
  s_lastSent = p;
  s_sentOnce = true;
  s_lastEnvTx = now;
  if (urgent) s_lastDetectTx = now;
}

// ----- event (환경 열 노출 주의) -----
static bool sendEvent(uint8_t type) {
  if (bleTxFree() == 0) return false;  // 다음 loop에서 다시
  PktEvent p = {};
  uint8_t flags = PKT_FLAG_EVENT;
  if (sensorsLatest().virtual_temp) flags |= PKT_FLAG_SIMULATION;  // 가상 온도로 생긴 사건은 가상
  nodeFillHeader(p.h, PKT_EVENT, flags);
  p.event_type = type;
  p.mode = MODE_NORMAL;  // 환경 노드에는 기도비닉 모드가 없다
  p.event_no = ++s_eventNo[type];
  bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), EVENT_REPEATS);
  printEventJson(p);
  return true;
}

static bool changedEnough(const PktEnvironment& now, const PktEnvironment& last) {
  if (now.sensor_status != last.sensor_status || now.heartbeat_s != last.heartbeat_s) return true;
  if (now.detected != last.detected) return true;  // 리드 상태·불꽃 현재 반응 변화
  if ((now.air_temp_c10 == ENV_TEMP_NULL) != (last.air_temp_c10 == ENV_TEMP_NULL)) return true;
  if (now.air_temp_c10 != ENV_TEMP_NULL && abs(now.air_temp_c10 - last.air_temp_c10) >= DELTA_TEMP_C * 10)
    return true;
  if ((now.humidity_pct == ENV_HUM_NULL) != (last.humidity_pct == ENV_HUM_NULL)) return true;
  if (now.humidity_pct != ENV_HUM_NULL && abs(now.humidity_pct - last.humidity_pct) >= DELTA_HUM_PCT)
    return true;
  if (now.light_raw != ENV_LIGHT_NULL && last.light_raw != ENV_LIGHT_NULL &&
      abs((int)now.light_raw - (int)last.light_raw) >= DELTA_LIGHT_RAW)
    return true;
  return false;
}

// 송신 정책. 사건은 두 모드 모두 즉시. fixed: 환경은 고정 주기만(감지는 다음 패킷에 래치).
// adaptive: 감지 즉시(반복)·값 변화 시·선언한 주기마다.
static void envTxPolicy(uint32_t now) {
  if (sensorsTakeHeatOnset()) s_heatPending = true;
  if (s_heatPending && sendEvent(EV_HEAT_EXPOSURE)) s_heatPending = false;

  if (!s_sentOnce) {
    if (now > DHT_READ_MS + 1000) sendEnv(now, false);  // DHT 안정화·두 번째 측정 후
    return;
  }
  uint32_t since = now - s_lastEnvTx;
  if (!s_adaptive) {
    if (since >= TX_FIXED_INTERVAL_MS) sendEnv(now, false);
    return;
  }
  if (sensorsPendingDetections()) {
    // 감지는 반복 광고가 붙은 패킷으로만 보낸다. 최소 간격 동안은 다른 송신도 미룬다.
    if (now - s_lastDetectTx >= EVENT_MIN_GAP_MS) sendEnv(now, true);
    return;
  }
  if (since >= ENV_MIN_GAP_MS && changedEnough(buildEnv(0), s_lastSent)) {
    sendEnv(now, false);
    return;
  }
  if (since >= declaredIntervalMs()) sendEnv(now, false);
}

static void printStats() {
  const TxStats& t = bleTxStats();
  const AnchorStats& a = anchorStats();
  diagBegin("stats");
  Serial.printf(",\"tx_mode\":\"%s\",\"uptime_ms\":%lu,"
                "\"tx\":{\"packets\":%lu,\"windows\":%lu,\"est_adv_events\":%lu,\"payload_bytes\":%lu,"
                "\"dropped\":%lu},"
                "\"anchor\":{\"rx_total\":%lu,\"rx_soldier\":%lu,\"rx_relayed_skip\":%lu,"
                "\"rx_simulation_skip\":%lu,\"table_full_skip\":%lu,\"reports\":%lu,\"queue_full_skip\":%lu}}\n",
                modeName(), (unsigned long)millis(), (unsigned long)t.packets,
                (unsigned long)t.windows, (unsigned long)t.est_adv_events,
                (unsigned long)t.payload_bytes, (unsigned long)t.dropped, (unsigned long)a.rx_total,
                (unsigned long)a.rx_soldier, (unsigned long)a.rx_relayed_skip,
                (unsigned long)a.rx_simulation_skip, (unsigned long)a.table_full_skip,
                (unsigned long)a.reports, (unsigned long)a.queue_full_skip);
}

// "vtemp <°C>": 숫자 전체가 올바를 때만 적용한다(오타로 0°C가 들어가지 않게).
static void setVirtualTempCommand(const char* arg) {
  char* end = nullptr;
  float v = strtof(arg, &end);
  if (end == arg || *end != '\0' || !isfinite(v) || v < -40.0f || v > 100.0f) {
    printWarn("vtemp needs a number between -40 and 100, or off", String(arg));
    return;
  }
  sensorsSetVirtualTemp(v);
}

// 시리얼 명령: stats | mode fixed | mode adaptive | vtemp <°C> | vtemp off | send
static void handleSerial(uint32_t now) {
  static String line;
  while (Serial.available()) {
    char c = Serial.read();
    if (c != '\n' && c != '\r') {
      if (line.length() < 64) line += c;
      continue;
    }
    line.trim();
    if (line == "stats") printStats();
    else if (line == "mode fixed") s_adaptive = false;
    else if (line == "mode adaptive") s_adaptive = true;
    else if (line == "vtemp off") sensorsSetVirtualTemp(NAN);
    else if (line.startsWith("vtemp ")) setVirtualTempCommand(line.c_str() + 6);
    else if (line == "send") sendEnv(now, false);
    else if (line.length()) printWarn("unknown command", line);
    line = "";
  }
}

void setup() {
  Serial.begin(115200);
  nodeBegin();
  BLEDevice::init("");  // 이름은 광고하지 않음(페이로드 절약)
  bleTxBegin();
  sensorsBegin();
#if ANCHOR_ENABLE
  anchorBegin();
#endif
  diagBegin("boot");
  Serial.printf(",\"tx_mode\":\"%s\",\"anchor\":%s,\"schema_version\":\"1.0\"}\n", modeName(),
                ANCHOR_ENABLE ? "true" : "false");
}

void loop() {
  uint32_t now = millis();
  sensorsPoll(now);
  envTxPolicy(now);
#if ANCHOR_ENABLE
  anchorLoop(now);
#endif
  bleTxLoop(now);
  handleSerial(now);
  delay(5);
}
