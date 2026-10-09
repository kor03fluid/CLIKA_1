// SQUAD LINK 환경 노드 (ESP32 WROOM)
// - DHT11·조도(필수), 소리·불꽃·충격·리드스위치(추가) 측정
// - 환경 패킷을 BLE 비연결 광고로 송신 (고정 5초 / 적응 주기 비교)
// - 고정 앵커: 병사 직접 방송 RSSI를 관측해 보고
// - 송신한 패킷을 USB 시리얼에 JSON 한 줄로 출력 (PC 직접 수신·로그용)
#include <BLEDevice.h>
#include "config.h"
#include "packet.h"
#include "node.h"
#include "sensors.h"
#include "ble_tx.h"
#include "anchor.h"

static bool s_adaptive = TX_MODE_ADAPTIVE_DEFAULT;
static uint32_t s_lastEnvTx = 0;
static uint32_t s_lastEventTx = 0;
static bool s_sentOnce = false;
static PktEnv s_lastSent = {};

static const char* modeName() { return s_adaptive ? "adaptive" : "fixed"; }

static void printBits(const char* key, uint8_t bits, const char* const names[], uint8_t count) {
  Serial.printf(",\"%s\":[", key);
  bool first = true;
  for (uint8_t i = 0; i < count; i++) {
    if (!(bits & (1 << i))) continue;
    Serial.printf("%s\"%s\"", first ? "" : ",", names[i]);
    first = false;
  }
  Serial.print("]");
}

static void printEnvJson(const PktEnv& p, const char* reason) {
  static const char* const evNames[] = {"sound", "flame", "shock", "reed", "heat"};
  static const char* const stNames[] = {"heat", "flame", "reed_open"};
  Serial.printf("{\"type\":\"env\",\"node\":%u,\"boot\":%u,\"seq\":%u,\"reason\":\"%s\",\"mode\":\"%s\"",
                p.h.node_id, p.h.boot_id, p.h.seq, reason, modeName());
  if (p.temp_c10 == ENV_TEMP_INVALID) Serial.print(",\"temp\":null,\"hum\":null");
  else Serial.printf(",\"temp\":%.1f,\"hum\":%u", p.temp_c10 / 10.0f, p.humidity);
  if (p.light_pct == ENV_BYTE_INVALID) Serial.print(",\"light\":null");
  else Serial.printf(",\"light\":%u", p.light_pct);
  Serial.printf(",\"valid\":%u", p.valid);
  printBits("events", p.events, evNames, 5);
  printBits("state", p.state, stNames, 3);
  Serial.printf(",\"virtual\":%s,\"ms\":%lu}\n", (p.h.flags & PKT_FLAG_VIRTUAL) ? "true" : "false",
                (unsigned long)millis());
}

static PktEnv buildEnv(uint8_t events) {
  const EnvReading& r = sensorsLatest();
  PktEnv p = {};
  p.valid = r.installed;
  if (r.dht_ok) {
    p.temp_c10 = (int16_t)lroundf(r.temp_c * 10);
    p.humidity = (uint8_t)constrain(lroundf(r.humidity), 0, 100);
    p.valid |= ENV_OK_DHT;
  } else {
    p.temp_c10 = ENV_TEMP_INVALID;
    p.humidity = ENV_BYTE_INVALID;
  }
  if (r.light_ok) {
    p.light_pct = r.light_pct;
    p.valid |= ENV_OK_LIGHT;
  } else {
    p.light_pct = ENV_BYTE_INVALID;
  }
  p.events = events;
  p.state = r.state;
  return p;
}

static void sendEnv(uint32_t now, const char* reason, bool urgent) {
  PktEnv p = buildEnv(sensorsTakeEvents());
  uint8_t flags = urgent ? PKT_FLAG_EVENT : 0;
  if (sensorsLatest().virtual_temp) flags |= PKT_FLAG_VIRTUAL;
  nodeFillHeader(p.h, PKT_ENV, flags);
  if (!bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), urgent ? EVENT_REPEATS : 1)) {
    Serial.println("{\"type\":\"warn\",\"msg\":\"tx queue full\"}");
  }
  printEnvJson(p, reason);
  s_lastSent = p;
  s_sentOnce = true;
  s_lastEnvTx = now;
  if (urgent) s_lastEventTx = now;
}

static bool changedEnough(const PktEnv& now, const PktEnv& last) {
  if (now.valid != last.valid || now.state != last.state) return true;
  if ((now.valid & ENV_OK_DHT) && (last.valid & ENV_OK_DHT)) {
    if (abs(now.temp_c10 - last.temp_c10) >= DELTA_TEMP_C * 10) return true;
    if (abs(now.humidity - last.humidity) >= DELTA_HUM_PCT) return true;
  }
  if ((now.valid & ENV_OK_LIGHT) && (last.valid & ENV_OK_LIGHT)) {
    if (abs(now.light_pct - last.light_pct) >= DELTA_LIGHT_PCT) return true;
  }
  return false;
}

// 송신 정책. fixed: 고정 주기만(이벤트는 다음 패킷에 래치). adaptive: 이벤트 즉시·변화 시·주기 적응.
static void envTxPolicy(uint32_t now) {
  if (!s_sentOnce) {
    if (now > DHT_READ_MS + 1000) sendEnv(now, "boot", false);  // DHT 안정화·두 번째 측정 후
    return;
  }
  uint32_t since = now - s_lastEnvTx;

  if (!s_adaptive) {
    if (since >= TX_FIXED_INTERVAL_MS) sendEnv(now, "fixed", false);
    return;
  }

  if (sensorsPendingEvents() && now - s_lastEventTx >= EVENT_MIN_GAP_MS) {
    sendEnv(now, "event", true);
    return;
  }
  if (since >= ENV_MIN_GAP_MS && changedEnough(buildEnv(0), s_lastSent)) {
    sendEnv(now, "change", false);
    return;
  }
  bool alert = sensorsLatest().state & (ENV_ST_HEAT | ENV_ST_FLAME);
  if (since >= (alert ? ENV_ALERT_INTERVAL_MS : ENV_HEARTBEAT_MS)) {
    sendEnv(now, alert ? "alert" : "heartbeat", false);
  }
}

static void printStats() {
  const TxStats& t = bleTxStats();
  const AnchorStats& a = anchorStats();
  Serial.printf("{\"type\":\"stats\",\"node\":%u,\"boot\":%u,\"mode\":\"%s\",\"uptime_ms\":%lu,"
                "\"tx\":{\"packets\":%lu,\"windows\":%lu,\"est_adv_events\":%lu,\"payload_bytes\":%lu,"
                "\"dropped\":%lu},"
                "\"anchor\":{\"rx_total\":%lu,\"rx_soldier\":%lu,\"rx_relayed_skip\":%lu,"
                "\"table_full_skip\":%lu,\"reports\":%lu}}\n",
                NODE_ID, nodeBootId(), modeName(), (unsigned long)millis(), (unsigned long)t.packets,
                (unsigned long)t.windows, (unsigned long)t.est_adv_events,
                (unsigned long)t.payload_bytes, (unsigned long)t.dropped, (unsigned long)a.rx_total,
                (unsigned long)a.rx_soldier, (unsigned long)a.rx_relayed_skip,
                (unsigned long)a.table_full_skip, (unsigned long)a.reports);
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
    else if (line.startsWith("vtemp ")) sensorsSetVirtualTemp(line.substring(6).toFloat());
    else if (line == "send") sendEnv(now, "manual", false);
    else if (line.length()) Serial.printf("{\"type\":\"warn\",\"msg\":\"unknown command: %s\"}\n", line.c_str());
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
  Serial.printf("{\"type\":\"boot\",\"node\":%u,\"boot\":%u,\"mode\":\"%s\",\"anchor\":%s}\n", NODE_ID,
                nodeBootId(), modeName(), ANCHOR_ENABLE ? "true" : "false");
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
