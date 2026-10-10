// 환경 모듈 펌웨어의 가상 데이터 흐름 시험: 가상 센서 보드(10분 시나리오) → 공통 판단 → 보고 정책 → 검사 →
// seq 부여 → USB JSON 한 줄. 펌웨어 소스(env_logic·anchor_logic·out·ident·settings·json_out·ble_tx)를 그대로 쓰고
// env_module.ino의 송신 정책(envTxPolicy·sendEnv·sendEvent)과 같은 순서로 부른다. 출력은 NDJSON(USB와 같음).
// pc/tests/test_env_module_contract.py가 이 줄을 규격 v1 검사기, C 시험 서버, 팀장 서버 입력 처리에 넣는다.
#include <cstdio>
#include "config.h"
#include "env_logic.h"
#include "anchor_logic.h"
#include "settings.h"
#include "ident.h"
#include "out.h"
#include "ble_tx.h"
#include "BLEDevice.h"
#include "Preferences.h"

HostSerial Serial;
BLEAdvertising g_adv;
uint32_t g_millis = 0;
std::map<std::string, uint32_t> g_nvs_kv;

static EnvJudge s_judge;
static VirtualBoard s_vboard;
static ReportPolicy s_policy;
static bool s_heatPending = false, s_heatPendingSim = false;
static uint16_t s_eventNo[5] = {};

static void sendEnv(uint32_t now, SendKind kind) {
  if (bleTxFree() == 0) return;
  const EnvReading r = s_judge.reading();
  const uint8_t det = s_judge.takeDetections();
  PktEnvironment p = buildEnvironment(r, det, s_policy.declaredIntervalMs(r));
  const bool urgent = kind == SEND_URGENT;
  uint8_t flags = urgent ? PKT_FLAG_EVENT : 0;
  if (r.simulated) flags |= PKT_FLAG_SIMULATION;
  outEnvironment(p, flags, urgent ? EVENT_REPEATS : 1, urgent);
  s_policy.markSent(now, kind, p);
}

static bool sendEvent(uint8_t type, bool simulation) {
  PktEvent p = {};
  p.event_type = type;
  p.mode = MODE_NORMAL;
  p.event_no = s_eventNo[type] + 1;
  if (!outEvent(p, PKT_FLAG_EVENT | (simulation ? PKT_FLAG_SIMULATION : 0))) return false;
  s_eventNo[type]++;
  return true;
}

static void envTxPolicy(uint32_t now) {
  bool sim = false;
  if (s_judge.takeHeatOnset(&sim)) { s_heatPending = true; s_heatPendingSim = sim; }
  if (s_heatPending && sendEvent(EV_HEAT_EXPOSURE, s_heatPendingSim)) s_heatPending = false;
  const SendKind k = s_policy.decide(now, s_judge.reading(), s_judge.pending());
  if (k != SEND_NONE) sendEnv(now, k);
}

int main(int argc, char** argv) {
  const bool fixed = argc > 1 && argv[1][0] == 'f';  // "fixed": 고정 5초 기준 설정
  settingsBegin();  // 기본: env_01, 가상 센서
  identBegin();
  bleTxBegin();
  s_vboard.begin(0);
  s_judge.begin(DET_ALL, settings().virtual_sensors, 0);  // 가상 모드에서는 6개 센서 모두 보고
  s_policy.setAdaptive(!fixed);

  // 앵커 시험 모드: A의 가상 병사 방송 두 개를 관측한 것처럼 표에 넣는다(실제 스캔은 보드 입출력 코드 몫)
  AnchorTable anchors;
  uint32_t lastDht = 0, lastLight = 0, lastAnchorReport = 0;
  const uint32_t END = 660000;  // 시나리오 한 주기(10분) + 1분
  for (uint32_t t = 0; t <= END; t += 20) {
    g_millis = t;
    const bool dhtDue = t == 0 || t - lastDht >= DHT_READ_MS;
    const bool lightDue = t == 0 || t - lastLight >= LIGHT_READ_MS;
    if (dhtDue) lastDht = t;
    if (lightDue) lastLight = t;
    s_judge.update(s_vboard.sample(t, dhtDue, lightDue));
    if (t == 620000) s_judge.setVirtualTemp(38.0f);  // 손으로 넣는 시험: vtemp 38 → 열 노출(가상)
    if (t == 640000) s_judge.setVirtualTemp(NAN);
    if (t == 645000) s_vboard.inject(DET_SOUND);     // vdetect sound
    envTxPolicy(t);

    if (t % 1000 == 0 && t >= 5000) {  // 병사 방송 수신(1초마다, 가상 원본)
      anchors.record(0x01, true, 0x00b7, (uint16_t)(t / 1000), -60 - (int)((t / 1000) % 3), t);
      anchors.record(0x02, true, 0x00c8, (uint16_t)(t / 1000), -72 - (int)((t / 7000) % 4) * 3, t);
    }
    if (t - lastAnchorReport >= ANCHOR_MIN_REPORT_MS) {
      AnchorDue due[ANCHOR_MAX_SOLDIERS];
      const uint8_t n = anchors.due(t, due, ANCHOR_MAX_SOLDIERS);
      const uint8_t free = bleTxFree();
      const uint8_t room = free > ANCHOR_TX_RESERVE ? free - ANCHOR_TX_RESERVE : 0;
      const uint8_t sent = n < room ? n : room;
      for (uint8_t i = 0; i < sent; i++) {
        PktAnchorObs p = {};
        fillAnchorObs(p, due[i].obs, elapsedMs(t, due[i].obs.last_ms));
        outAnchorObs(p, due[i].obs.sim ? PKT_FLAG_SIMULATION : 0);
      }
      if (sent) {
        anchors.markReported(due, sent, t);
        lastAnchorReport = t;
      }
    }
    bleTxLoop(t);
  }
  const TxStats& tx = bleTxStats();
  fprintf(stderr, "packets=%lu windows=%lu dropped=%lu blocked=%lu environment=%lu event=%lu anchor=%lu\n",
          (unsigned long)tx.packets, (unsigned long)tx.windows, (unsigned long)tx.dropped,
          (unsigned long)outStats().blocked, (unsigned long)tx.by_type[PKT_ENVIRONMENT],
          (unsigned long)tx.by_type[PKT_EVENT], (unsigned long)tx.by_type[PKT_ANCHOR_OBS]);
  return 0;
}
