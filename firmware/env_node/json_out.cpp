#include "json_out.h"
#include "config.h"

static const char* const SS_NAMES[] = {"ok", "unavailable", "not_implemented", "disabled"};
static const char* const EVENT_NAMES[] = {"unknown", "sos", "impact", "prolonged_still", "heat_exposure"};
static const char* const MODE_NAMES[] = {"normal", "covert"};

void nodeName(uint8_t id, char* out, size_t len) {
  if (id >= 0x01 && id <= 0x1F) snprintf(out, len, "halo_%02u", id);
  else if (id >= 0x20 && id <= 0x27) snprintf(out, len, "gateway_%02u", id - 0x1F);
  else if (id >= 0x28 && id <= 0x2F) snprintf(out, len, "relay_%02u", id - 0x27);
  else if (id >= 0x31 && id <= 0x3F) snprintf(out, len, "env_%02u", id - 0x30);
  else snprintf(out, len, "node_%02x", id);
}

static void jsonBegin(const PktHeader& h, const char* packet_type) {
  char name[16];
  nodeName(h.node_id, name, sizeof(name));
  Serial.printf("{\"schema_version\":\"1.0\",\"packet_type\":\"%s\",\"node_id\":\"%s\","
                "\"boot_id\":\"boot_%04x\",\"seq\":%u,\"source\":\"%s\",\"uptime_ms\":%lu,\"payload\":{",
                packet_type, name, (unsigned)h.boot_id, (unsigned)h.seq,
                (h.flags & PKT_FLAG_SIMULATION) ? "simulation" : "device", (unsigned long)h.uptime_ms);
}

static void jsonEnd(const PktHeader& h) {
  // 환경 노드를 PC에 직접 USB로 연결한 경로: 자기 자신이 USB 출력 노드, 무선 수신 아님.
  // 가상(source simulation) 패킷은 route "simulation"이다(규격 예시, 팀장 서버는 다른 route를 거부).
  char name[16];
  nodeName(NODE_ID, name, sizeof(name));
  Serial.printf("},\"transport\":{\"gateway_id\":\"%s\",\"route\":\"%s\",\"hop_count\":0,"
                "\"relay_id\":null,\"rssi_dbm\":null}}\n",
                name, (h.flags & PKT_FLAG_SIMULATION) ? "simulation" : "direct");
}

static void printTri(const char* key, uint8_t v) {
  if (v == TB_OMIT) return;
  Serial.printf(",\"%s\":%s", key, v == TB_TRUE ? "true" : v == TB_FALSE ? "false" : "null");
}

void printEnvironmentJson(const PktEnvironment& p) {
  jsonBegin(p.h, "environment");
  if (p.air_temp_c10 == ENV_TEMP_NULL) Serial.print("\"air_temperature_c\":null");
  else Serial.printf("\"air_temperature_c\":%.1f", p.air_temp_c10 / 10.0f);
  if (p.humidity_pct == ENV_HUM_NULL) Serial.print(",\"humidity_pct\":null");
  else Serial.printf(",\"humidity_pct\":%u", (unsigned)p.humidity_pct);
  if (p.light_raw == ENV_LIGHT_NULL) Serial.print(",\"light_raw\":null");
  else Serial.printf(",\"light_raw\":%u", (unsigned)p.light_raw);
  Serial.printf(",\"heartbeat_interval_ms\":%lu", (unsigned long)p.heartbeat_s * 1000UL);

  struct Opt { const char* name; int ss; int dt; const char* field; };
  static const Opt opt[] = {
    {"sound", ENV_SS_SOUND, ENV_DT_SOUND, "sound_detected"},
    {"flame", ENV_SS_FLAME, ENV_DT_FLAME, "flame_detected"},
    {"shock", ENV_SS_SHOCK, ENV_DT_SHOCK, "shock_detected"},
    {"reed", ENV_SS_REED, ENV_DT_REED_CLOSED, "reed_closed"},
  };
  Serial.printf(",\"sensor_status\":{\"dht11\":\"%s\",\"light\":\"%s\"",
                SS_NAMES[(p.sensor_status >> ENV_SS_DHT11) & 3], SS_NAMES[(p.sensor_status >> ENV_SS_LIGHT) & 3]);
  for (const Opt& o : opt) {
    if (((p.detected >> o.dt) & 3) == TB_OMIT) continue;  // 쓰지 않는 추가 센서는 키를 뺀다
    Serial.printf(",\"%s\":\"%s\"", o.name, SS_NAMES[(p.sensor_status >> o.ss) & 3]);
  }
  Serial.print("}");
  for (const Opt& o : opt) printTri(o.field, (p.detected >> o.dt) & 3);
  jsonEnd(p.h);
}

void printEventJson(const PktEvent& p) {
  char name[16];
  nodeName(p.h.node_id, name, sizeof(name));
  const char* type = p.event_type <= EV_HEAT_EXPOSURE ? EVENT_NAMES[p.event_type] : EVENT_NAMES[0];
  jsonBegin(p.h, "event");
  // event_id = "<node_id>:<boot_id>:<event_type>:<번호>" (규격 6장 예: halo_01:boot_a1:sos:1)
  Serial.printf("\"event_id\":\"%s:boot_%04x:%s:%u\",\"event_type\":\"%s\",\"mode\":\"%s\"",
                name, (unsigned)p.h.boot_id, type, (unsigned)p.event_no, type,
                MODE_NAMES[p.mode == MODE_COVERT ? 1 : 0]);
  jsonEnd(p.h);
}

void printAnchorObsJson(const PktAnchorObs& p) {
  char anchorName[16], observedName[16];
  nodeName(p.h.node_id, anchorName, sizeof(anchorName));
  nodeName(p.observed_node, observedName, sizeof(observedName));
  jsonBegin(p.h, "anchor_observation");
  Serial.printf("\"anchor_id\":\"%s\",\"observed_node_id\":\"%s\",\"observed_boot_id\":\"boot_%04x\","
                "\"observed_seq\":%u,\"rssi_dbm\":%d,\"observation_age_ms\":%u",
                anchorName, observedName, (unsigned)p.observed_boot, (unsigned)p.observed_seq,
                (int)p.rssi_dbm, (unsigned)p.age_ms);
  jsonEnd(p.h);
}
