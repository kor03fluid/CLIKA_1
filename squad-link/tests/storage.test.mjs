import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {config} from '../core/config.mjs';
import {createApp} from '../communication/server.mjs';
import {createEventStore} from '../core/event-store.mjs';
test('SOS acknowledgement and resolution survive restart; fresh device data still required',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'squad-store-'));const c=structuredClone(config);
 c.storage.event_file=join(dir,'events.json');c.storage.audit_file=join(dir,'audit.ndjson');c.input.mode='device';let app;
 async function start(){app=createApp({config:c});await new Promise(r=>app.server.listen(0,'127.0.0.1',r));return `http://127.0.0.1:${app.server.address().port}`;}
 const packet={schema_version:'1.0',source:'device',packet_type:'event',node_id:'halo_01',boot_id:'boot',seq:0,uptime_ms:0,transport:{gateway_id:'gateway_01',route:'direct',hop_count:0,relay_id:null,rssi_dbm:-60},payload:{mode:'normal',event_id:'sos_storage',event_type:'sos'}};
 const post=(base,path,body)=>fetch(base+path,{method:'POST',headers:{'content-type':'application/json'},body:body?JSON.stringify(body):undefined});
 try{
  let base=await start();assert.equal((await post(base,'/api/ingest',packet)).status,200);
  await post(base,'/api/events/sos_storage/ack');await app.stop();app=null;
  base=await start();let snapshot=await fetch(base+'/api/state').then(r=>r.json());
  assert.equal(snapshot.events[0].event_state,'acknowledged');assert.equal(snapshot.soldiers[0].connection_state,'waiting');
  assert.equal(snapshot.soldiers[0].payload,null);
  await post(base,'/api/events/sos_storage/resolve');await app.stop();app=null;
  base=await start();await post(base,'/api/ingest',{...packet,seq:1});
  snapshot=await fetch(base+'/api/state').then(r=>r.json());
  assert.equal(snapshot.events.length,1);assert.equal(snapshot.events[0].event_state,'resolved');
 }finally{if(app)await app.stop();rmSync(dir,{recursive:true,force:true});}
});
test('corrupt archive fails visibly without overwriting it',()=>{
 const dir=mkdtempSync(join(tmpdir(),'squad-corrupt-'));const path=join(dir,'events.json');
 try{writeFileSync(path,'broken');assert.throws(()=>createEventStore(path).load());}
 finally{rmSync(dir,{recursive:true,force:true});}
});
