// SQUAD LINK 환경 모듈 펌웨어 (ESP32 WROOM) — 기획서 5장 "환경 모듈과 예비 모듈", 담당 팀원 C
//
// 데이터 흐름(기획서 3장·10장, 공통 데이터 규격 v1 2장)
//   보드 센서 값(기본 가상) → 공통 판단(env_logic) → 검사 → BLE 광고(부록 A, B의 무선 규격) + USB JSON 한 줄(규격 v1)
//   USB JSON은 PC의 C 시험 서버가 받아 다시 검사·중복 제거하고, 통과한 가상 데이터만 팀장 관제 서버로 넘긴다.
//   환경 노드 무선 패킷은 게이트웨이(B)가 같은 JSON으로 바꾼다.
//
// 구성(기획서 10장: 보드별 입력·출력 코드와 공통 상태 판단 코드를 분리)
//   공통 판단(Arduino 없음, PC에서 시험): env_logic.*  anchor_logic.*  json_out.*  packet.h
//   보드 입출력(ESP32): io_sensors.*  ble_tx.*  anchor.*  out.*  settings.*  ident.*  이 파일
//
// 태스크: 센싱(sense, 20ms) · 보고 루프(loop: 정책·송신·앵커 보고·명령) · BLE 스캔 콜백(BLE 태스크)
// USB에는 규격 JSON 줄만 나간다. 진단 줄("# {...}")은 "diag on"일 때와 직접 보낸 명령의 응답일 때만 나간다.
#include <Arduino.h>
#include <BLEDevice.h>
#include <esp_system.h>
#include "config.h"
#include "packet.h"
#include "settings.h"
#include "ident.h"
#include "json_out.h"
#include "env_logic.h"
#include "io_sensors.h"
#include "ble_tx.h"
#include "anchor.h"
#include "out.h"

#ifndef ARDUINO_RUNNING_CORE
#define ARDUINO_RUNNING_CORE 1
#endif

static ReportPolicy s_policy;
static bool s_heatPending = false;
static bool s_heatPendingSim = false;  // 사건이 생긴 순간의 출처(대기 중에 vtemp off 해도 가상으로 남게)
static uint16_t s_eventNo[5] = {};     // EventType별 사건 번호(부팅마다 1부터)

static TaskHandle_t s_senseTask = nullptr;
static volatile uint32_t s_senseMaxMs = 0;
static volatile uint32_t s_senseOverruns = 0;
static uint32_t s_loopMaxMs = 0;
static uint32_t s_loopOverruns = 0;

static uint32_t s_autostatsMs = 0;
static uint32_t s_nextAutostats = 0;
static const char* s_profile = nullptr;  // 송신량·전력 비교 구간 이름("base" 스캔 끔 / "full" 스캔 켬)
static uint32_t s_lastBlocked = 0;

static bool s_checkRunning = false;
static uint32_t s_checkEnd = 0;
static IoSensorStats s_checkStart = {};

// ----- 진단 줄 ("# {...}", 데이터 스트림 아님) -----
static void diagBegin(const char* type) {
  char name[16];
  identName(name, sizeof(name));
  Serial.printf("# {\"type\":\"%s\",\"node_id\":\"%s\",\"boot_id\":\"boot_%04x\"", type, name, identBootId());
}

// 사용자가 친 글자를 넣으므로 따옴표·역슬래시·제어문자를 바꿔 쓴다.
static String safeText(const String& s) {
  String out;
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    out += (c == '"' || c == '\\' || (uint8_t)c < 0x20) ? '_' : c;
  }
  return out;
}

// reply: 직접 보낸 명령의 응답(항상 낸다). 아니면 "diag on"일 때만.
static void warn(const char* msg, const String& detail, bool reply) {
  if (!reply && !settings().diag) return;
  diagBegin("warn");
  Serial.printf(",\"msg\":\"%s\",\"detail\":\"%s\"}\n", msg, safeText(detail).c_str());
}

static void ok(const String& cmd) {
  diagBegin("ok");
  Serial.printf(",\"cmd\":\"%s\"}\n", safeText(cmd).c_str());
}

static const char* modeName() { return s_policy.adaptive() ? "adaptive" : "fixed"; }
static const char* boolText(bool v) { return v ? "true" : "false"; }

static String useList(uint8_t mask) {
  String s = "[";
  const char* names[4] = {"sound", "flame", "shock", "reed"};
  bool first = true;
  for (int i = 0; i < 4; i++) {
    if (!(mask & (1 << i))) continue;
    if (!first) s += ",";
    s += "\"";
    s += names[i];
    s += "\"";
    first = false;
  }
  return s + "]";
}

static String vtempText() {
  const float v = sensorsVirtualTemp();
  return isnan(v) ? String("null") : String(v, 1);
}

static const char* resetReason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_EXT: return "external";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "int_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt";
    case ESP_RST_WDT: return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";  // USB 전원이 스캔·송신 부하를 못 버틴 경우도 여기
    default: return "other";
  }
}

// 시험 조건 기록(팀장 지시 6: 시험 조건·수신 건수·오류). 키 이름은 C 시험 서버·report.py와 같다.
static void printConditions() {
  Serial.printf(",\"fw\":\"%s/%s\",\"tx_mode\":\"%s\",\"anchor_enabled\":%s,\"anchor_test\":%s,\"vsensor\":%s,"
                "\"vtemp\":%s,\"scenario\":\"%s\",\"use\":%s,\"profile\":%s%s%s,\"uptime_ms\":%lu",
                FW_NAME, FW_VERSION, modeName(), boolText(anchorEnabled()), boolText(anchorTestMode()),
                boolText(sensorsVirtualMode()), vtempText().c_str(), sensorsScenarioPhase(),
                useList(sensorsLatest().use_mask).c_str(), s_profile ? "\"" : "", s_profile ? s_profile : "null",
                s_profile ? "\"" : "", (unsigned long)millis());
}

static void printStats() {
  const TxStats& t = bleTxStats();
  const AnchorStats& a = anchorStats();
  const IoSensorStats ss = sensorsStats();
  const OutStats& o = outStats();
  diagBegin("stats");
  printConditions();
  Serial.printf(",\"tx\":{\"packets\":%lu,\"windows\":%lu,\"window_ms\":%lu,\"payload_bytes\":%lu,\"dropped\":%lu,"
                "\"adv_fail\":%lu,\"environment\":%lu,\"event\":%lu,\"anchor_observation\":%lu,\"anchor_bytes\":%lu}",
                (unsigned long)t.packets, (unsigned long)t.windows, (unsigned long)t.window_ms,
                (unsigned long)t.payload_bytes, (unsigned long)t.dropped, (unsigned long)t.adv_fail,
                (unsigned long)t.by_type[PKT_ENVIRONMENT], (unsigned long)t.by_type[PKT_EVENT],
                (unsigned long)t.by_type[PKT_ANCHOR_OBS], (unsigned long)t.bytes_by_type[PKT_ANCHOR_OBS]);
  Serial.printf(",\"anchor\":{\"rx_total\":%lu,\"rx_soldier\":%lu,\"rx_relayed_skip\":%lu,\"rx_simulation_skip\":%lu,"
                "\"rx_simulation\":%lu,\"table_full_skip\":%lu,\"reports\":%lu,\"queue_full_skip\":%lu,"
                "\"scan_restarts\":%lu}",
                (unsigned long)a.rx_total, (unsigned long)a.rx_soldier, (unsigned long)a.rx_relayed_skip,
                (unsigned long)a.rx_simulation_skip, (unsigned long)a.rx_simulation, (unsigned long)a.table_full_skip,
                (unsigned long)a.reports, (unsigned long)a.queue_full_skip, (unsigned long)a.scan_restarts);
  Serial.printf(",\"out\":{\"lines\":%lu,\"blocked\":%lu},\"sense\":{\"polls\":%lu,\"max_ms\":%lu,\"overruns\":%lu,"
                "\"dht_reads\":%lu,\"dht_fails\":%lu},\"loop\":{\"max_ms\":%lu,\"overruns\":%lu}}\n",
                (unsigned long)o.lines, (unsigned long)o.blocked, (unsigned long)ss.polls,
                (unsigned long)s_senseMaxMs, (unsigned long)s_senseOverruns, (unsigned long)ss.dht_reads,
                (unsigned long)ss.dht_fails, (unsigned long)s_loopMaxMs, (unsigned long)s_loopOverruns);
}

static void printBoot() {
  diagBegin("boot");
  Serial.printf(",\"fw\":\"%s/%s\",\"tx_mode\":\"%s\",\"anchor\":%s,\"anchor_test\":%s,\"vsensor\":%s,\"use\":%s,"
                "\"board\":\"%s\",\"reset\":\"%s\",\"schema_version\":\"1.0\"}\n",
                FW_NAME, FW_VERSION, modeName(), boolText(anchorEnabled()), boolText(anchorTestMode()),
                boolText(sensorsVirtualMode()), useList(sensorsLatest().use_mask).c_str(), BOARD_NAME, resetReason());
}

static void printConfig() {
  char running[16], saved[16];
  nodeName(identNodeId(), running, sizeof(running));
  nodeName(settingsSavedNodeId(), saved, sizeof(saved));
  const Settings& s = settings();
  diagBegin("config");
  Serial.printf(",\"saved_node_id\":\"%s\",\"running_node_id\":\"%s\",\"sensors\":\"%s\",\"real_use\":%s,"
                "\"anchor\":%s,\"tx_mode\":\"%s\",\"diag\":%s,\"scenario\":%s,\"fw\":\"%s/%s\"}\n",
                saved, running, s.virtual_sensors ? "virtual" : "real", useList(s.use_mask).c_str(),
                boolText(s.anchor), s.adaptive ? "adaptive" : "fixed", boolText(s.diag), boolText(sensorsScenario()),
                FW_NAME, FW_VERSION);
}

static void printHelp() {
  diagBegin("help");
  Serial.print(",\"commands\":\"stats | config | check | id [env_NN] | sensors virtual|real | use [sound|flame|shock|reed|all|none] "
               "[on|off] | anchor on|off | anchor test on|off | mode fixed|adaptive | diag on|off | scenario [on|off] | "
               "vdetect sound|flame|shock|reed | vtemp <C>|off | profile base|full | autostats <s> | send | reboot | factory\"}\n");
}

// ----- environment -----
static void sendEnv(uint32_t now, SendKind kind) {
  static bool warnedFull = false;
  if (bleTxFree() == 0) {  // 큐가 비면 다음 루프에서 다시. 감지 래치와 seq는 그대로 둔다.
    if (!warnedFull) warn("tx queue full", "environment", false);
    warnedFull = true;
    return;
  }
  warnedFull = false;
  const EnvReading r = sensorsLatest();
  const uint8_t det = sensorsTakeDetections();
  PktEnvironment p = buildEnvironment(r, det, s_policy.declaredIntervalMs(r));
  const bool urgent = kind == SEND_URGENT;
  uint8_t flags = urgent ? PKT_FLAG_EVENT : 0;
  if (r.simulated) flags |= PKT_FLAG_SIMULATION;
  outEnvironment(p, flags, urgent ? EVENT_REPEATS : 1, urgent);  // 자리는 위에서 확인
  s_policy.markSent(now, kind, p);
}

// ----- event (환경 열 노출 주의: 환경 노드가 만들고 서버는 받기만 한다, 2026-10-10 팀장 확정) -----
static bool sendEvent(uint8_t type, bool simulation) {
  PktEvent p = {};
  p.event_type = type;
  p.mode = MODE_NORMAL;  // 환경 노드에는 기도비닉 모드가 없다
  p.event_no = s_eventNo[type] + 1;
  if (!outEvent(p, PKT_FLAG_EVENT | (simulation ? PKT_FLAG_SIMULATION : 0))) return false;  // 큐 가득: 다음 루프에서
  s_eventNo[type]++;
  return true;
}

static void envTxPolicy(uint32_t now) {
  bool sim = false;
  if (sensorsTakeHeatOnset(&sim)) {
    s_heatPending = true;
    s_heatPendingSim = sim;
  }
  if (s_heatPending && sendEvent(EV_HEAT_EXPOSURE, s_heatPendingSim)) s_heatPending = false;
  const SendKind k = s_policy.decide(now, sensorsLatest(), sensorsPendingDetections());
  if (k != SEND_NONE) sendEnv(now, k);
}

// ----- 배선 점검 -----
static void startCheck(uint32_t now) {
  s_checkStart = sensorsStats();
  sensorsRequestLightMv();
  s_checkEnd = now + CHECK_WATCH_MS;
  s_checkRunning = true;
}

static void finishCheck() {
  s_checkRunning = false;
  const IoSensorStats st = sensorsStats();
  const bool virt = sensorsVirtualMode();
  CheckInput in = {};
  in.virtual_mode = virt;
  in.real_use = sensorsRealUse();
  in.light_mv_valid = st.light_mv_seq != s_checkStart.light_mv_seq;
  in.light_mv = st.light_mv;
  in.dht_fail_run = sensorsDhtFailRun();
  in.dht_reads = st.dht_reads - s_checkStart.dht_reads;
  in.dht_fails = st.dht_fails - s_checkStart.dht_fails;
  in.sound_active = digitalRead(PIN_SOUND) == SOUND_ACTIVE_LEVEL;
  in.flame_active = digitalRead(PIN_FLAME) == FLAME_ACTIVE_LEVEL;
  in.shock_active = digitalRead(PIN_SHOCK) == SHOCK_ACTIVE_LEVEL;
  in.sound_edges = st.sound_edges - s_checkStart.sound_edges;
  in.flame_edges = st.flame_edges - s_checkStart.flame_edges;
  in.shock_edges = st.shock_edges - s_checkStart.shock_edges;
  const bool reedClosed = digitalRead(PIN_REED) != REED_OPEN_LEVEL;
  const char* warns[12];
  const uint8_t n = checkEvaluate(in, warns, 12);
  diagBegin("check");
  Serial.printf(",\"sensors\":\"%s\",\"light_pin_mv\":%u,\"dht_fail_run\":%u,\"dht_reads\":%lu,\"dht_fails\":%lu,"
                "\"pins\":{\"sound\":{\"active\":%s,\"edges\":%lu},\"flame\":{\"active\":%s,\"edges\":%lu},"
                "\"shock\":{\"active\":%s,\"edges\":%lu},\"reed_closed\":%s},\"warnings\":[",
                virt ? "virtual" : "real", (unsigned)in.light_mv, (unsigned)in.dht_fail_run,
                (unsigned long)in.dht_reads, (unsigned long)in.dht_fails, boolText(in.sound_active),
                (unsigned long)in.sound_edges, boolText(in.flame_active), (unsigned long)in.flame_edges,
                boolText(in.shock_active), (unsigned long)in.shock_edges, boolText(reedClosed));
  for (uint8_t i = 0; i < n; i++) Serial.printf("%s\"%s\"", i ? "," : "", warns[i]);
  Serial.print("],\"note\":\"measure module VCC and output with a multimeter before wiring; 5V signals must not reach GPIO/ADC\"}\n");
}

// ----- 시리얼 명령 -----
// "vtemp <°C>": 숫자 전체가 올바를 때만 적용한다(오타로 0°C가 들어가지 않게).
static void setVirtualTempCommand(const String& line, const char* arg) {
  char* end = nullptr;
  const float v = strtof(arg, &end);
  if (end == arg || *end != '\0' || !isfinite(v) || v < -40.0f || v > 100.0f) {
    warn("vtemp needs a number between -40 and 100, or off", String(arg), true);
    return;
  }
  sensorsSetVirtualTemp(v);
  ok(line);
}

static uint8_t sensorBit(const String& name) {
  return name == "sound" ? DET_SOUND : name == "flame" ? DET_FLAME : name == "shock" ? DET_SHOCK
       : name == "reed" ? DET_REED : 0;
}

static void useCommand(const String& line, const String& arg) {
  uint8_t mask = settings().use_mask;
  if (arg == "all") mask = DET_ALL;
  else if (arg == "none") mask = 0;
  else {
    const int sp = arg.indexOf(' ');
    const uint8_t bit = sensorBit(sp > 0 ? arg.substring(0, sp) : String(""));
    const String onoff = sp > 0 ? arg.substring(sp + 1) : String("");
    if (!bit || (onoff != "on" && onoff != "off")) {
      warn("use needs sound|flame|shock|reed on|off, all or none", arg, true);
      return;
    }
    mask = onoff == "on" ? (mask | bit) : (mask & ~bit);
  }
  settingsSetUse(mask);
  sensorsSetRealUse(mask);
  if (sensorsVirtualMode()) warn("saved; applies in real sensor mode (virtual mode reports all six sensors)", line, true);
  else ok(line);
}

static void setProfile(const char* name, bool scan) {
  printStats();  // 앞 구간 끝
  anchorSetEnabled(scan);  // 구간 비교용(저장하지 않음. 저장하려면 "anchor on|off")
  s_profile = name;
  printStats();  // 새 구간 시작
}

static void restartSoon() {
  Serial.flush();
  delay(100);
  ESP.restart();
}

static void handleLine(uint32_t now, const String& line) {
  if (line == "stats") printStats();
  else if (line == "config") printConfig();
  else if (line == "help") printHelp();
  else if (line == "check") startCheck(now);
  else if (line == "id") printConfig();
  else if (line.startsWith("id ")) {
    uint8_t id = 0;
    if (!parseEnvNodeName(line.c_str() + 3, &id)) {
      warn("id needs env_01..env_15 (Appendix A: 0x31..0x3F)", line.substring(3), true);
      return;
    }
    settingsSetNodeId(id);
    printConfig();
    if (id != identNodeId()) restartSoon();  // 새 ID·새 boot_id로 다시 시작(규격 4장)
  } else if (line == "sensors virtual" || line == "vsensor on") {
    settingsSetVirtual(true);
    sensorsSetVirtualMode(true);
    ok(line);
  } else if (line == "sensors real" || line == "vsensor off") {
    settingsSetVirtual(false);
    sensorsSetVirtualMode(false);
    ok(line);
  } else if (line == "use") printConfig();
  else if (line.startsWith("use ")) useCommand(line, line.substring(4));
  else if (line == "anchor on" || line == "anchor off") {
    const bool on = line == "anchor on";
    settingsSetAnchor(on);
    anchorSetEnabled(on);
    s_profile = nullptr;
    ok(line);
  } else if (line == "anchor test on" || line == "anchor test off") {
    anchorSetTestMode(line == "anchor test on");
    ok(line);
  } else if (line == "mode fixed" || line == "mode adaptive") {
    const bool adaptive = line == "mode adaptive";
    settingsSetAdaptive(adaptive);
    s_policy.setAdaptive(adaptive);
    ok(line);
  } else if (line == "diag on" || line == "diag off") {
    settingsSetDiag(line == "diag on");
    ok(line);
  } else if (line == "scenario") {
    diagBegin("scenario");
    Serial.printf(",\"scenario\":%s,\"phase\":\"%s\"}\n", boolText(sensorsScenario()), sensorsScenarioPhase());
  } else if (line == "scenario on" || line == "scenario off") {
    sensorsSetScenario(line == "scenario on");
    ok(line);
  } else if (line.startsWith("vdetect ")) {
    const uint8_t bit = sensorBit(line.substring(8));
    if (!bit) warn("vdetect needs sound, flame, shock or reed", line.substring(8), true);
    else if (!sensorsInject(bit)) warn("vdetect works only with virtual sensors (sensors virtual)", line.substring(8), true);
    else ok(line);
  } else if (line == "vtemp off") {
    sensorsSetVirtualTemp(NAN);
    ok(line);
  } else if (line.startsWith("vtemp ")) setVirtualTempCommand(line, line.c_str() + 6);
  else if (line == "profile base") setProfile("base", false);
  else if (line == "profile full") setProfile("full", true);
  else if (line.startsWith("autostats ")) {
    const long s = line.substring(10).toInt();
    if (s < 0 || s > 3600) {
      warn("autostats needs 0..3600 seconds", line.substring(10), true);
      return;
    }
    s_autostatsMs = (uint32_t)s * 1000UL;
    s_nextAutostats = now + s_autostatsMs;
    ok(line);
  } else if (line == "send") sendEnv(now, SEND_NORMAL);
  else if (line == "reboot") restartSoon();
  else if (line == "factory") {
    settingsFactory();
    printConfig();
    restartSoon();
  } else if (line.length()) warn("unknown command (help)", line, true);
}

static void handleSerial(uint32_t now) {
  static String line;
  while (Serial.available()) {
    const char c = Serial.read();
    if (c != '\n' && c != '\r') {
      if (line.length() < 64) line += c;
      continue;
    }
    line.trim();
    handleLine(now, line);
    line = "";
  }
}

// ----- 센싱 태스크 -----
static void senseTask(void*) {
  for (;;) {
    const uint32_t t0 = millis();
    sensorsPoll(t0);
    const uint32_t d = millis() - t0;
    if (d > s_senseMaxMs) s_senseMaxMs = d;
    if (d > SENSE_OVERRUN_MS) s_senseOverruns = s_senseOverruns + 1;
    vTaskDelay(pdMS_TO_TICKS(SENSE_PERIOD_MS));
  }
}

void setup() {
  // 기본은 송신 버퍼가 없어 printf가 다 나갈 때까지 루프를 막는다. 앵커 보고 묶음이 광고 창을 늘리지 않게 버퍼를 둔다.
#if ARDUINO_USB_CDC_ON_BOOT && !ARDUINO_USB_MODE
  // 칩 자체 USB(TinyUSB CDC, Nano ESP32): 버퍼 크기 대신 쓰기 대기 시간을 줄인다(PC 연결이 없으면 바로 넘어감)
  Serial.setTxTimeoutMs(SERIAL_TX_TIMEOUT_MS);
#else
  Serial.setTxBufferSize(SERIAL_TX_BUFFER);
#endif
  Serial.begin(115200);
  settingsBegin();
  identBegin();
  BLEDevice::init("");  // 이름은 광고하지 않음(페이로드 절약)
  bleTxBegin();
  sensorsBegin(settings().virtual_sensors, settings().use_mask);
  s_policy.setAdaptive(settings().adaptive);
  anchorBegin();
  anchorSetEnabled(settings().anchor);
  xTaskCreatePinnedToCore(senseTask, "sense", SENSE_TASK_STACK, nullptr, 1, &s_senseTask, ARDUINO_RUNNING_CORE);
  if (settings().diag) printBoot();
}

void loop() {
  const uint32_t now = millis();
  envTxPolicy(now);
  anchorLoop(now);
  bleTxLoop(now);
  handleSerial(now);
  if (s_checkRunning && (int32_t)(now - s_checkEnd) >= 0) finishCheck();
  if (s_autostatsMs && (int32_t)(now - s_nextAutostats) >= 0) {  // 사용자가 켠 주기 기록
    s_nextAutostats = now + s_autostatsMs;
    printStats();
  }
  const OutStats& o = outStats();
  if (o.blocked != s_lastBlocked) {
    s_lastBlocked = o.blocked;
    warn("packet blocked by spec check", o.last_block ? o.last_block : "", false);
  }
  const uint32_t d = millis() - now;
  if (d > s_loopMaxMs) s_loopMaxMs = d;
  if (d > LOOP_OVERRUN_MS) s_loopOverruns++;
  delay(5);
}
