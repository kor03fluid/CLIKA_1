// 팀장 전달용 예시: 펌웨어 json_out.cpp로 환경·열 노출 사건·앵커 관측을 한 줄씩(실측 3줄, 가상 3줄) 출력.
// docs/lead_handoff/samples_*.ndjson이 이 출력과 같은지, 팀장 서버 입력 처리를 통과하는지 test_lead_server_contract.py가 확인한다.
#include "json_out.h"
HostSerial Serial;
static PktHeader hdr(uint8_t type, uint16_t seq, uint32_t up, uint8_t flags) {
  PktHeader h = {}; h.ver_type = (PKT_VERSION << 4) | type; h.flags = flags; h.node_id = 0x31;
  h.boot_id = 0x1a2b; h.seq = seq; h.uptime_ms = up; return h;
}
static void run(uint8_t sim, uint16_t base, uint32_t t0, uint16_t evno) {
  PktEnvironment e = {};
  e.h = hdr(PKT_ENVIRONMENT, base, t0, sim);
  e.air_temp_c10 = 362; e.humidity_pct = sim ? 50 : 41; e.light_raw = 2210; e.heartbeat_s = 10;
  e.detected = TB_FALSE << ENV_DT_SOUND | TB_FALSE << ENV_DT_FLAME | TB_FALSE << ENV_DT_SHOCK | TB_TRUE << ENV_DT_REED_CLOSED;
  printEnvironmentJson(e);
  PktEvent ev = {};
  ev.h = hdr(PKT_EVENT, base + 1, t0 + 50, PKT_FLAG_EVENT | sim);
  ev.event_type = EV_HEAT_EXPOSURE; ev.mode = MODE_NORMAL; ev.event_no = evno;
  printEventJson(ev);
  PktAnchorObs a = {};
  a.h = hdr(PKT_ANCHOR_OBS, base + 2, t0 + 700, sim);
  a.observed_node = 0x01; a.observed_boot = sim ? 0x00b7 : 0x3c41; a.observed_seq = sim ? 57 : 208;
  a.rssi_dbm = -61; a.age_ms = 420;
  printAnchorObsJson(a);
}
int main() { run(0, 140, 812400, 1); run(PKT_FLAG_SIMULATION, 213, 1504200, 2); return 0; }
