#include "anchor_logic.h"
#include "config.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static_assert(ANCHOR_STALE_MS <= 0xFFFF, "age_ms(16bit)가 ANCHOR_STALE_MS를 담지 못함");

AdvVerdict anchorClassify(const uint8_t* md, size_t len, bool testMode, PktHeader* hdr) {
  if (len < 2 + sizeof(PktHeader)) return ADV_NOT_OURS;
  if ((uint16_t)(md[0] | (md[1] << 8)) != PKT_COMPANY_ID) return ADV_NOT_OURS;
  PktHeader h;
  memcpy(&h, md + 2, sizeof(h));
  if (pktVersion(h) != PKT_VERSION) return ADV_NOT_OURS;
  const uint8_t type = pktType(h);
  if (type != PKT_SOLDIER_STATUS && type != PKT_GPS && type != PKT_EVENT) return ADV_NOT_SOLDIER;
  if (h.node_id < 0x01 || h.node_id > 0x1F) return ADV_NOT_SOLDIER;  // 병사 노드(halo_*)만
  if (h.flags & PKT_FLAG_RELAYED) return ADV_RELAYED;                 // 중계 패킷으로 관측을 만들지 않는다
  const bool sim = h.flags & PKT_FLAG_SIMULATION;
  if (sim && !testMode) return ADV_SIM_SKIPPED;                       // 평상시 실제 앵커는 실제 병사 패킷만
  if (hdr) *hdr = h;
  return sim ? ADV_ACCEPT_SIM : ADV_ACCEPT;
}

void AnchorTable::clear() {
  for (auto& o : tab_) o.used = false;
}

void AnchorTable::clearSim() {
  for (auto& o : tab_) {
    if (o.sim) o.used = false;
  }
}

uint8_t AnchorTable::size() const {
  uint8_t n = 0;
  for (const auto& o : tab_) n += o.used;
  return n;
}

bool AnchorTable::record(uint8_t id, bool sim, uint16_t boot, uint16_t seq, int rssi, uint32_t now) {
  SoldierObs* o = nullptr;
  SoldierObs* freeSlot = nullptr;
  for (auto& s : tab_) {
    if (s.used && s.id == id && s.sim == sim) {
      o = &s;
      break;
    }
    // 빈 칸이 없으면 오래 안 보인 병사 칸을 다시 쓴다
    const bool reusable = !s.used || elapsedMs(now, s.last_ms) > 2 * ANCHOR_STALE_MS;
    if (reusable && !freeSlot) freeSlot = &s;
  }
  if (!o && freeSlot) {
    o = freeSlot;
    *o = {};
    o->used = true;
    o->id = id;
    o->sim = sim;
    o->rssi_avg = rssi;
  }
  if (!o) return false;
  o->boot_id = boot;  // 재부팅이면 seq가 다시 시작한다(평활값만 이어 감)
  o->last_seq = seq;
  o->rssi_last = (int8_t)(rssi < -128 ? -128 : rssi > 127 ? 127 : rssi);
  o->rssi_avg += ANCHOR_RSSI_ALPHA * (rssi - o->rssi_avg);
  if (o->samples < 255) o->samples++;
  o->last_ms = now;
  return true;
}

uint8_t AnchorTable::due(uint32_t now, AnchorDue* out, uint8_t max) {
  uint8_t n = 0;
  for (auto& o : tab_) {
    if (!o.used) continue;
    const uint32_t age = elapsedMs(now, o.last_ms);
    if (age > ANCHOR_STALE_MS) {
      o.reported = false;                             // 돌아오면 새로 보인 것으로 바로 보고
      if (age > 2 * ANCHOR_STALE_MS) o.used = false;  // 오래된 칸은 비워 둔다
      continue;
    }
    const int8_t avg = (int8_t)lroundf(o.rssi_avg);
    const uint32_t waited = elapsedMs(now, o.last_report_ms);
    uint8_t rank;
    if (!o.reported) rank = 0;
    else if (abs(avg - o.reported_avg) >= ANCHOR_RSSI_DELTA_DB) rank = 1;
    else if (waited >= ANCHOR_MAX_REPORT_MS) rank = 2;
    else continue;
    if (n < max) out[n++] = {o, rank, waited};
  }
  for (uint8_t i = 1; i < n; i++) {  // 우선순위 정렬(작은 배열이라 삽입 정렬)
    AnchorDue d = out[i];
    int j = i - 1;
    while (j >= 0 && (out[j].rank > d.rank || (out[j].rank == d.rank && out[j].waited < d.waited))) {
      out[j + 1] = out[j];
      j--;
    }
    out[j + 1] = d;
  }
  return n;
}

void AnchorTable::markReported(const AnchorDue* d, uint8_t n, uint32_t now) {
  for (uint8_t i = 0; i < n; i++) {
    for (auto& o : tab_) {
      if (!o.used || o.id != d[i].obs.id || o.sim != d[i].obs.sim) continue;
      o.reported = true;
      o.reported_avg = (int8_t)lroundf(d[i].obs.rssi_avg);
      o.samples = o.samples > d[i].obs.samples ? o.samples - d[i].obs.samples : 0;  // 보고 뒤 받은 표본은 남긴다
      o.last_report_ms = now;
    }
  }
}

void fillAnchorObs(PktAnchorObs& p, const SoldierObs& o, uint32_t ageMs) {
  p.observed_node = o.id;
  p.observed_boot = o.boot_id;
  p.observed_seq = o.last_seq;
  p.rssi_dbm = o.rssi_last;  // 그 패킷(observed_seq)의 직접 수신 RSSI. 평활은 서버가 한다
  p.age_ms = ageMs > 0xFFFF ? 0xFFFF : ageMs;
}
