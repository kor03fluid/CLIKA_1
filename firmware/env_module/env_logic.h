#pragma once
// 공통 상태 판단 코드 (기획서 10장: 보드별 입력·출력 코드와 분리).
// Arduino·ESP32 API를 쓰지 않는다. 보드 입출력 코드(io_sensors.cpp)가 넘긴 원시값으로 판단하고,
// PC에서도 그대로 빌드해 시험한다(pc/tests/test_env_module_contract.py).
//
//   VirtualBoard  보드의 6개 센서 값을 가상으로 만든다(센서 검증 전 기본). 실제 센서와 같은 RawSample 형식
//   EnvJudge      원시값(실제 또는 가상) → 측정 가능 여부·출처·열 노출 주의·감지 래치
//   ReportPolicy  고정 5초 / 적응(감지 즉시·값 변화·선언 주기)
//   buildEnvironment, check*  environment 본문을 만들고, 내보내기 전에 규격 v1 값 규칙을 다시 확인한다
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include "packet.h"

// 추가 센서 비트(켠 센서 마스크와 감지 래치에 같이 쓴다)
#define DET_SOUND 0x01
#define DET_FLAME 0x02
#define DET_SHOCK 0x04
#define DET_REED  0x08  // 감지 래치에서는 리드 열림·닫힘 변화
#define DET_ALL   0x0F

// 기획서 5장 표 → 규격 7장 필드
//   필수 DHT11  환경 공기 온도·습도. 체온 대체 불가      → air_temperature_c, humidity_pct, sensor_status.dht11
//   필수 조도   상대 밝기. 보정 없이 lux 표시하지 않음    → light_raw(ADC 원시값), sensor_status.light
//   추가 소리   큰 소리 이벤트. 총성 판별·정확한 dB 제외  → sound_detected
//   추가 불꽃   광학 반응 이벤트. 화재 확정 판정 제외     → flame_detected
//   추가 충격   설치물 자체의 충격                       → shock_detected
//   추가 리드   자석 부착 덮개 등의 열림·닫힘            → reed_closed

// 보드가 한 번 읽은 원시값(실제 센서 또는 VirtualBoard)
struct RawSample {
  uint32_t now_ms;
  bool     has_dht;      // 이번에 DHT11을 읽었는가
  float    dht_temp;     // 읽기 실패면 NAN
  float    dht_hum;
  bool     has_light;
  uint16_t light_raw;    // ADC 12bit 원시값
  bool     reed_closed;  // 리드가 닫힘 상태인가
  bool     flame_active; // 불꽃 센서가 지금 반응 중인가
  uint8_t  isr_det;      // 짧은 반응 펄스(소리·불꽃·충격, DET_*)
};

struct EnvReading {
  bool     dht_ok;       // ok ⇔ 온도·습도 모두 숫자
  float    temp_c;       // 공기 온도. 없으면 NAN
  float    humidity;     // 상대습도 %. 없으면 NAN
  bool     light_ok;
  uint16_t light_raw;
  bool     heat;         // 환경 열 노출 주의 상태(공기 온도 기준, 개인 체온 아님)
  bool     flame_now;    // 불꽃 현재 반응(켠 경우만)
  bool     reed_closed;  // 리드 닫힘(켠 경우만 의미 있음)
  bool     simulated;    // 가상 데이터(가상 센서 또는 vtemp) → source "simulation"
  bool     virtual_sensors;
  uint8_t  use_mask;     // 켜져 있던 추가 센서. 꺼진 센서는 JSON에서 필드·sensor_status 키를 모두 뺀다
};

// ----- 가상 센서 보드 -----
// 실물 센서를 확인하기 전, 보드가 6개 센서 값을 가상으로 만든다. 값은 EnvJudge·보고 정책·검사를 실제와 똑같이 거치고
// 패킷은 source "simulation"이다. 시나리오(10분 반복)는 규격의 경우를 모두 지난다:
//   큰 소리·설치물 충격 펄스, 리드 열림·닫힘, 불꽃 반응, 공기 온도 상승 → 열 노출 주의 → 해제,
//   DHT11 읽기 실패(측정 불가 null), 어두워짐(조도 원시값 변화)
class VirtualBoard {
 public:
  void begin(uint32_t now);
  void setScenario(bool on) { scenario_ = on; }
  bool scenario() const { return scenario_; }
  void inject(uint8_t det);  // 손으로 넣는 감지(시리얼 "vdetect"). 리드는 열림·닫힘 전환
  RawSample sample(uint32_t now, bool dhtDue, bool lightDue);
  static const char* phaseName(uint32_t offsetMs);  // 시나리오 구간 이름
  uint32_t offset(uint32_t now) const;              // 시나리오 안의 위치(ms)

 private:
  uint32_t start_ = 0;
  uint32_t last_ = 0;
  bool started_ = false;
  bool scenario_ = true;
  uint8_t injected_ = 0;
  bool reedManualOpen_ = false;
};

// ----- 상태 판단 -----
class EnvJudge {
 public:
  void begin(uint8_t use, bool virtualSensors, uint32_t now);
  void update(const RawSample& s);  // 새 원시값을 반영하고 다시 판단한다
  void setUse(uint8_t mask);        // 꺼진 센서의 감지는 버린다
  void setVirtualTemp(float c);     // 시험용 공기 온도(시리얼 "vtemp"). NAN이면 해제. 켜져 있으면 simulation
  // 가상 ↔ 실제 센서 전환. 두 출처의 값·감지가 한 패킷에 섞이지 않게 측정값을 비우고 새로 시작한다.
  void setVirtualSensors(bool on);
  const EnvReading& reading() const { return cur_; }
  uint8_t pending() const { return latched_; }
  uint8_t takeDetections();
  bool takeHeatOnset(bool* simulated);  // 새로 시작한 열 노출(한 번만)과 시작 순간의 출처
  float virtualTemp() const { return vtemp_; }
  bool virtualSensors() const { return vsensor_; }
  uint8_t use() const { return use_; }
  uint8_t dhtFailRun() const { return dhtFails_; }

 private:
  void judge();
  bool simulating() const { return vsensor_ || !isnan(vtemp_); }
  void simulationChanged(bool was);

  EnvReading cur_ = {};
  uint8_t use_ = 0;
  uint8_t latched_ = 0;
  bool heatOnset_ = false;
  bool heatOnsetSim_ = false;
  bool realHeat_ = false;  // 가상 시험 동안 맡아 둔 실측 열 노출 상태
  float vtemp_ = NAN;
  bool vsensor_ = false;
  bool flameActive_ = false;
  uint8_t dhtFails_ = 0;
  float dhtTemp_ = NAN;
  float dhtHum_ = NAN;
  bool lightSeen_ = false;
  uint16_t lightRaw_ = 0;
  bool reedTracking_ = false;  // 리드 상태를 따라가는 중인가(켜거나 출처가 바뀌면 지금 상태에서 시작)
  bool reedClosed_ = true;
  bool reedRaw_ = true;
  uint32_t reedRawSince_ = 0;
};

// ----- 보고 정책 (기획서 8장: 기준 고정 5초 vs 적응 정상 10~30초·이상 시 단축) -----
enum SendKind : uint8_t { SEND_NONE = 0, SEND_NORMAL = 1, SEND_URGENT = 2 };

class ReportPolicy {
 public:
  void setAdaptive(bool on) { adaptive_ = on; }
  bool adaptive() const { return adaptive_; }
  // 이 노드가 선언하는 정상 보고 주기(서버 두절 기준 = max(15000, 3×주기+2000), 규격 10장)
  uint32_t declaredIntervalMs(const EnvReading& r) const;
  // 고정: 주기만(감지는 다음 패킷에 래치). 적응: 감지 즉시(반복 광고)·값 변화·선언 주기. 사건은 별도(두 모드 즉시).
  SendKind decide(uint32_t now, const EnvReading& r, uint8_t pendingDet) const;
  void markSent(uint32_t now, SendKind kind, const PktEnvironment& p);

 private:
  bool adaptive_ = true;
  bool sentOnce_ = false;
  uint32_t lastEnvTx_ = 0;
  uint32_t lastDetectTx_ = 0;
  PktEnvironment last_ = {};
};

// environment 본문(머리 제외)을 채운다. det: 이번 패킷에 실을 감지 래치(DET_*)
PktEnvironment buildEnvironment(const EnvReading& r, uint8_t det, uint32_t intervalMs);
bool envChangedEnough(const PktEnvironment& now, const PktEnvironment& last);

// ----- 내보내기 전 검사 (규격 v1 값 규칙) -----
// 보드에서 만든 값(가상·실제)을 USB·BLE로 내보내기 전에 다시 확인한다. 하나라도 어기면 그 패킷은 내보내지 않는다.
// 통과하면 nullptr, 아니면 어긴 규칙 이름(영문 짧은 문구).
const char* checkHeader(const PktHeader& h, uint8_t expectType, uint8_t selfNodeId);
const char* checkEnvironment(const PktEnvironment& p, uint8_t selfNodeId);
const char* checkEvent(const PktEvent& p, uint8_t selfNodeId);
const char* checkAnchorObs(const PktAnchorObs& p, uint8_t selfNodeId);

// ----- 배선 점검("check") 판정 -----
// 기획서 5장: 센서 입력 전압과 출력 신호 전압은 별도로 확인하고, 5V 신호를 GPIO·ADC에 직접 넣지 않는다.
// ESP32는 3.3V를 넘는 전압을 안전하게 잴 수 없으므로 5V 여부는 멀티미터로 먼저 잰다. 이 점검은 GPIO에 꽂은 뒤
// 신호가 3.3V 범위에서 정상으로 보이는지(포화·단선·계속 반응·잡음)만 본다.
struct CheckInput {
  bool     virtual_mode;
  uint8_t  real_use;         // 실제 센서 모드에서 켠 추가 센서
  bool     light_mv_valid;
  uint16_t light_mv;         // 조도 핀 평균 전압
  uint8_t  dht_fail_run;     // 지금 연속 실패 수
  uint32_t dht_reads;        // 점검 시간 동안 읽기
  uint32_t dht_fails;        //   그중 실패
  bool     sound_active, flame_active, shock_active;  // 지금 반응 레벨인가
  uint32_t sound_edges, flame_edges, shock_edges;     // 점검 시간 동안 펄스 수
};
// 경고 코드(영문 짧은 문구)를 out에 담고 개수를 돌려준다.
uint8_t checkEvaluate(const CheckInput& in, const char** out, uint8_t max);
