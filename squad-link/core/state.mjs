import {randomUUID} from 'node:crypto';
import {validateTelemetry,createTelemetry} from './telemetry.mjs';
import {config as defaults,timeoutMs} from './config.mjs';
const sensorValues = new Set(['ok', 'unavailable', 'not_implemented', 'disabled']);
export function makeState({now = () => performance.now(), wall = () => new Date(), config = defaults} = {}) {
  let soldiers, events, seen, revision, previousBoots, incidentIds, streamHeads;
  const iso = () => wall().toISOString();
  const telemetry=createTelemetry({now,iso,config});
  function reset() {
    telemetry.reset(); streamHeads=new Map();
    soldiers = Array.from({length: config.squad.soldier_count}, (_, i) => ({
      soldier_id: `soldier_${String(i + 1).padStart(2, '0')}`,
      assigned_node_id: config.squad.node_ids[i] ?? null,
      source: null, connection_state: i < config.squad.node_ids.length ? 'waiting' : 'unassigned',
      last_seen_at: null, data_stale: true, payload: null,
      boot_id: null, last_seq: -1, last_seen_mono: null,
      last_status_mono: null, status_received_at: null
    }));
    events = []; incidentIds = new Set(); seen = new Set(); previousBoots = new Map(); revision = 0;
  }
  reset();
  function eventRecord(event_id, node_id, event_type, details = {}) {
    if (events.some(e => e.event_id === event_id)) return;
    events.unshift({event_id, node_id, event_type, source: config.input.mode,
      event_state: 'open', first_received_at: iso(), acknowledged_at: null,
      resolved_at: null, ...details});
  }
  function orderPacket(packet) {
    const key=JSON.stringify([packet.source,packet.node_id,packet.boot_id,packet.seq]);
    if(seen.has(key))return {accepted:false,reason:'duplicate'};
    const head=streamHeads.get(packet.node_id);
    if(head?.old.has(packet.boot_id))return {accepted:false,reason:'previous_boot'};
    const newer=!head||head.boot!==packet.boot_id||packet.seq>head.seq;
    if(!newer&&packet.packet_type!=='event')return {accepted:false,reason:'out_of_order'};
    if(newer){const old=head?.old??new Set();if(head&&head.boot!==packet.boot_id)old.add(head.boot);streamHeads.set(packet.node_id,{boot:packet.boot_id,seq:packet.seq,old});}
    return {accepted:true,newer,key};
  }
  function ingest(packet) {
    if (!packet || packet.schema_version !== config.app.schema_version || packet.source !== config.input.mode)
      throw Error('규격 버전 또는 현재 입력 모드와 source가 일치하지 않습니다.');
    if (!['soldier_status', 'event','environment','gps'].includes(packet.packet_type))
      throw Error('지원하지 않는 패킷 유형입니다.');
    if (typeof packet.boot_id !== 'string' || !packet.boot_id ||
      !Number.isSafeInteger(packet.seq) || packet.seq < 0 ||
      !Number.isSafeInteger(packet.uptime_ms) || packet.uptime_ms < 0)
      throw Error('부팅 ID·순번·uptime이 올바르지 않습니다.');
    const t=packet.transport;
    const validRoute=packet.source==='simulation'?t?.route==='simulation'&&t.hop_count===0&&t.relay_id===null:
      t?.route==='direct'?t.hop_count===0&&t.relay_id===null:
      t?.route==='relay'&&t.hop_count===1&&typeof t.relay_id==='string'&&t.relay_id.length>0;
    if(!validRoute||typeof t.gateway_id!=='string'||!t.gateway_id||(t.rssi_dbm!==null&&!Number.isFinite(t.rssi_dbm)))throw Error('transport 경로·홉·RSSI 오류');
    if(['environment','gps'].includes(packet.packet_type)){
      validateTelemetry(packet,config);
      const ordered=orderPacket(packet);if(!ordered.accepted)return ordered;
      const result=telemetry.ingest(packet);
      if(result.accepted){seen.add(ordered.key);if(seen.size>config.communication.dedup_limit)seen.delete(seen.values().next().value);revision++;}
      return result;
    }
    const s = soldiers.find(s => s.assigned_node_id === packet.node_id);
    if(!s)throw Error('미등록 병사 노드');
    const p=packet.payload;
    if(!p||!['normal','covert'].includes(p.mode))throw Error('운용 모드를 확인하세요.');
    if (packet.packet_type === 'soldier_status') {
      if (!Number.isSafeInteger(p.heartbeat_interval_ms) || p.heartbeat_interval_ms <= 0 ||
        !['good','poor','no_contact','unavailable'].includes(p.heart_rate_quality) ||
        !['moving','still','unknown'].includes(p.motion_state)) throw Error('병사 상태 필드를 확인하세요.');
      if (p.heart_rate_quality === 'good' ? !Number.isFinite(p.heart_rate_bpm) || p.heart_rate_bpm <= 0 : p.heart_rate_bpm !== null)
        throw Error('심박값과 측정 품질이 일치하지 않습니다.');
      if (!p.sensor_status || !['heart_rate','imu','body_temperature','gps'].every(k => sensorValues.has(p.sensor_status[k])))
        throw Error('센서별 상태를 확인하세요.');
      if (p.body_temperature_c !== null && !Number.isFinite(p.body_temperature_c))
        throw Error('체온 예약 필드는 null 또는 유한한 숫자여야 합니다.');
    } else if (typeof p.event_id !== 'string' || !p.event_id ||
      !['sos','impact','prolonged_still','heat_exposure'].includes(p.event_type)) {
      throw Error('사건 ID 또는 유형을 확인하세요.');
    }
    const ordered=orderPacket(packet);if(!ordered.accepted)return ordered;
    const key = ordered.key;
    if (seen.has(key)) return {accepted: false, reason: 'duplicate'};
    const old = previousBoots.get(s.assigned_node_id) || new Set();
    if (old.has(packet.boot_id)) return {accepted: false, reason: 'previous_boot'};
    const newer = ordered.newer;
    seen.add(key);
    if (seen.size > config.communication.dedup_limit) seen.delete(seen.values().next().value);
    if (newer) {
      if (s.boot_id !== packet.boot_id) {
        if (s.boot_id) old.add(s.boot_id);
        previousBoots.set(s.assigned_node_id,old);
        s.boot_id = packet.boot_id; s.payload = null;
        s.last_status_mono = null; s.status_received_at = null;
      }
      s.last_seq = packet.seq;
      // A first event alone does not establish the declared heartbeat period.
      if (packet.packet_type === 'soldier_status') {
        s.payload = structuredClone(p); s.last_status_mono = now(); s.status_received_at = iso();
      }
      s.source = packet.source;
      s.last_seen_mono = now(); s.last_seen_at = iso();
      if (s.payload) {
        const recovered = s.connection_state === 'lost';
        s.connection_state = 'connected'; s.data_stale = false;
        if (recovered) eventRecord(`link_restored:${s.assigned_node_id}:${randomUUID()}`,s.assigned_node_id,'link_restored');
      } else {s.connection_state = 'waiting'; s.data_stale = true;}
    }
    if (packet.packet_type === 'event') {
      // Source is part of the incident namespace; repeats retain acknowledgement.
      const incidentKey = JSON.stringify([packet.source,packet.node_id,p.event_id]);
      if (!incidentIds.has(incidentKey)) {
        incidentIds.add(incidentKey);
        const active = p.event_type === 'sos' && events.find(e =>
          e.node_id === packet.node_id && e.source === packet.source &&
          e.event_type === 'sos' && e.event_state !== 'resolved');
        if (active) {
          active.repeat_count++;
          active.last_received_at = iso();
        } else {
          eventRecord(p.event_id,packet.node_id,p.event_type,{mode: p.mode,
            source: packet.source, occurred_uptime_ms: packet.uptime_ms, boot_id: packet.boot_id,
            repeat_count: 1, last_received_at: iso()});
        }
      }
    }
    revision++;
    return {accepted: true, latest: newer};
  }
  function checkTimeouts() {
    for (const s of soldiers) {
      if (s.connection_state !== 'connected' || !s.payload) continue;
      if (now() - s.last_seen_mono > timeoutMs(s.payload.heartbeat_interval_ms,config)) {
        s.connection_state = 'lost'; s.data_stale = true;
        eventRecord(`link_lost:${s.assigned_node_id}:${randomUUID()}`,s.assigned_node_id,'link_lost');
        revision++;
      }
    }
  }
  function action(event_id, action) {
    const e = events.find(e => e.event_id === event_id);
    if (!e) throw Error('사건이 없습니다.');
    if (action === 'ack' && e.event_state === 'open') {
      e.event_state = 'acknowledged'; e.acknowledged_at = iso(); revision++;
    } else if (action === 'resolve' && e.event_state !== 'resolved') {
      const targets = e.event_type === 'sos' ? events.filter(item =>
        item.node_id === e.node_id && item.source === e.source &&
        item.event_type === 'sos' && item.event_state !== 'resolved') : [e];
      const completedAt = iso();
      for (const item of targets) {
        item.event_state = 'resolved'; item.resolved_at = completedAt;
      }
      revision++;
    } else if (!['ack','resolve'].includes(action)) throw Error('지원하지 않는 조작입니다.');
  }
  function snapshot() {
    checkTimeouts();
    return {schema_version: config.app.schema_version, revision, server_time: iso(), source: config.input.mode,
      soldiers: soldiers.map(({last_seen_mono,last_status_mono,last_seq,boot_id,...s}) => ({...structuredClone(s),
        data_stale: s.connection_state !== 'connected' || last_status_mono === null ||
          now()-last_status_mono > timeoutMs(s.payload.heartbeat_interval_ms,config),
        age_ms: last_seen_mono === null ? null : Math.floor(now()-last_seen_mono),
        timeout_ms: s.payload ? timeoutMs(s.payload.heartbeat_interval_ms,config) : null})),
      telemetry: telemetry.snapshot(), events: structuredClone(events)};
  }
  function archive(){return {events:structuredClone(events),incident_ids:[...incidentIds]};}
  function restore(data){
    if(!data)return;
    if(!Array.isArray(data.events)||!Array.isArray(data.incident_ids)||data.incident_ids.some(id=>typeof id!=='string')||data.events.some(e=>typeof e.event_id!=='string'||!['open','acknowledged','resolved'].includes(e.event_state)||!['simulation','device'].includes(e.source)))throw Error('사건 기록 내용 오류');
    events=structuredClone(data.events.filter(e=>e.source===config.input.mode));
    incidentIds=new Set(data.incident_ids);revision++;
  }
  return {reset, ingest, snapshot, action,archive,restore};
}
