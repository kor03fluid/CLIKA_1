import test from 'node:test';
import assert from 'node:assert/strict';
import {makeState} from '../core/state.mjs';
function fixture(){
  let elapsed=0;
  const state=makeState({now:()=>elapsed,wall:()=>new Date(1728000000000+elapsed)});
  const status={schema_version:'1.0',packet_type:'soldier_status',node_id:'halo_01',boot_id:'a',seq:1,source:'simulation',uptime_ms:0,
    payload:{mode:'normal',heart_rate_bpm:78,heart_rate_quality:'good',motion_state:'moving',heartbeat_interval_ms:5000,
      sensor_status:{heart_rate:'ok',imu:'ok',body_temperature:'not_implemented',gps:'disabled'},body_temperature_c:null},
    transport:{gateway_id:'gateway_01',route:'simulation',hop_count:0,relay_id:null,rssi_dbm:null}};
  const event={...status,packet_type:'event',seq:2,payload:{event_id:'sos1',event_type:'sos',mode:'normal'}};
  return {state,status,event,advance:ms=>{elapsed+=ms;}};
}
test('SOS confirmation/resolution never changes connectivity and duplicates preserve incident state',()=>{
  const {state,status,event,advance}=fixture();
  state.ingest(status);state.ingest(event);state.action('sos1','ack');
  state.ingest({...event,seq:3});
  assert.equal(state.snapshot().events.find(e=>e.event_id==='sos1').event_state,'acknowledged');
  advance(17001);
  assert.equal(state.snapshot().soldiers[0].connection_state,'lost');
  state.action('sos1','resolve');
  assert.equal(state.snapshot().soldiers[0].connection_state,'lost');
  state.ingest({...status,seq:4});
  assert.equal(state.snapshot().soldiers[0].connection_state,'connected');
  assert.equal(state.snapshot().events.find(e=>e.event_id==='sos1').event_state,'resolved');
});
test('duplicate packet cannot extend last seen and six unassigned soldiers cannot become lost',()=>{
  const {state,status,advance}=fixture();state.ingest(status);advance(16900);
  assert.equal(state.ingest(status).reason,'duplicate');advance(101);
  const snapshot=state.snapshot();
  assert.equal(snapshot.soldiers[0].connection_state,'lost');
  assert.equal(snapshot.soldiers[1].connection_state,'waiting');
  assert.equal(snapshot.soldiers.filter(s=>s.connection_state==='unassigned').length,6);
  assert.equal(snapshot.events.length,1);state.snapshot();assert.equal(state.snapshot().events.length,1);
});
test('declared reporting interval governs timeout; reboot rejects delayed prior-boot packets',()=>{
  const {state,status,advance}=fixture();status.payload.heartbeat_interval_ms=30000;
  state.ingest(status);advance(32000);assert.equal(state.snapshot().soldiers[0].connection_state,'connected');
  advance(60001);assert.equal(state.snapshot().soldiers[0].connection_state,'lost');
  state.ingest({...status,boot_id:'b',seq:0});
  assert.equal(state.ingest({...status,seq:100}).reason,'previous_boot');
  assert.equal(state.snapshot().soldiers[0].connection_state,'connected');
});
test('no-contact null accepted; invalid quality/value and actual-device ingestion rejected',()=>{
  const {state,status}=fixture();status.payload.heart_rate_quality='no_contact';
  assert.throws(()=>state.ingest(status));status.payload.heart_rate_bpm=null;state.ingest(status);
  assert.equal(state.snapshot().soldiers[0].payload.heart_rate_bpm,null);
  assert.throws(()=>state.ingest({...status,source:'device'}));
});
test('new SOS packet proves link activity without refreshing old measurements',()=>{
  const {state,status,event,advance}=fixture();state.ingest(status);advance(17001);state.ingest(event);
  const s=state.snapshot().soldiers[0];
  assert.equal(s.connection_state,'connected');assert.equal(s.data_stale,true);
  assert.notEqual(s.status_received_at,s.last_seen_at);
});

test('repeated SOS groups until resolution, preserves acknowledgement, and ignores old requests',()=>{
  const {state,status,event}=fixture();state.ingest(status);
  for(let i=0;i<7;i++) state.ingest({...event,seq:i+2,payload:{...event.payload,event_id:`sos${i}`}});
  let incidents=state.snapshot().events;
  assert.equal(incidents.length,1);assert.equal(incidents[0].repeat_count,7);
  state.action('sos0','ack');
  state.ingest({...event,seq:9,payload:{...event.payload,event_id:'sos7'}});
  incidents=state.snapshot().events;
  assert.equal(incidents.length,1);assert.equal(incidents[0].repeat_count,8);
  assert.equal(incidents[0].event_state,'acknowledged');
  state.action('sos0','resolve');
  state.ingest({...event,seq:10,payload:{...event.payload,event_id:'sos6'}});
  assert.equal(state.snapshot().events.length,1);
  state.ingest({...event,seq:11,payload:{...event.payload,event_id:'sos8'}});
  assert.equal(state.snapshot().events.length,2);
  assert.equal(state.snapshot().events[0].event_state,'open');
});

test('resolving SOS does not complete other incident types',()=>{
  const {state,status,event}=fixture();state.ingest(status);state.ingest(event);
  state.ingest({...event,seq:3,payload:{...event.payload,event_id:'impact1',event_type:'impact'}});
  state.action('sos1','ack');state.action('sos1','resolve');
  const events=state.snapshot().events;
  assert.equal(events.find(e=>e.event_id==='sos1').event_state,'resolved');
  assert.equal(events.find(e=>e.event_id==='impact1').event_state,'open');
});
