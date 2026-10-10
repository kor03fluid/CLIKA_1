import test from 'node:test';
import assert from 'node:assert/strict';
import {config,validateConfig} from '../core/config.mjs';
import {createApp} from '../communication/server.mjs';
test('one configuration updates simulation, roster, timeout and public UI configuration',async()=>{
 const changed=structuredClone(config);
 changed.squad.soldier_count=10;changed.squad.node_ids=['test_a','test_b'];
 changed.simulation.heartbeat_interval_ms=30000;
 changed.simulation.heart_rate_bpm=[91,95];changed.ui.timezone='UTC';
 const app=createApp({config:validateConfig(changed),persistence:false});
 await new Promise(r=>app.server.listen(0,'127.0.0.1',r));
 const base=`http://127.0.0.1:${app.server.address().port}`;
 try{
  const state=await fetch(base+'/api/state').then(r=>r.json());
  const ui=await fetch(base+'/api/config').then(r=>r.json());
  assert.equal(state.soldiers.length,10);
  assert.equal(state.soldiers[0].assigned_node_id,'test_a');
  assert.equal(state.soldiers[0].payload.heart_rate_bpm,91);
  assert.equal(state.soldiers[0].timeout_ms,92000);
  assert.equal(ui.simulation.heartbeat_interval_ms,30000);
  assert.equal(ui.ui.timezone,'UTC');
  for(const path of ['/','/app.mjs','/style.css'])assert.equal((await fetch(base+path)).status,200);
 }finally{await app.stop();}
});
test('invalid central configuration fails before server startup',()=>{
 const c=structuredClone(config);c.simulation.heartbeat_interval_ms=0;
 assert.throws(()=>validateConfig(c),/설정 오류/);
});
