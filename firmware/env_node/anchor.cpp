#include "anchor.h"
#include "config.h"
#include "packet.h"
#include "node.h"
#include "json_out.h"
#include "ble_tx.h"
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

struct SoldierObs {
  bool     used;
  uint8_t  id;
  uint16_t boot_id;
  uint16_t last_seq;
  int8_t   rssi_last;
  float    rssi_avg;
  uint8_t  samples;   // 직전 보고 이후
  uint32_t last_ms;
  bool     reported;
  int8_t   reported_avg;
};

static_assert(ANCHOR_STALE_MS <= 0xFFFF, "age_ms(16bit)가 ANCHOR_STALE_MS를 담지 못함");

static SoldierObs s_tab[ANCHOR_MAX_SOLDIERS];
static AnchorStats s_stats = {};
// 스캔 콜백은 BLE 태스크에서 돌기 때문에 표 접근을 잠근다.
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static BLEScan* s_scan = nullptr;
static volatile bool s_scanning = false;
static uint32_t s_scanRetryAt = 0;
static uint32_t s_lastReport = 0;
static uint32_t s_holdUntil = 0;  // 큐가 가득 차 미룬 보고의 재시도 시각

// now가 then보다 앞서면(다른 태스크가 더 늦은 millis()를 기록) 0으로 본다
static uint32_t elapsedMs(uint32_t now, uint32_t then) {
  int32_t d = (int32_t)(now - then);
  return d > 0 ? (uint32_t)d : 0;
}

static void recordSoldier(uint8_t id, uint16_t boot, uint16_t seq, int rssi, uint32_t now) {
  portENTER_CRITICAL(&s_mux);
  SoldierObs* o = nullptr;
  SoldierObs* freeSlot = nullptr;
  for (auto& s : s_tab) {
    if (s.used && s.id == id) { o = &s; break; }
    // 빈 칸이 없으면 오래 안 보인 병사 칸을 재사용한다
    bool reusable = !s.used || elapsedMs(now, s.last_ms) > 2 * ANCHOR_STALE_MS;
    if (reusable && !freeSlot) freeSlot = &s;
  }
  if (!o && freeSlot) {
    o = freeSlot;
    *o = {};
    o->used = true;
    o->id = id;
    o->rssi_avg = rssi;
  }
  if (!o) {
    s_stats.table_full_skip++;
  } else {
    if (o->boot_id != boot) {
      o->boot_id = boot;  // 재부팅: seq가 다시 시작하므로 평활값만 유지
    }
    o->last_seq = seq;
    o->rssi_last = rssi;
    o->rssi_avg += ANCHOR_RSSI_ALPHA * (rssi - o->rssi_avg);
    if (o->samples < 255) o->samples++;
    o->last_ms = now;
    s_stats.rx_soldier++;
  }
  portEXIT_CRITICAL(&s_mux);
}

class ScanCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice dev) override {
    s_stats.rx_total++;
    if (!dev.haveManufacturerData()) return;
    String md = dev.getManufacturerData();
    if (md.length() < 2 + sizeof(PktHeader)) return;
    const uint8_t* b = reinterpret_cast<const uint8_t*>(md.c_str());
    if ((uint16_t)(b[0] | (b[1] << 8)) != PKT_COMPANY_ID) return;

    PktHeader h;
    memcpy(&h, b + 2, sizeof(h));
    if (pktVersion(h) != PKT_VERSION) return;
    uint8_t type = pktType(h);
    if (type != PKT_SOLDIER_STATUS && type != PKT_GPS && type != PKT_EVENT) return;
    if (h.node_id < 0x01 || h.node_id > 0x1F) return;  // 병사 노드(halo_*)만
    if (h.flags & PKT_FLAG_RELAYED) {  // 중계된 패킷으로 관측을 만들지 않는다
      s_stats.rx_relayed_skip++;
      return;
    }
    if (h.flags & PKT_FLAG_SIMULATION) {  // 실제 앵커는 실제 병사 패킷만 관측한다
      s_stats.rx_simulation_skip++;
      return;
    }
    recordSoldier(h.node_id, h.boot_id, h.seq, dev.getRSSI(), millis());
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

// 보고에 실린 병사를 보고 완료로 표시한다. 보고 뒤에 받은 표본 수는 남긴다.
static void markReported(const SoldierObs* snap, uint8_t n) {
  portENTER_CRITICAL(&s_mux);
  for (uint8_t i = 0; i < n; i++) {
    for (auto& o : s_tab) {
      if (!o.used || o.id != snap[i].id) continue;
      o.reported = true;
      o.reported_avg = (int8_t)lroundf(snap[i].rssi_avg);
      o.samples = o.samples > snap[i].samples ? o.samples - snap[i].samples : 0;
    }
  }
  portEXIT_CRITICAL(&s_mux);
}

// 병사마다 관측 패킷 하나(각자 seq). 모두 큐에 넣을 수 있을 때만 보내고, 자리가 없으면 seq를 쓰지 않고 false.
// rssi_dbm은 마지막으로 직접 받은 패킷(observed_seq)의 값이다. 평활은 서버가 한다.
static bool sendReports(const SoldierObs* snap, uint8_t n, uint32_t now) {
  if (bleTxFree() < n) {
    s_stats.queue_full_skip++;
    return false;
  }
  for (uint8_t i = 0; i < n; i++) {
    const SoldierObs& o = snap[i];
    PktAnchorObs p = {};
    nodeFillHeader(p.h, PKT_ANCHOR_OBS, 0);  // 실제 관측이므로 항상 device
    uint32_t age = elapsedMs(now, o.last_ms);
    p.observed_node = o.id;
    p.observed_boot = o.boot_id;
    p.observed_seq = o.last_seq;
    p.rssi_dbm = o.rssi_last;
    p.age_ms = age > 0xFFFF ? 0xFFFF : age;
    bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), 1);  // 자리는 위에서 확인
    s_stats.reports++;
    printAnchorObsJson(p);
  }
  markReported(snap, n);
  return true;
}

void anchorLoop(uint32_t now) {
  if (!s_scanning && (int32_t)(now - s_scanRetryAt) >= 0) {
    s_scan->clearResults();
    s_scanning = s_scan->start(ANCHOR_SCAN_CYCLE_S, onScanDone, false);
    if (!s_scanning) s_scanRetryAt = now + ANCHOR_SCAN_RETRY_MS;
  }

  if (now - s_lastReport < ANCHOR_MIN_REPORT_MS || (int32_t)(now - s_holdUntil) < 0) return;

  SoldierObs snap[ANCHOR_MAX_SOLDIERS];
  uint8_t n = 0;
  bool changed = false;

  portENTER_CRITICAL(&s_mux);
  // 잠금 안에서 시각을 읽어야 콜백이 기록한 last_ms보다 늦은 값이 보장된다
  uint32_t t = millis();
  for (const auto& o : s_tab) {
    if (!o.used || elapsedMs(t, o.last_ms) > ANCHOR_STALE_MS) continue;
    int8_t avg = (int8_t)lroundf(o.rssi_avg);
    if (!o.reported || abs(avg - o.reported_avg) >= ANCHOR_RSSI_DELTA_DB) changed = true;
    snap[n++] = o;
  }
  portEXIT_CRITICAL(&s_mux);

  bool periodic = n > 0 && now - s_lastReport >= ANCHOR_MAX_REPORT_MS;
  if (!changed && !periodic) return;
  if (sendReports(snap, n, t)) s_lastReport = now;
  else s_holdUntil = now + ANCHOR_MIN_REPORT_MS;
}

const AnchorStats& anchorStats() { return s_stats; }
