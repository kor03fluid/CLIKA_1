import test from 'node:test';
import assert from 'node:assert/strict';
import {createApp} from '../communication/server.mjs';

test('two viewer streams receive the same SOS and acknowledgement from one server',async()=>{
  const app=createApp({persistence:false});await new Promise(r=>app.server.listen(0,'127.0.0.1',r));
  const base=`http://127.0.0.1:${app.server.address().port}`;
  const controllers=[new AbortController(),new AbortController()];
  async function viewer(signal){
    const res=await fetch(base+'/api/stream',{signal});const reader=res.body.getReader();let buffer='';
    return async function next(predicate=()=>true){
      while(true){
        let split=buffer.indexOf('\n\n');
        if(split>=0){const part=buffer.slice(0,split);buffer=buffer.slice(split+2);
          const line=part.split('\n').find(l=>l.startsWith('data: '));
          if(line){const state=JSON.parse(line.slice(6));if(predicate(state))return state;}continue;}
        const chunk=await reader.read();if(chunk.done)throw Error('Stream ended');
        buffer+=new TextDecoder().decode(chunk.value);
      }
    };
  }
  try{
    const [a,b]=await Promise.all(controllers.map(c=>viewer(c.signal)));
    const initial=await Promise.all([a(),b()]);assert.equal(initial[0].soldiers.length,8);
    assert.equal(initial[0].soldiers.filter(s=>s.connection_state==='connected').length,2);
    // Connections open a few ms apart, so elapsed ages can differ on initial reads.
    const stable=list=>list.map(({age_ms,...s})=>s);
    assert.deepEqual(stable(initial[0].soldiers),stable(initial[1].soldiers));
    assert.equal((await fetch(base+'/api/demo/sos',{method:'POST'})).status,200);
    const [one,two]=await Promise.all([a(s=>s.events.some(e=>e.event_type==='sos')),b(s=>s.events.some(e=>e.event_type==='sos'))]);
    assert.equal(one.revision,two.revision);assert.deepEqual(one.events,two.events);
    const id=one.events[0].event_id;
    assert.equal((await fetch(base+`/api/events/${encodeURIComponent(id)}/ack`,{method:'POST'})).status,200);
    const confirmed=await Promise.all([a(s=>s.events[0]?.event_state==='acknowledged'),b(s=>s.events[0]?.event_state==='acknowledged')]);
    assert.deepEqual(confirmed[0].events,confirmed[1].events);
    assert.equal(confirmed[0].soldiers[0].connection_state,'connected');
    assert.equal((await fetch(base+'/')).status,200);
  }finally{controllers.forEach(c=>c.abort());await app.stop();}
});
