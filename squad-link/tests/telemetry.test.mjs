import test from 'node:test';
import assert from 'node:assert/strict';
import {config} from '../core/config.mjs';
import {makeState} from '../core/state.mjs';
import {createApp} from '../communication/server.mjs';
const transport={gateway_id:'gateway_01',route:'simulation',hop_count:0,relay_id:null,rssi_dbm:null};
const env=()=>({schema_version:'1.0',source:'simulation',packet_type:'environment',node_id:'env_01',boot_id:'envboot',seq:1,uptime_ms:0,transport,payload:{air_temperature_c:25,humidity_pct:50,light_raw:100,heartbeat_interval_ms:5000,sensor_status:{dht11:'ok',light:'ok'}}});
const gps=()=>({...env(),packet_type:'gps',node_id:'halo_01',payload:{fix_valid:true,latitude_deg:37.5,longitude_deg:127,hdop:1.2}});
test('environment duplicates and delayed packets cannot refresh readings; stale values stay marked',()=>{
 let clock=0;const state=makeState({now:()=>clock});const p=env();state.ingest(p);clock=10000;
 assert.equal(state.ingest(p).reason,'duplicate');
 assert.equal(state.ingest({...p,seq:0}).reason,'out_of_order');clock=17001;
 assert.equal(state.snapshot().telemetry[0].data_stale,true);
 state.ingest({...p,boot_id:'newboot',seq:0});
 assert.equal(state.ingest({...p,seq:9}).reason,'previous_boot');
});
test('GPS no fix keeps dated previous location without connecting a soldier',()=>{
 const state=makeState();const p=gps();state.ingest(p);
 state.ingest({...p,seq:2,payload:{fix_valid:false,latitude_deg:null,longitude_deg:null,hdop:null}});
 const s=state.snapshot();assert.equal(s.telemetry[0].payload.fix_valid,false);
 assert.equal(s.telemetry[0].last_valid_location.latitude_deg,37.5);
 assert.equal(s.soldiers[0].connection_state,'waiting');
 assert.throws(()=>state.ingest({...p,seq:3,payload:{...p.payload,latitude_deg:91}}));
});
test('environment validates nullable measurements, ADC ranges and optional sensor statuses',()=>{
 const state=makeState();const p=env();
 assert.throws(()=>state.ingest({...p,payload:{...p.payload,humidity_pct:101}}));
 assert.throws(()=>state.ingest({...p,payload:{...p.payload,light_raw:4096}}));
 assert.throws(()=>state.ingest({...p,payload:{...p.payload,flame_detected:true}}));
 state.ingest({...p,payload:{air_temperature_c:null,humidity_pct:null,light_raw:null,heartbeat_interval_ms:5000,sensor_status:{dht11:'unavailable',light:'disabled'}}});
});
test('device mode accepts direct and one-hop relay; rejects simulations and invalid hops; no auto simulator',async()=>{
 const c=structuredClone(config);c.input.mode='device';const app=createApp({config:c,persistence:false});
 await new Promise(r=>app.server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${app.server.address().port}`;
 const post=p=>fetch(base+'/api/ingest',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(p)});
 try{
  const initial=await fetch(base+'/api/state').then(r=>r.json());assert.equal(initial.soldiers[0].connection_state,'waiting');
  const p={...env(),source:'device',transport:{...transport,route:'direct'}};
  assert.equal((await post(p)).status,200);
  assert.equal((await post({...p,seq:2,transport:{...transport,route:'relay',hop_count:1,relay_id:'relay_01'}})).status,200);
  assert.equal((await post({...p,seq:3,transport:{...transport,route:'relay',hop_count:2,relay_id:'relay_01'}})).status,400);
  assert.equal((await post(env())).status,400);
  assert.equal((await fetch(base+'/api/demo/sos',{method:'POST'})).status,400);
 }finally{await app.stop();}
});
test('shared node sequence rejects old GPS/status packets across packet types',()=>{
 const state=makeState();const p=gps();state.ingest({...p,seq:10});
 const status={...p,packet_type:'soldier_status',seq:9,payload:{mode:'normal',heart_rate_bpm:null,heart_rate_quality:'no_contact',motion_state:'unknown',heartbeat_interval_ms:5000,body_temperature_c:null,sensor_status:{heart_rate:'unavailable',imu:'unavailable',body_temperature:'not_implemented',gps:'ok'}}};
 assert.equal(state.ingest(status).reason,'out_of_order');
 state.ingest({...status,seq:11});
 assert.equal(state.ingest({...p,seq:11}).reason,'duplicate');
 state.ingest({...status,boot_id:'reboot',seq:0});
 assert.equal(state.ingest({...p,seq:20}).reason,'previous_boot');
});
