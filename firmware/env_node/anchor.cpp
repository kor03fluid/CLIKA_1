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
  bool     reported;      // 지금 보이는 동안 한 번이라도 보고했는가(사라졌다 돌아오면 false)
  int8_t   reported_avg;
  uint32_t last_report_ms;
};

static_assert(ANCHOR_STALE_MS <= 0xFFFF, "age_ms(16bit)가 ANCHOR_STALE_MS를 담지 못함");

static SoldierObs s_tab[ANCHOR_MAX_SOLDIERS];
static AnchorStats s_stats = {};
// 스캔 콜백은 BLE 태스크에서 돌기 때문에 표 접근을 잠근다.
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static BLEScan* s_scan = nullptr;
static volatile bool s_scanning = false;
static bool s_scanRetryPending = false;  // 시작 실패 후 기다리는 중(0에서 시작하는 시각 비교는 24.8일 뒤 뒤집힘)
static uint32_t s_scanRetryAt = 0;
static uint32_t s_lastReport = 0;
static bool s_enabled = true;
static uint32_t s_scanStartedAt = 0;
static bool s_queueWait = false;  // 큐 자리가 없어 보고를 미루는 중
static uint32_t s_queueRetryAt = 0;

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

// 보고할 차례인 병사: 아직 보고 안 함 > RSSI 평균이 크게 바뀜 > 마지막 보고가 오래됨 순서
struct Due {
  SoldierObs obs;
  uint8_t rank;      // 0 새로 보임, 1 변화, 2 주기
  uint32_t waited;   // 마지막 보고 후 경과
};

static void sendOne(const SoldierObs& o) {
  PktAnchorObs p = {};
  nodeFillHeader(p.h, PKT_ANCHOR_OBS, 0);  // 실제 관측이므로 항상 device
  uint32_t age = elapsedMs(p.h.uptime_ms, o.last_ms);  // 이 패킷의 uptime_ms 기준(서버가 수신 시각에서 뺀다)
  p.observed_node = o.id;
  p.observed_boot = o.boot_id;
  p.observed_seq = o.last_seq;
  p.rssi_dbm = o.rssi_last;  // 마지막으로 직접 받은 패킷(observed_seq)의 RSSI. 평활은 서버가 한다
  p.age_ms = age > 0xFFFF ? 0xFFFF : age;
  bleTxQueue(reinterpret_cast<const uint8_t*>(&p), sizeof(p), 1);  // 자리는 부르는 쪽이 확인
  s_stats.reports++;
  printAnchorObsJson(p);
}

void anchorSetEnabled(bool on) {
  if (on == s_enabled || !s_scan) return;
  s_enabled = on;
  if (on) return;  // 다음 anchorLoop에서 스캔 시작
  if (s_scanning) s_scan->stop();  // Bluedroid: stop()에는 끝 콜백이 오지 않으므로 직접 표시
  s_scanning = false;
  s_scanRetryPending = false;
  portENTER_CRITICAL(&s_mux);
  for (auto& o : s_tab) o.used = false;
  portEXIT_CRITICAL(&s_mux);
}

bool anchorEnabled() { return s_enabled && s_scan; }

void anchorLoop(uint32_t now) {
  if (!s_enabled) return;
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

  if (now - s_lastReport < ANCHOR_MIN_REPORT_MS) return;  // 보고 묶음 사이 최소 간격
  if (s_queueWait && (int32_t)(now - s_queueRetryAt) < 0) return;

  Due due[ANCHOR_MAX_SOLDIERS];
  uint8_t n = 0;
  portENTER_CRITICAL(&s_mux);
  // 잠금 안에서 시각을 읽어야 콜백이 기록한 last_ms보다 늦은 값이 보장된다
  uint32_t t = millis();
  for (auto& o : s_tab) {
    if (!o.used) continue;
    uint32_t age = elapsedMs(t, o.last_ms);
    if (age > ANCHOR_STALE_MS) {
      o.reported = false;                              // 돌아오면 새로 보인 것으로 바로 보고
      if (age > 2 * ANCHOR_STALE_MS) o.used = false;   // 오래된 칸은 비워 둔다
      continue;
    }
    int8_t avg = (int8_t)lroundf(o.rssi_avg);
    uint32_t waited = elapsedMs(t, o.last_report_ms);
    uint8_t rank;
    if (!o.reported) rank = 0;
    else if (abs(avg - o.reported_avg) >= ANCHOR_RSSI_DELTA_DB) rank = 1;
    else if (waited >= ANCHOR_MAX_REPORT_MS) rank = 2;
    else continue;
    due[n++] = {o, rank, waited};
  }
  portEXIT_CRITICAL(&s_mux);
  if (n == 0) return;

  // 큐 자리만큼만 보낸다(병사 수가 큐보다 많아도 멈추지 않음). 남은 병사는 다음 차례에 먼저 나간다.
  // 사건·감지 패킷이 바로 들어갈 수 있게 몇 칸은 남겨 둔다.
  uint8_t freeSlots = bleTxFree();
  uint8_t room = freeSlots > ANCHOR_TX_RESERVE ? freeSlots - ANCHOR_TX_RESERVE : 0;
  if (room < n && !s_queueWait) s_stats.queue_full_skip++;  // 미룬 묶음마다 한 번만 센다
  if (room == 0) {
    s_queueWait = true;  // loop마다 표를 다시 훑지 않고 잠시 뒤에 본다
    s_queueRetryAt = now + ANCHOR_QUEUE_RETRY_MS;
    return;
  }
  s_queueWait = false;
  for (uint8_t i = 1; i < n; i++) {  // 우선순위 정렬(작은 배열이라 삽입 정렬)
    Due d = due[i];
    int j = i - 1;
    while (j >= 0 && (due[j].rank > d.rank || (due[j].rank == d.rank && due[j].waited < d.waited))) {
      due[j + 1] = due[j];
      j--;
    }
    due[j + 1] = d;
  }
  uint8_t sent = n < room ? n : room;
  for (uint8_t i = 0; i < sent; i++) sendOne(due[i].obs);

  // 보낸 병사만 보고 완료로 표시한다. 보고 뒤에 받은 표본 수는 남긴다.
  portENTER_CRITICAL(&s_mux);
  for (uint8_t i = 0; i < sent; i++) {
    for (auto& o : s_tab) {
      if (!o.used || o.id != due[i].obs.id) continue;
      o.reported = true;
      o.reported_avg = (int8_t)lroundf(due[i].obs.rssi_avg);
      o.samples = o.samples > due[i].obs.samples ? o.samples - due[i].obs.samples : 0;
      o.last_report_ms = t;
    }
  }
  portEXIT_CRITICAL(&s_mux);
  s_lastReport = now;
}

const AnchorStats& anchorStats() { return s_stats; }
