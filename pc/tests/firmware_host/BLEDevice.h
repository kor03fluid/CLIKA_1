// PC 시험용 BLE 대체: 광고를 시작할 때마다 제조사 데이터를 기록한다(ble_tx.cpp 송신 순서 확인용).
#pragma once
#include <Arduino.h>
#include <string>
#include <vector>

enum esp_power_level_t { ESP_PWR_LVL_N0 = 0 };
#define ADV_TYPE_NONCONN_IND 3
#define ESP_BLE_ADV_FLAG_BREDR_NOT_SPT 0x04

struct BLEAdvertisementData {
  std::string md;
  void setFlags(uint8_t) {}
  void setManufacturerData(const String& v) { md = v.s; }
};

struct BLEAdvertising {
  std::string current;
  int fail_starts = 0;               // 이만큼 start()가 실패한다
  std::vector<std::string> started;  // 시작한 광고 창의 제조사 데이터
  void setAdvertisementType(int) {}
  void setScanResponse(bool) {}
  void setMinInterval(uint16_t) {}
  void setMaxInterval(uint16_t) {}
  void setAdvertisementData(BLEAdvertisementData& d) { current = d.md; }
  bool start() {
    if (fail_starts > 0) {
      fail_starts--;
      return false;
    }
    started.push_back(current);
    return true;
  }
  bool stop() { return true; }
};

extern BLEAdvertising g_adv;

struct BLEDevice {
  static void setPower(esp_power_level_t) {}
  static BLEAdvertising* getAdvertising() { return &g_adv; }
};
