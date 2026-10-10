// 환경 모듈 펌웨어의 공통 판단 코드(env_logic·anchor_logic) 시험. "이름 값"을 한 줄씩 출력한다.
// pc/tests/test_env_module_contract.py가 빌드·실행해 확인한다(Arduino·BLE 없이 그대로 빌드되는지도 함께 본다).
#include <cstdio>
#include <cstring>
#include "config.h"
#include "env_logic.h"
#include "anchor_logic.h"

static void out(const char* name, double v) { printf("%s %g\n", name, v); }
static void outs(const char* name, const char* v) { printf("%s %s\n", name, v ? v : "OK"); }

// ----- 가상 센서 보드 시나리오 -----
static void virtualBoard() {
  VirtualBoard vb;
  vb.begin(0);
  long soundAt = -1, shockAt = -1, flamePulseAt = -1, reedFrom = -1, reedTo = -1, flameFrom = -1, flameTo = -1;
  long dhtFrom = -1, dhtTo = -1;
  float tMax = -100, lightMin = 5000;
  int sounds = 0;
  bool prevReed = true, prevFlame = false, prevDht = true;
  for (uint32_t t = 0; t < 600000; t += 20) {
    RawSample s = vb.sample(t, true, true);
    if (s.isr_det & DET_SOUND) { if (soundAt < 0) soundAt = t; sounds++; }
    if ((s.isr_det & DET_SHOCK) && shockAt < 0) shockAt = t;
    if ((s.isr_det & DET_FLAME) && flamePulseAt < 0) flamePulseAt = t;
    if (!s.reed_closed && prevReed) reedFrom = t;
    if (s.reed_closed && !prevReed) reedTo = t;
    if (s.flame_active && !prevFlame) flameFrom = t;
    if (!s.flame_active && prevFlame) flameTo = t;
    const bool dhtOk = !isnan(s.dht_temp);
    if (!dhtOk && prevDht) dhtFrom = t;
    if (dhtOk && !prevDht) dhtTo = t;
    prevReed = s.reed_closed; prevFlame = s.flame_active; prevDht = dhtOk;
    if (dhtOk && s.dht_temp > tMax) tMax = s.dht_temp;
    if (s.light_raw < lightMin) lightMin = s.light_raw;
  }
  out("vb_sound_at", soundAt); out("vb_sounds", sounds); out("vb_shock_at", shockAt); out("vb_flame_pulse_at", flamePulseAt);
  out("vb_reed_open_from", reedFrom); out("vb_reed_open_to", reedTo);
  out("vb_flame_from", flameFrom); out("vb_flame_to", flameTo);
  out("vb_dht_fail_from", dhtFrom); out("vb_dht_fail_to", dhtTo);
  out("vb_temp_max", tMax); out("vb_light_min", lightMin);
  // 두 번째 주기에도 같은 펄스(10분 반복)
  int again = 0;
  for (uint32_t t = 600000; t < 640000; t += 20) again += (vb.sample(t, false, false).isr_det & DET_SOUND) ? 1 : 0;
  out("vb_sound_second_cycle", again);
  // 손으로 넣은 감지
  vb.inject(DET_SHOCK | DET_REED);
  RawSample s = vb.sample(640020, false, false);
  out("vb_inject_shock", (s.isr_det & DET_SHOCK) ? 1 : 0);
  out("vb_inject_reed_closed", s.reed_closed ? 1 : 0);
  outs("vb_phase_285s", VirtualBoard::phaseName(285000));
}

// 실제 센서 원시값 하나
static RawSample real(uint32_t t, float temp, float hum, bool dht = true) {
  RawSample s = {};
  s.now_ms = t; s.has_dht = dht; s.dht_temp = temp; s.dht_hum = hum;
  s.has_light = true; s.light_raw = 1500; s.reed_closed = true;
  return s;
}

static void judge() {
  EnvJudge j;
  j.begin(0, false, 0);
  out("j_start_dht_ok", j.reading().dht_ok);  // 아직 읽지 않음
  j.update(real(2000, 25.0f, 40.0f));
  out("j_real_dht_ok", j.reading().dht_ok); out("j_real_sim", j.reading().simulated);
  j.update(real(4000, NAN, NAN));
  j.update(real(6000, NAN, NAN));
  out("j_fail2_dht_ok", j.reading().dht_ok); out("j_fail2_temp", j.reading().temp_c);
  j.update(real(8000, NAN, NAN));
  out("j_fail3_dht_ok", j.reading().dht_ok); out("j_fail3_temp_nan", isnan(j.reading().temp_c));
  // vtemp: DHT 없이도 온습도 모두 숫자, 가상, 열 노출 사건(가상)
  j.setVirtualTemp(38.0f);
  bool sim = false;
  out("j_vtemp_dht_ok", j.reading().dht_ok); out("j_vtemp_hum", j.reading().humidity);
  out("j_vtemp_sim", j.reading().simulated);
  out("j_vtemp_onset", j.takeHeatOnset(&sim)); out("j_vtemp_onset_sim", sim);
  j.setVirtualTemp(NAN);
  out("j_vtemp_off_heat", j.reading().heat);  // 가상 열 노출은 버림
  // 실측이 이미 더울 때 vtemp: 가상 사건이 따로 생기고, 끝나면 실측 상태로 돌아가 사건이 또 생기지 않음
  j.update(real(10000, 36.0f, 40.0f));
  out("j_real36_onset", j.takeHeatOnset(&sim)); out("j_real36_onset_sim", sim);
  j.setVirtualTemp(38.0f);
  out("j_real36_vtemp_onset", j.takeHeatOnset(&sim)); out("j_real36_vtemp_onset_sim", sim);
  j.setVirtualTemp(NAN);
  j.update(real(12000, 36.0f, 40.0f));
  out("j_real36_back_heat", j.reading().heat); out("j_real36_back_onset", j.takeHeatOnset(&sim));
  j.update(real(14000, 34.0f, 40.0f));
  out("j_real34_heat", j.reading().heat);  // 34°C 이하 해제
  // 꺼진 센서의 감지는 버리고, 켠 센서만 래치
  RawSample p = real(16000, 25.0f, 40.0f, false);
  p.isr_det = DET_SOUND | DET_SHOCK;
  j.update(p);
  out("j_unused_det", j.pending());
  j.setUse(DET_SOUND);
  j.update(p);
  out("j_used_det", j.pending());
  // 리드를 새로 켜면 지금 상태에서 시작(변화로 세지 않음), 그 뒤 50ms 넘게 바뀌면 감지
  j.takeDetections();
  j.setUse(DET_SOUND | DET_REED);
  RawSample r = real(17000, 25.0f, 40.0f, false);
  r.reed_closed = false;
  j.update(r);
  out("j_reed_new_det", j.pending());
  r.reed_closed = true; r.now_ms = 17010; j.update(r);
  r.now_ms = 17030; j.update(r);
  out("j_reed_bounce_det", j.pending());  // 20ms만 바뀜 → 아직
  r.now_ms = 17070; j.update(r);
  out("j_reed_change_det", j.pending()); out("j_reed_closed", j.reading().reed_closed);
  // 실제 → 가상 전환: 측정값을 비우고 가상 원시값부터 새로 판단
  j.setVirtualSensors(true);
  out("j_switch_dht_ok", j.reading().dht_ok); out("j_switch_sim", j.reading().simulated);
  out("j_switch_det", j.pending());
}

static void policy() {
  EnvReading r = {};
  r.dht_ok = true; r.temp_c = 24.0f; r.humidity = 50.0f; r.light_ok = true; r.light_raw = 1800;
  ReportPolicy fx;
  fx.setAdaptive(false);
  out("p_first_before_3s", fx.decide(2000, r, 0));
  out("p_first_after_3s", fx.decide(3100, r, 0));
  fx.markSent(3100, SEND_NORMAL, buildEnvironment(r, 0, fx.declaredIntervalMs(r)));
  out("p_fixed_interval", fx.declaredIntervalMs(r));
  out("p_fixed_4s", fx.decide(7000, r, DET_SOUND));   // 고정: 감지도 주기까지 기다림
  out("p_fixed_5s", fx.decide(8100, r, DET_SOUND));
  ReportPolicy ad;
  ad.markSent(3100, SEND_NORMAL, buildEnvironment(r, 0, ad.declaredIntervalMs(r)));
  out("p_adaptive_interval", ad.declaredIntervalMs(r));
  out("p_adaptive_idle_10s", ad.decide(13100, r, 0));
  out("p_adaptive_urgent", ad.decide(3500, r, DET_SHOCK));
  ad.markSent(3500, SEND_URGENT, buildEnvironment(r, DET_SHOCK, 30000));
  out("p_adaptive_urgent_gap", ad.decide(4500, r, DET_SHOCK));  // 2초 안: 미룸
  EnvReading warm = r;
  warm.temp_c = 25.2f;
  out("p_adaptive_change_2s", ad.decide(5000, warm, 0));  // 3초 최소 간격 전
  out("p_adaptive_change_4s", ad.decide(7600, warm, 0));
  out("p_adaptive_heartbeat", ad.decide(33600, r, 0));
  EnvReading hot = r;
  hot.heat = true;
  out("p_heat_interval", ad.declaredIntervalMs(hot));
}

static PktHeader hdr(uint8_t type, uint8_t flags = 0) {
  PktHeader h = {};
  h.ver_type = (PKT_VERSION << 4) | type; h.flags = flags; h.node_id = 0x31; h.boot_id = 0x1a2b; h.seq = 7;
  return h;
}

static void packets() {
  EnvReading r = {};
  r.dht_ok = true; r.temp_c = 24.46f; r.humidity = 104.0f; r.light_ok = true; r.light_raw = 1800;
  r.use_mask = 0;
  PktEnvironment e = buildEnvironment(r, 0, 30000);
  e.h = hdr(PKT_ENVIRONMENT);
  out("b_temp_c10", e.air_temp_c10); out("b_hum_clamped", e.humidity_pct); out("b_heartbeat_s", e.heartbeat_s);
  out("b_omit_all", e.detected == (TB_OMIT << ENV_DT_SOUND | TB_OMIT << ENV_DT_FLAME | TB_OMIT << ENV_DT_SHOCK |
                                   TB_OMIT << ENV_DT_REED_CLOSED));
  outs("c_env_ok", checkEnvironment(e, 0x31));
  r.use_mask = DET_ALL; r.reed_closed = true;
  PktEnvironment all = buildEnvironment(r, DET_SOUND, 30000);
  all.h = hdr(PKT_ENVIRONMENT);
  outs("c_env_all_ok", checkEnvironment(all, 0x31));
  out("b_sound_true", ((all.detected >> ENV_DT_SOUND) & 3) == TB_TRUE);
  EnvReading bad = r;
  bad.dht_ok = true; bad.humidity = NAN;  // 하나만 있으면 둘 다 null
  PktEnvironment half = buildEnvironment(bad, 0, 30000);
  out("b_half_both_null", half.air_temp_c10 == ENV_TEMP_NULL && half.humidity_pct == ENV_HUM_NULL);
  half.h = hdr(PKT_ENVIRONMENT);
  outs("c_env_half_ok", checkEnvironment(half, 0x31));
  // 검사가 막아야 하는 것
  PktEnvironment x = all; x.humidity_pct = 101; outs("c_env_hum101", checkEnvironment(x, 0x31));
  x = all; x.humidity_pct = ENV_HUM_NULL; outs("c_env_hum_only_null", checkEnvironment(x, 0x31));
  x = all; x.light_raw = 5000; outs("c_env_light5000", checkEnvironment(x, 0x31));
  x = all; x.heartbeat_s = 0; outs("c_env_hb0", checkEnvironment(x, 0x31));
  x = all; x.h.flags = PKT_FLAG_RELAYED; outs("c_env_relayed_flag", checkEnvironment(x, 0x31));
  x = all; x.h.node_id = 0x01; outs("c_env_soldier_id", checkEnvironment(x, 0x01));
  x = all; outs("c_env_other_env", checkEnvironment(x, 0x32));
  x = all; x.sensor_status &= ~(3 << ENV_SS_SOUND); x.sensor_status |= SS_DISABLED << ENV_SS_SOUND;
  outs("c_env_omit_mismatch", checkEnvironment(x, 0x31));
  x = all; x.h.seq = 0; outs("c_env_seq0", checkEnvironment(x, 0x31));
  PktEvent ev = {};
  ev.h = hdr(PKT_EVENT, PKT_FLAG_EVENT); ev.event_type = EV_HEAT_EXPOSURE; ev.mode = MODE_NORMAL; ev.event_no = 1;
  outs("c_event_ok", checkEvent(ev, 0x31));
  PktEvent ev2 = ev; ev2.event_type = EV_SOS; outs("c_event_sos", checkEvent(ev2, 0x31));
  ev2 = ev; ev2.mode = MODE_COVERT; outs("c_event_covert", checkEvent(ev2, 0x31));
  ev2 = ev; ev2.event_no = 0; outs("c_event_no0", checkEvent(ev2, 0x31));
  PktAnchorObs a = {};
  a.h = hdr(PKT_ANCHOR_OBS); a.observed_node = 0x01; a.rssi_dbm = -60; a.age_ms = 300;
  outs("c_anchor_ok", checkAnchorObs(a, 0x31));
  PktAnchorObs a2 = a; a2.rssi_dbm = 5; outs("c_anchor_rssi_pos", checkAnchorObs(a2, 0x31));
  a2 = a; a2.observed_node = 0x31; outs("c_anchor_obs_env", checkAnchorObs(a2, 0x31));
}

static void check() {
  CheckInput in = {};
  in.virtual_mode = true; in.light_mv_valid = true; in.light_mv = 1500;
  const char* w[12];
  out("k_virtual_ok", checkEvaluate(in, w, 12));
  in.light_mv = 3200; out("k_high", checkEvaluate(in, w, 12));
  in.light_mv = 10; out("k_low", checkEvaluate(in, w, 12));
  in.light_mv = 1500; in.dht_fail_run = 5;
  out("k_virtual_ignores_dht", checkEvaluate(in, w, 12));
  in.virtual_mode = false;
  out("k_real_dht", checkEvaluate(in, w, 12));
  in.dht_fail_run = 0; in.real_use = DET_SOUND | DET_SHOCK; in.sound_edges = 50; in.shock_active = true;
  out("k_real_noisy_held", checkEvaluate(in, w, 12));
  in.real_use = 0;
  out("k_real_unused_ignored", checkEvaluate(in, w, 12));
}

static void md(uint8_t* b, uint8_t type, uint8_t node, uint8_t flags, uint8_t ver = PKT_VERSION) {
  b[0] = PKT_COMPANY_ID & 0xFF; b[1] = PKT_COMPANY_ID >> 8;
  PktHeader h = {};
  h.ver_type = (ver << 4) | type; h.flags = flags; h.node_id = node; h.boot_id = 0x00a1; h.seq = 9;
  memcpy(b + 2, &h, sizeof(h));
}

static void anchor() {
  uint8_t b[2 + sizeof(PktHeader)];
  PktHeader h;
  md(b, PKT_SOLDIER_STATUS, 0x01, 0); out("a_real", anchorClassify(b, sizeof(b), false, &h));
  out("a_real_seq", h.seq);
  md(b, PKT_SOLDIER_STATUS, 0x01, PKT_FLAG_RELAYED); out("a_relayed", anchorClassify(b, sizeof(b), false, &h));
  out("a_relayed_test", anchorClassify(b, sizeof(b), true, &h));
  md(b, PKT_SOLDIER_STATUS, 0x01, PKT_FLAG_RELAYED | PKT_FLAG_SIMULATION);
  out("a_relayed_sim_test", anchorClassify(b, sizeof(b), true, &h));
  md(b, PKT_GPS, 0x02, PKT_FLAG_SIMULATION); out("a_sim_off", anchorClassify(b, sizeof(b), false, &h));
  out("a_sim_test", anchorClassify(b, sizeof(b), true, &h));
  md(b, PKT_ENVIRONMENT, 0x31, 0); out("a_env_node", anchorClassify(b, sizeof(b), true, &h));
  md(b, PKT_ANCHOR_OBS, 0x01, 0); out("a_soldier_anchor_type", anchorClassify(b, sizeof(b), true, &h));
  md(b, PKT_EVENT, 0x01, PKT_FLAG_EVENT); out("a_soldier_event", anchorClassify(b, sizeof(b), false, &h));
  md(b, PKT_SOLDIER_STATUS, 0x01, 0, 1); out("a_old_version", anchorClassify(b, sizeof(b), false, &h));
  md(b, PKT_SOLDIER_STATUS, 0x01, 0); b[0] = 0x59; out("a_other_company", anchorClassify(b, sizeof(b), false, &h));
  out("a_short", anchorClassify(b, 5, false, &h));

  AnchorTable t;
  AnchorDue d[ANCHOR_MAX_SOLDIERS];
  t.record(0x01, false, 0xa1, 1, -60, 1000);
  t.record(0x02, false, 0xb2, 1, -70, 1100);
  t.record(0x01, true, 0xc3, 1, -50, 1200);  // 같은 ID의 가상 관측은 따로
  out("t_size", t.size());
  uint8_t n = t.due(2000, d, ANCHOR_MAX_SOLDIERS);
  out("t_due_new", n); out("t_due_rank0", d[0].rank);
  t.markReported(d, n, 2000);
  out("t_due_after_report", t.due(3000, d, ANCHOR_MAX_SOLDIERS));
  for (int i = 0; i < 8; i++) t.record(0x01, false, 0xa1, 2 + i, -40, 3000 + i * 100);  // 평활값이 6dB 넘게 바뀜
  n = t.due(4000, d, ANCHOR_MAX_SOLDIERS);
  out("t_change_n", n); out("t_change_rank", n ? d[0].rank : -1); out("t_change_id", n ? d[0].obs.id : -1);
  out("t_change_rssi_last", n ? d[0].obs.rssi_last : 0);
  t.markReported(d, n, 4000);
  t.record(0x01, false, 0xa1, 20, -40, 16000);
  t.record(0x02, false, 0xb2, 2, -70, 16000);
  t.record(0x01, true, 0xc3, 2, -50, 16000);
  n = t.due(17100, d, ANCHOR_MAX_SOLDIERS);  // 마지막 보고 후 15초 넘음 → 주기 보고(오래 기다린 것부터)
  out("t_periodic_n", n); out("t_periodic_rank", n ? d[0].rank : -1);
  out("t_stale", t.due(16000 + ANCHOR_STALE_MS + 1, d, ANCHOR_MAX_SOLDIERS));  // 45초 넘게 안 보이면 뺀다
  t.clearSim();
  out("t_after_clear_sim", t.size());
  PktAnchorObs p = {};
  SoldierObs o = {};
  o.id = 0x01; o.boot_id = 0xa1; o.last_seq = 20; o.rssi_last = -41;
  fillAnchorObs(p, o, 70000);
  out("t_fill_age_capped", p.age_ms); out("t_fill_rssi", p.rssi_dbm);
}

int main() {
  virtualBoard();
  judge();
  policy();
  packets();
  check();
  anchor();
  return 0;
}
