#include "anchor.h"
#include "config.h"
#include "packet.h"
#include "node.h"
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

static SoldierObs s_tab[ANCHOR_MAX_SOLDIERS];
static AnchorStats s_stats = {};
// 스캔 콜백은 BLE 태스크에서 돌기 때문에 표 접근을 잠근다.
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static BLEScan* s_scan = nullptr;
static volatile bool s_scanning = false;
static uint32_t s_lastReport = 0;

static void recordSoldier(uint8_t id, uint16_t boot, uint16_t seq, int rssi, uint32_t now) {
  portENTER_CRITICAL(&s_mux);
  SoldierObs* o = nullptr;
  SoldierObs* freeSlot = nullptr;
  for (auto& s : s_tab) {
    if (s.used && s.id == id) { o = &s; break; }
    // 빈 칸이 없으면 오래 안 보인 병사 칸을 재사용한다
    bool reusable = !s.used || now - s.last_ms > 2 * ANCHOR_STALE_MS;
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
    if (type != PKT_SOLDIER_STATUS && type != PKT_SOLDIER_POS) return;
    if (h.flags & PKT_FLAG_RELAYED) {
      s_stats.rx_relayed_skip++;
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

static void printReportJson(const PktAnchorReport& p) {
  Serial.printf("{\"type\":\"anchor\",\"anchor\":%u,\"boot\":%u,\"seq\":%u,\"obs\":[",
                p.h.node_id, p.h.boot_id, p.h.seq);
  for (uint8_t i = 0; i < p.count; i++) {
    const AnchorEntry& e = p.e[i];
    Serial.printf("%s{\"soldier\":%u,\"last_seq\":%u,\"rssi\":%d,\"rssi_avg\":%d,\"n\":%u,\"age_ms\":%u}",
                  i ? "," : "", e.soldier_id, e.last_seq, e.rssi_last, e.rssi_avg, e.samples,
                  e.age_ds * 100u);
  }
  Serial.printf("],\"ms\":%lu}\n", (unsigned long)millis());
}

static void sendReports(const SoldierObs* snap, uint8_t n, uint32_t now) {
  for (uint8_t i = 0; i < n; i += ANCHOR_ENTRIES_PER_PKT) {
    PktAnchorReport p = {};
    nodeFillHeader(p.h, PKT_ANCHOR_REPORT, 0);
    for (uint8_t k = 0; k < ANCHOR_ENTRIES_PER_PKT && i + k < n; k++) {
      const SoldierObs& o = snap[i + k];
      AnchorEntry& e = p.e[k];
      uint32_t ageDs = (now - o.last_ms) / 100;
      e.soldier_id = o.id;
      e.last_seq = o.last_seq;
      e.rssi_last = o.rssi_last;
      e.rssi_avg = (int8_t)lroundf(o.rssi_avg);
      e.samples = o.samples;
      e.age_ds = ageDs > 255 ? 255 : ageDs;
      p.count++;
    }
    if (bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), 1)) {
      s_stats.reports++;
      printReportJson(p);
    }
  }
}

void anchorLoop(uint32_t now) {
  if (!s_scanning) {
    s_scan->clearResults();
    s_scanning = s_scan->start(ANCHOR_SCAN_CYCLE_S, onScanDone, false);
  }

  if (now - s_lastReport < ANCHOR_MIN_REPORT_MS) return;

  SoldierObs snap[ANCHOR_MAX_SOLDIERS];
  uint8_t n = 0;
  bool changed = false;

  portENTER_CRITICAL(&s_mux);
  for (const auto& o : s_tab) {
    if (!o.used || now - o.last_ms > ANCHOR_STALE_MS) continue;
    int8_t avg = (int8_t)lroundf(o.rssi_avg);
    if (!o.reported || abs(avg - o.reported_avg) >= ANCHOR_RSSI_DELTA_DB) changed = true;
    snap[n++] = o;
  }
  bool periodic = n > 0 && now - s_lastReport >= ANCHOR_MAX_REPORT_MS;
  if (changed || periodic) {
    for (auto& o : s_tab) {
      if (!o.used || now - o.last_ms > ANCHOR_STALE_MS) continue;
      o.reported = true;
      o.reported_avg = (int8_t)lroundf(o.rssi_avg);
      o.samples = 0;
    }
  }
  portEXIT_CRITICAL(&s_mux);

  if (!changed && !periodic) return;
  s_lastReport = now;
  sendReports(snap, n, now);
}

const AnchorStats& anchorStats() { return s_stats; }
