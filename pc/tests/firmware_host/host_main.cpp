// 환경 노드 JSON 출력 시험: 여러 경우의 패킷을 만들어 json_out.cpp로 출력한다.
// pc/tests/test_firmware_contract.py가 빌드·실행하고 출력 줄을 규격 v1 검사기로 확인한다.
#include "json_out.h"

HostSerial Serial;

static PktHeader header(uint8_t type, uint8_t node, uint16_t boot, uint16_t seq, uint32_t uptime,
                        uint8_t flags) {
  PktHeader h = {};
  h.ver_type = (PKT_VERSION << 4) | type;
  h.flags = flags;
  h.node_id = node;
  h.boot_id = boot;
  h.seq = seq;
  h.uptime_ms = uptime;
  return h;
}

static uint8_t dt(uint8_t sound, uint8_t flame, uint8_t shock, uint8_t reed) {
  return sound << ENV_DT_SOUND | flame << ENV_DT_FLAME | shock << ENV_DT_SHOCK | reed << ENV_DT_REED_CLOSED;
}

int main() {
  // 1) 모든 센서 정상, 추가 센서 사용
  PktEnvironment e = {};
  e.h = header(PKT_ENVIRONMENT, 0x31, 0x1a2b, 1, 10000, 0);
  e.air_temp_c10 = 245;
  e.humidity_pct = 52;
  e.light_raw = 1730;
  e.heartbeat_s = 30;
  e.detected = dt(TB_FALSE, TB_TRUE, TB_FALSE, TB_TRUE);
  printEnvironmentJson(e);

  // 2) DHT11 읽기 실패(null), 추가 센서 모두 끔, 가상(vtemp) 표시
  PktEnvironment e2 = {};
  e2.h = header(PKT_ENVIRONMENT, 0x31, 0x1a2b, 2, 40000, PKT_FLAG_SIMULATION);
  e2.air_temp_c10 = ENV_TEMP_NULL;
  e2.humidity_pct = ENV_HUM_NULL;
  e2.light_raw = ENV_LIGHT_NULL;
  e2.heartbeat_s = 10;
  e2.sensor_status = SS_UNAVAILABLE << ENV_SS_DHT11 | SS_UNAVAILABLE << ENV_SS_LIGHT;
  e2.detected = dt(TB_OMIT, TB_OMIT, TB_OMIT, TB_OMIT);
  printEnvironmentJson(e2);

  // 3) 영하 온도, 측정 불가(null) 추가 센서
  PktEnvironment e3 = e;
  e3.h = header(PKT_ENVIRONMENT, 0x32, 0xffff, 65535, 4294967295u, 0);
  e3.air_temp_c10 = -55;
  e3.detected = dt(TB_NULL, TB_FALSE, TB_TRUE, TB_FALSE);
  printEnvironmentJson(e3);

  // 4) 환경 열 노출 주의 사건
  PktEvent ev = {};
  ev.h = header(PKT_EVENT, 0x31, 0x1a2b, 3, 50000, PKT_FLAG_EVENT);
  ev.event_type = EV_HEAT_EXPOSURE;
  ev.mode = MODE_NORMAL;
  ev.event_no = 1;
  printEventJson(ev);

  // 5) 앵커 관측
  PktAnchorObs a = {};
  a.h = header(PKT_ANCHOR_OBS, 0x31, 0x1a2b, 4, 50300, 0);
  a.observed_node = 0x01;
  a.observed_boot = 0x00a1;
  a.observed_seq = 1;
  a.rssi_dbm = -58;
  a.age_ms = 300;
  printAnchorObsJson(a);
  return 0;
}
