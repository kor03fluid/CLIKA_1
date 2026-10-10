#include "ble_tx.h"
#include "config.h"
#include "packet.h"
#include <BLEDevice.h>
#include <BLEAdvertising.h>

struct TxItem {
  uint8_t buf[PKT_MAX_PAYLOAD];
  uint8_t len;
  uint8_t windowsLeft;
  bool urgent;
};

// 레거시 광고 31B = Flags(3B) + 제조사 데이터 머리(4B) + 페이로드. 넘으면 BLE 라이브러리가 조용히 버린다.
static_assert(3 + 4 + PKT_MAX_PAYLOAD <= 31, "advertising payload exceeds 31 bytes");

static TxItem s_q[TX_QUEUE_LEN];
static uint8_t s_head = 0;
static uint8_t s_count = 0;

static BLEAdvertising* s_adv = nullptr;
static bool s_active = false;
static uint32_t s_windowEnd = 0;
static uint32_t s_nextStart = 0;
static TxStats s_stats = {};

static uint16_t msToAdvUnits(uint32_t ms) { return ms * 1000 / 625; }

void bleTxBegin() {
  BLEDevice::setPower(BLE_TX_POWER);
  s_adv = BLEDevice::getAdvertising();
  s_adv->setAdvertisementType(ADV_TYPE_NONCONN_IND);
  s_adv->setScanResponse(false);
  s_adv->setMinInterval(msToAdvUnits(TX_ADV_INTERVAL_MS));
  s_adv->setMaxInterval(msToAdvUnits(TX_ADV_INTERVAL_MS));
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
}

static TxItem& slot(uint8_t i) { return s_q[(s_head + i) % TX_QUEUE_LEN]; }

bool bleTxQueue(const uint8_t* payload, uint8_t len, uint8_t windows, bool urgent) {
  if (len > PKT_MAX_PAYLOAD || windows == 0) return false;
  if (s_count == TX_QUEUE_LEN) {
    s_stats.dropped++;
    return false;
  }
  uint8_t pos = s_count;  // 큐 안에서 들어갈 자리(0 = 맨 앞)
  if (urgent) {
    pos = s_active ? 1 : 0;  // 광고 중인 창은 끊지 않는다
    while (pos < s_count && slot(pos).urgent) pos++;
    for (uint8_t i = s_count; i > pos; i--) slot(i) = slot(i - 1);
  }
  TxItem& it = slot(pos);
  memcpy(it.buf, payload, len);
  it.len = len;
  it.windowsLeft = windows;
  it.urgent = urgent;
  s_count++;
  s_stats.packets++;
  s_stats.payload_bytes += len;
  return true;
}

static bool startWindow(const TxItem& it) {
  uint8_t md[2 + PKT_MAX_PAYLOAD];
  md[0] = PKT_COMPANY_ID & 0xFF;
  md[1] = PKT_COMPANY_ID >> 8;
  memcpy(md + 2, it.buf, it.len);

  BLEAdvertisementData data;
  data.setFlags(ESP_BLE_ADV_FLAG_BREDR_NOT_SPT);
  data.setManufacturerData(String((const char*)md, 2 + it.len));
  s_adv->setAdvertisementData(data);
  if (!s_adv->start()) return false;
  digitalWrite(PIN_LED, HIGH);
  return true;
}

void bleTxLoop(uint32_t now) {
  if (s_active) {
    if ((int32_t)(now - s_windowEnd) < 0) return;
    s_adv->stop();
    digitalWrite(PIN_LED, LOW);
    s_active = false;
    s_stats.windows++;
    s_stats.est_adv_events += TX_WINDOW_MS / TX_ADV_INTERVAL_MS;

    TxItem& it = s_q[s_head];
    if (--it.windowsLeft == 0) {
      s_head = (s_head + 1) % TX_QUEUE_LEN;
      s_count--;
      s_nextStart = now;
    } else {
      s_nextStart = now + TX_REPEAT_GAP_MS;
    }
    return;
  }

  if (s_count == 0 || (int32_t)(now - s_nextStart) < 0) return;
  if (!startWindow(s_q[s_head])) {  // 창으로 세지 않고 잠시 뒤 같은 패킷으로 다시
    s_stats.adv_fail++;
    s_nextStart = now + TX_REPEAT_GAP_MS;
    return;
  }
  s_active = true;
  s_windowEnd = now + TX_WINDOW_MS;
}

uint8_t bleTxFree() { return TX_QUEUE_LEN - s_count; }

const TxStats& bleTxStats() { return s_stats; }
