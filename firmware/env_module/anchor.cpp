#include "anchor.h"
#include "anchor_logic.h"
#include "config.h"
#include "out.h"
#include "ble_tx.h"
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

static AnchorTable s_table;
static AnchorStats s_stats = {};
// 스캔 콜백은 BLE 태스크에서 돌기 때문에 표 접근을 잠근다.
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static BLEScan* s_scan = nullptr;
static volatile bool s_scanning = false;
static bool s_scanRetryPending = false;
static uint32_t s_scanRetryAt = 0;
static uint32_t s_scanStartedAt = 0;
static uint32_t s_lastReport = 0;
static bool s_enabled = true;
static volatile bool s_testMode = false;
static bool s_queueWait = false;  // 큐 자리가 없어 보고를 미루는 중
static uint32_t s_queueRetryAt = 0;

class ScanCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice dev) override {
    s_stats.rx_total++;
    if (!dev.haveManufacturerData()) return;
    String md = dev.getManufacturerData();
    PktHeader h;
    const AdvVerdict v = anchorClassify(reinterpret_cast<const uint8_t*>(md.c_str()), md.length(), s_testMode, &h);
    if (v == ADV_RELAYED) s_stats.rx_relayed_skip++;
    else if (v == ADV_SIM_SKIPPED) s_stats.rx_simulation_skip++;
    if (v != ADV_ACCEPT && v != ADV_ACCEPT_SIM) return;
    const bool sim = v == ADV_ACCEPT_SIM;
    if (sim) s_stats.rx_simulation++;
    const int rssi = dev.getRSSI();
    portENTER_CRITICAL(&s_mux);
    const bool ok = s_table.record(h.node_id, sim, h.boot_id, h.seq, rssi, millis());
    portEXIT_CRITICAL(&s_mux);
    if (ok) s_stats.rx_soldier++;
    else s_stats.table_full_skip++;
  }
};

static ScanCallbacks s_callbacks;

static void onScanDone(BLEScanResults) { s_scanning = false; }

void anchorBegin() {
  s_scan = BLEDevice::getScan();
  s_scan->setAdvertisedDeviceCallbacks(&s_callbacks, true);  // 광고 이벤트마다 RSSI 표본
  s_scan->setActiveScan(false);  // 패시브: 스캔 요청을 송신하지 않음
  s_scan->setInterval(ANCHOR_SCAN_INTERVAL_MS);
  s_scan->setWindow(ANCHOR_SCAN_WINDOW_MS);
}

void anchorSetEnabled(bool on) {
  if (on == s_enabled || !s_scan) return;
  s_enabled = on;
  if (on) return;  // 다음 anchorLoop에서 스캔 시작
  if (s_scanning) s_scan->stop();  // Bluedroid: stop()에는 끝 콜백이 오지 않으므로 직접 표시
  s_scanning = false;
  s_scanRetryPending = false;
  portENTER_CRITICAL(&s_mux);
  s_table.clear();
  portEXIT_CRITICAL(&s_mux);
}

bool anchorEnabled() { return s_enabled && s_scan; }

void anchorSetTestMode(bool on) {
  s_testMode = on;
  if (on) return;
  portENTER_CRITICAL(&s_mux);
  s_table.clearSim();  // 가상 관측은 시험이 끝나면 보고하지 않는다
  portEXIT_CRITICAL(&s_mux);
}

bool anchorTestMode() { return s_testMode; }

void anchorLoop(uint32_t now) {
  if (!s_enabled || !s_scan) return;
  // 스택이 스캔 시작 실패를 알리지 않으면 끝 콜백이 오지 않아 영영 멈춘다(BLE 라이브러리는 로그만 남김)
  if (s_scanning && now - s_scanStartedAt > ANCHOR_SCAN_CYCLE_S * 1000UL + ANCHOR_SCAN_WATCHDOG_MS) {
    s_scan->stop();
    s_scanning = false;
    s_stats.scan_restarts++;
  }
  if (!s_scanning && (!s_scanRetryPending || (int32_t)(now - s_scanRetryAt) >= 0)) {
    s_scan->clearResults();
    s_scanning = s_scan->start(ANCHOR_SCAN_CYCLE_S, onScanDone, false);
    s_scanStartedAt = now;
    s_scanRetryPending = !s_scanning;
    if (s_scanRetryPending) s_scanRetryAt = now + ANCHOR_SCAN_RETRY_MS;
  }

  if (now - s_lastReport < ANCHOR_MIN_REPORT_MS) return;  // 보고 묶음 사이 최소 간격(제한된 주기로 묶음)
  if (s_queueWait && (int32_t)(now - s_queueRetryAt) < 0) return;

  AnchorDue due[ANCHOR_MAX_SOLDIERS];
  portENTER_CRITICAL(&s_mux);
  const uint32_t t = millis();  // 잠금 안에서 읽어야 콜백이 기록한 시각보다 늦다
  const uint8_t n = s_table.due(t, due, ANCHOR_MAX_SOLDIERS);
  portEXIT_CRITICAL(&s_mux);
  if (n == 0) return;

  // 큐 자리만큼만 보낸다. 남은 병사는 다음 차례에 먼저 나간다. 사건·감지 패킷용으로 몇 칸은 남긴다.
  const uint8_t freeSlots = bleTxFree();
  const uint8_t room = freeSlots > ANCHOR_TX_RESERVE ? freeSlots - ANCHOR_TX_RESERVE : 0;
  if (room < n && !s_queueWait) s_stats.queue_full_skip++;  // 미룬 묶음마다 한 번만 센다
  if (room == 0) {
    s_queueWait = true;
    s_queueRetryAt = now + ANCHOR_QUEUE_RETRY_MS;
    return;
  }
  s_queueWait = false;
  const uint8_t sent = n < room ? n : room;
  for (uint8_t i = 0; i < sent; i++) {
    PktAnchorObs p = {};
    fillAnchorObs(p, due[i].obs, elapsedMs(millis(), due[i].obs.last_ms));
    outAnchorObs(p, due[i].obs.sim ? PKT_FLAG_SIMULATION : 0);  // 가상 원본 관측은 simulation
    s_stats.reports++;
  }
  portENTER_CRITICAL(&s_mux);
  s_table.markReported(due, sent, t);
  portEXIT_CRITICAL(&s_mux);
  s_lastReport = now;
}

const AnchorStats& anchorStats() { return s_stats; }
