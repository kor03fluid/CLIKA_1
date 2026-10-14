import test from 'node:test';
import assert from 'node:assert/strict';
import {makeState} from '../core/state.mjs';
import {createSimulator} from '../communication/simulator.mjs';
import {createApp} from '../communication/server.mjs';
import {config,timeoutMs,validateConfig} from '../core/config.mjs';

function fixture(){
  let elapsed=0;
  const state=makeState({now:()=>elapsed,wall:()=>new Date(1728000000000+elapsed)});
  const status={schema_version:'1.0',packet_type:'soldier_status',node_id:'halo_01',boot_id:'a',seq:1,source:'simulation',uptime_ms:0,
    payload:{mode:'normal',heart_rate_bpm:78,heart_rate_quality:'good',motion_state:'moving',heartbeat_interval_ms:5000,
      sensor_status:{heart_rate:'ok',imu:'ok',body_temperature:'not_implemented',gps:'disabled'},body_temperature_c:null},
    transport:{gateway_id:'gateway_01',route:'simulation',hop_count:0,relay_id:null,rssi_dbm:null}};
  const event=(seq,event_id,event_type,node_id='halo_01')=>({...status,node_id,packet_type:'event',seq,payload:{event_id,event_type,mode:'normal'}});
  return {state,status,event,advance:ms=>{elapsed+=ms;}};
}
const report=(node_id,status,extra={})=>({schema_version:'1.0',node_id,status,equipment:'hailo Modern',reporter:'HoloHand AI 정비',...extra});

test('a maintenance report sets the soldier equipment state and only changes it when the content changes',()=>{
  const {state,status,advance}=fixture();state.ingest(status);
  assert.equal(state.snapshot().soldiers[0].maintenance,null);
  const first=state.maintenance(report('halo_01','limited',{reasons:['전원·제어 기능 저하'],items:[{id:'S1',kind:'impact',label:'HP-01L 충격 감지',state:'open'}]}));
  assert.equal(first.changed,true);
  let m=state.snapshot().soldiers[0].maintenance;
  assert.equal(m.status,'limited');assert.deepEqual(m.items.map(x=>x.state),['open']);assert.equal(m.reported_at,m.changed_at);
  advance(1000);
  assert.equal(state.maintenance(report('halo_01','limited',{reasons:['전원·제어 기능 저하'],items:[{id:'S1',kind:'impact',label:'HP-01L 충격 감지',state:'open'}]})).changed,false);
  m=state.snapshot().soldiers[0].maintenance;assert.notEqual(m.reported_at,m.changed_at);
  assert.equal(state.maintenance(report('halo_01','go')).changed,true);
  assert.equal(state.snapshot().soldiers[0].maintenance.status,'go');
  assert.equal(state.snapshot().soldiers[1].maintenance,null);
  state.reset();assert.equal(state.snapshot().soldiers[0].maintenance,null);
});

test('invalid maintenance reports are refused',()=>{
  const {state}=fixture();
  assert.throws(()=>state.maintenance(report('halo_09','go')),/미등록/);
  assert.throws(()=>state.maintenance(report('halo_01','ok')),/go·limited·nogo/);
  assert.throws(()=>state.maintenance({...report('halo_01','go'),schema_version:'0.9'}),/규격 버전/);
  assert.throws(()=>state.maintenance(report('halo_01','go',{items:[{state:'done'}]})),/open·repaired·monitor/);
  assert.throws(()=>state.maintenance(report('halo_01','go',{reasons:'x'})),/판정 사유/);
  assert.throws(()=>state.maintenance(report('halo_01','go',{equipment:'x'.repeat(61)})),/장비 이름/);
  assert.throws(()=>state.maintenance(report('halo_01','go',{items:Array.from({length:21},()=>({state:'open'}))})),/정비 항목/);
  assert.throws(()=>state.maintenance([]),/형식/);
});

test('maintenance closes only the reported soldier impact incidents, never SOS or another soldier',()=>{
  const {state,status,event}=fixture();
  state.ingest(status);state.ingest({...status,node_id:'halo_02'});
  state.ingest(event(2,'imp1','impact'));state.ingest(event(3,'sos1','sos'));state.ingest(event(2,'imp2','impact','halo_02'));
  state.action('imp1','ack');
  const res=state.maintenance(report('halo_01','go',{resolved_event_ids:['imp1','sos1','imp2','nope']}));
  assert.deepEqual(res.resolved,['imp1']);
  const events=state.snapshot().events;
  const by=id=>events.find(e=>e.event_id===id);
  assert.equal(by('imp1').event_state,'resolved');assert.equal(by('imp1').resolved_by,'maintenance');
  assert.equal(by('sos1').event_state,'open');assert.equal(by('imp2').event_state,'open');
  assert.deepEqual(state.maintenance(report('halo_01','go',{resolved_event_ids:['imp1']})).resolved,[],'already closed');
});

function sim({enabled=true,randoms=[]}={}){
  let t=0;const c=structuredClone(config);
  c.simulation.random_issues={enabled,min_delay_ms:1000,max_delay_ms:1000,outage_ms:30000};
  const state=makeState({config:c});
  const queue=[...randoms];
  const s=createSimulator(state,c,{random:()=>queue.length?queue.shift():0,now:()=>t});
  s.reset();
  const node=(id)=>state.snapshot().soldiers.find(x=>x.assigned_node_id===id);
  const give=(id,status,items=[])=>s.maintenance(id,state.maintenance(report(id,status,{items})).record);
  return {s,state,node,give,at:ms=>{t=ms;}};
}

test('random impact waits for maintenance to see it and report the equipment back in service',()=>{
  const {s,state,give,at}=sim({randoms:[0,0,0,0]});
  assert.equal(s.tick(),false,'first tick schedules');
  at(999);assert.equal(s.tick(),false);
  at(1000);assert.equal(s.tick(),true,'both nodes fire');
  assert.deepEqual(state.snapshot().events.filter(e=>e.event_type==='impact').map(e=>e.node_id).sort(),['halo_01','halo_02']);
  assert.deepEqual(s.snapshot().random_issues.nodes.map(n=>n.pending),['impact','impact']);
  at(5000);s.tick();assert.equal(state.snapshot().events.filter(e=>e.event_type==='impact').length,2,'no second issue while one waits');
  give('halo_01','go');assert.equal(s.snapshot().random_issues.nodes[0].pending,'impact','a go report sent before maintenance saw the impact');
  give('halo_01','limited',[{kind:'impact',state:'open'}]);give('halo_01','go');
  assert.equal(s.snapshot().random_issues.nodes[0].pending,null);
  s.tick();assert.equal(s.snapshot().random_issues.nodes[0].next_in_ms,1000,'next issue scheduled');
});

test('a random sensor failure is repaired by maintenance and a random outage resumes by itself',()=>{
  const {s,node,give,at}=sim({randoms:[0,0,0.6,0.9]});
  s.tick();at(1000);s.tick();
  assert.equal(node('halo_01').payload.sensor_status.imu,'unavailable');assert.equal(node('halo_01').payload.motion_state,'unknown');
  assert.deepEqual(s.snapshot().stopped_node_ids,['halo_02']);
  give('halo_01','limited',[{kind:'fault',state:'open'}]);
  assert.equal(node('halo_01').payload.sensor_status.imu,'unavailable','still open');
  give('halo_01','limited',[{kind:'fault',state:'repaired'}]);
  assert.equal(node('halo_01').payload.sensor_status.imu,'ok','repaired sensor reports ok again');
  assert.equal(s.snapshot().random_issues.nodes[0].pending,'fault','in service only after inspection');
  give('halo_01','go');assert.equal(s.snapshot().random_issues.nodes[0].pending,null);
  const outage=Math.max(30000,timeoutMs(config.simulation.heartbeat_interval_ms)+5000);
  at(1000+outage-1);s.tick();assert.deepEqual(s.snapshot().stopped_node_ids,['halo_02']);
  at(1000+outage);assert.equal(s.tick(),true);
  assert.deepEqual(s.snapshot().stopped_node_ids,[]);assert.equal(s.snapshot().random_issues.nodes[1].pending,null);
});

test('manual stop, switching off and the issue button',()=>{
  const {s,state,at}=sim({enabled:false});
  s.tick();at(5000);s.tick();assert.equal(state.snapshot().events.length,0,'off: nothing happens');
  s.action('stop');s.action('random_on');s.tick();at(10000);s.tick();
  assert.deepEqual(s.snapshot().random_issues.nodes.map(n=>!!n.pending),[true,false],'a manually stopped node gets no issue');
  assert.throws(()=>s.action('issue'),/줄 수 있는 노드가 없습니다/);
  s.action('resume');s.action('issue');
  assert.deepEqual(s.snapshot().random_issues.nodes.map(n=>!!n.pending),[true,true]);
  s.action('random_off');assert.equal(s.snapshot().random_issues.enabled,false);
  s.action('reset');assert.deepEqual(s.snapshot().random_issues.nodes.map(n=>n.pending),[null,null]);
});

test('the maintenance endpoint takes JSON only and shows the report to every viewer',async()=>{
  const app=createApp({persistence:false});await new Promise(r=>app.server.listen(0,'127.0.0.1',r));
  const base=`http://127.0.0.1:${app.server.address().port}`;
  try{
    const text=await fetch(base+'/api/maintenance',{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify(report('halo_01','go'))});
    assert.equal(text.status,415);
    const bad=await fetch(base+'/api/maintenance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(report('halo_01','fine'))});
    assert.equal(bad.status,400);
    const ok=await fetch(base+'/api/maintenance',{method:'POST',headers:{'Content-Type':'application/json; charset=utf-8'},body:JSON.stringify(report('halo_01','limited'))});
    assert.equal(ok.status,200);assert.deepEqual(await ok.json(),{ok:true,accepted:true,changed:true,resolved:[]});
    const state=await fetch(base+'/api/state').then(r=>r.json());
    assert.equal(state.soldiers[0].maintenance.status,'limited');
    assert.ok(state.demo.random_issues,'the demo snapshot lists the random issue state');
  }finally{await app.stop();}
});

test('an issue merged into an item maintenance already tracks, or closed through its impact id, still ends',()=>{
  const {s,state,give,at}=sim({randoms:[0,0,0,0,0,0]});
  give('halo_01','limited',[{kind:'impact',state:'open'}]); // still open from before a demo reset
  s.tick();at(1000);s.tick();
  const ev=state.snapshot().events.find(e=>e.node_id==='halo_01'&&e.event_type==='impact');
  const r=state.maintenance(report('halo_01','go',{resolved_event_ids:[ev.event_id]}));
  s.maintenance('halo_01',r.record,r.resolved);
  assert.equal(s.snapshot().random_issues.nodes[0].pending,null,'known item: the closing go ends it');
  // halo_02 had nothing open: only its own resolved impact id counts as seen
  const ev2=state.snapshot().events.find(e=>e.node_id==='halo_02'&&e.event_type==='impact');
  const r2=state.maintenance(report('halo_02','go',{resolved_event_ids:[ev2.event_id]}));
  s.maintenance('halo_02',r2.record,r2.resolved);
  assert.equal(s.snapshot().random_issues.nodes[1].pending,null,'closing its impact is seeing it');
});

test('monitoring or an unrelated report never repairs the simulated IMU; closing the item does',()=>{
  const {s,node,give,at}=sim({randoms:[0,0,0.6,0]});
  s.tick();at(1000);s.tick();
  assert.equal(node('halo_01').payload.sensor_status.imu,'unavailable');
  give('halo_01','limited',[{kind:'impact',state:'open'}]);
  assert.equal(node('halo_01').payload.sensor_status.imu,'unavailable','a report without the fault item');
  give('halo_01','limited',[{kind:'fault',state:'monitor'}]);
  assert.equal(node('halo_01').payload.sensor_status.imu,'unavailable','관찰 is not a repair');
  give('halo_01','go');
  assert.equal(node('halo_01').payload.sensor_status.imu,'ok','item closed after inspection');
});

test('stop holds the countdown, resume ends a random outage, SOS is refused while node 1 is silent',()=>{
  const {s,state,at}=sim({randoms:[0,0,0,0,0.9]});
  s.tick();s.action('stop');at(500);s.tick();
  assert.deepEqual([s.snapshot().random_issues.nodes[1].held,s.snapshot().random_issues.nodes[1].next_in_ms],[true,null]);
  s.action('resume');at(1000);s.tick();
  assert.equal(s.snapshot().random_issues.nodes[1].pending,null,'no issue the moment it resumes');
  at(2000);s.tick();at(3000);s.tick();
  assert.equal(s.snapshot().random_issues.nodes[1].pending,'link');
  s.action('resume');
  assert.deepEqual([s.snapshot().stopped_node_ids,s.snapshot().random_issues.nodes[1].pending],[[],null],'resume also ends a random outage');
  const c=structuredClone(config);c.simulation.random_issues={enabled:true,min_delay_ms:1000,max_delay_ms:1000,outage_ms:30000};
  let t=0;const st=makeState({config:c});const s0=createSimulator(st,c,{random:()=>0.9,now:()=>t});s0.reset();
  s0.tick();t=1000;s0.tick();
  assert.throws(()=>s0.action('sos'),/SOS/);
  assert.equal(st.snapshot().events.length,0);
  void state;
});

test('random issue settings are validated; over-long event ids are skipped, not fatal',()=>{
  for(const bad of [{enabled:'yes',min_delay_ms:1,max_delay_ms:2,outage_ms:3},{enabled:true,min_delay_ms:5,max_delay_ms:2,outage_ms:3},{enabled:true,min_delay_ms:1.5,max_delay_ms:2,outage_ms:3},null]){
    const c=structuredClone(config);c.simulation.random_issues=bad;
    assert.throws(()=>validateConfig(c),/설정 오류/);
  }
  const {state,status}=fixture();state.ingest(status);
  assert.deepEqual(state.maintenance(report('halo_01','go',{resolved_event_ids:['x'.repeat(300),7]})).resolved,[]);
});

test('the endpoint keeps Korean text split across network chunks and refuses rebinding hosts',async()=>{
  const app=createApp({persistence:false});await new Promise(r=>app.server.listen(0,'127.0.0.1',r));
  const port=app.server.address().port;
  const {request}=await import('node:http');
  const post=(body,host)=>new Promise((resolve,reject)=>{
    const req=request({host:'127.0.0.1',port,path:'/api/maintenance',method:'POST',headers:{'Content-Type':'application/json',...(host?{Host:host}:{})}},res=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>resolve({status:res.statusCode,body:d}));});
    req.on('error',reject);
    const buf=Buffer.from(body);const cut=buf.indexOf(Buffer.from('헤'))+1;
    req.write(buf.subarray(0,cut));setTimeout(()=>req.end(buf.subarray(cut)),20);
  });
  try{
    assert.equal((await post(JSON.stringify(report('halo_01','go',{equipment:'헤일로 장비'})))).status,200);
    const state=await fetch(`http://127.0.0.1:${port}/api/state`).then(r=>r.json());
    assert.equal(state.soldiers[0].maintenance.equipment,'헤일로 장비');
    assert.equal((await post(JSON.stringify(report('halo_01','go',{equipment:'헤일로'})),'attacker.example:8080')).status,421);
  }finally{await app.stop();}
});
