import test from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../communication/server.mjs';
import {config} from '../core/config.mjs';
test('stop immediately returns feedback and SSE reports timeout without refresh',async()=>{
 const c=structuredClone(config);c.simulation.heartbeat_interval_ms=50;
 c.communication.minimum_timeout_ms=100;c.communication.heartbeat_multiplier=1;c.communication.grace_ms=1;c.server.broadcast_interval_ms=20;
 const app=createApp({config:c,persistence:false});await new Promise(r=>app.server.listen(0,'127.0.0.1',r));
 const base=`http://127.0.0.1:${app.server.address().port}`;const controller=new AbortController();
 const timeout=setTimeout(()=>controller.abort(),3000);
 try{
  const res=await fetch(base+'/api/stream',{signal:controller.signal});const reader=res.body.getReader();
  const stopped=await fetch(base+'/api/demo/stop',{method:'POST'}).then(r=>r.json());
  assert.deepEqual(stopped.state.demo.stopped_node_ids,['halo_02']);
  let buffer='',lost=null;
  while(!lost){const chunk=await reader.read();if(chunk.done)throw Error('SSE ended before timeout');buffer+=new TextDecoder().decode(chunk.value);
   let split;while((split=buffer.indexOf('\n\n'))>=0){const part=buffer.slice(0,split);buffer=buffer.slice(split+2);const line=part.split('\n').find(l=>l.startsWith('data: '));if(line){const s=JSON.parse(line.slice(6));if(s.soldiers[1].connection_state==='lost')lost=s;}}
  }
  assert.ok(lost.events.some(e=>e.event_type==='link_lost'&&e.node_id==='halo_02'));
  const restored=await fetch(base+'/api/demo/resume',{method:'POST'}).then(r=>r.json());
  assert.equal(restored.state.soldiers[1].connection_state,'connected');assert.deepEqual(restored.state.demo.stopped_node_ids,[]);
 }finally{clearTimeout(timeout);controller.abort();await app.stop();}
});
