import {timeoutMs} from '../core/config.mjs';
export function createSimulator(state,config,{random=Math.random,now=()=>performance.now()}={}) {
  let seq,manualStop,boot,started,sosCounter,issueCounter,fault,faultSeen,outage,pending,next,randomOn;
  const ids=config.squad.node_ids;
  // Random issues (simulation only): after a delay each node gets an impact, a failed IMU or a link outage; the
  // next one waits until maintenance has seen the issue and reports the equipment back in service (go).
  const ri=config.simulation.random_issues||{enabled:false,min_delay_ms:60000,max_delay_ms:180000,outage_ms:30000};
  // an outage shorter than the lost-link timeout would end unnoticed: it lasts at least the timeout + 5 s
  const outageMs=Math.max(ri.outage_ms,timeoutMs(config.simulation.heartbeat_interval_ms,config)+5000);
  const live=i=>!manualStop[i]&&!outage[i];
  function packet(i,type,payload){return {schema_version:config.app.schema_version,packet_type:type,node_id:ids[i],boot_id:boot,seq:seq[i]++,source:'simulation',uptime_ms:Math.floor(performance.now()-started),payload,transport:{gateway_id:config.simulation.gateway_id,route:'simulation',hop_count:0,relay_id:null,rssi_dbm:null}};}
  function status(i){state.ingest(packet(i,'soldier_status',{mode:config.simulation.mode,heart_rate_bpm:config.simulation.heart_rate_bpm[i],heart_rate_quality:'good',motion_state:fault[i]?'unknown':config.simulation.motion_state,heartbeat_interval_ms:config.simulation.heartbeat_interval_ms,body_temperature_c:null,sensor_status:{heart_rate:'ok',imu:fault[i]?'unavailable':'ok',body_temperature:'not_implemented',gps:'disabled'}}));}
  function statuses(){ids.forEach((_,i)=>{if(live(i))status(i);});}
  function reset(){state.reset();seq=ids.map(()=>0);manualStop=ids.map(()=>false);fault=ids.map(()=>false);faultSeen=ids.map(()=>false);outage=ids.map(()=>0);pending=ids.map(()=>null);next=ids.map(()=>null);randomOn=ri.enabled;sosCounter=0;issueCounter=0;boot=`demo_${Date.now()}`;started=performance.now();statuses();}
  const delay=()=>ri.min_delay_ms+Math.floor(random()*(ri.max_delay_ms-ri.min_delay_ms+1));
  function kindFor(i){
    const kinds=[['impact',5],['fault',3],...(manualStop[i]?[]:[['link',2]])];
    let r=random()*kinds.reduce((s,[,w])=>s+w,0);
    for(const [k,w] of kinds)if((r-=w)<0)return k;
    return kinds[0][0];
  }
  function fire(i,kind=kindFor(i)){
    const t=now();let event_id=null;
    if(kind==='impact'){event_id=`${ids[i]}:${boot}:impact:${++issueCounter}`;state.ingest(packet(i,'event',{mode:config.simulation.mode,event_type:'impact',event_id}));}
    else if(kind==='fault'){fault[i]=true;faultSeen[i]=false;if(live(i))status(i);}
    else outage[i]=t+outageMs;
    // maintenance already tracking an open item of this kind (e.g. still open from before a demo reset) takes
    // the new issue onto it without sending anything new: it counts as seen
    const known=!!state.maintenanceOf(ids[i])?.items.some(x=>x.kind===kind);
    pending[i]={kind,at:t,seen:known,event_id};next[i]=null;
    if(kind==='fault')faultSeen[i]=known;
  }
  /** Per second: ends link outages, schedules and fires random issues. Returns true when the state changed. */
  function tick(){
    const t=now();let changed=false;
    ids.forEach((_,i)=>{
      if(outage[i]&&t>=outage[i]){outage[i]=0;if(pending[i]?.kind==='link')pending[i]=null;if(live(i))status(i);changed=true;}
      if(manualStop[i]){next[i]=null;return;} // held while stopped; a fresh delay starts after the resume
      if(!randomOn||pending[i])return;
      if(next[i]===null)next[i]=t+delay();
      else if(t>=next[i]){fire(i);changed=true;}
    });
    return changed;
  }
  /**
   * A maintenance report for a simulated node (m: the stored record, resolved: impact event ids it closed).
   * The IMU works again once its item is repaired (or closed after inspection: the item is gone); monitoring is
   * no repair. The issue ends when maintenance has seen it (an item of its kind, or its impact closed) and the
   * equipment is back in service.
   */
  function maintenance(node,m,resolved=[]){
    const i=ids.indexOf(node);
    if(i<0||!m)return false;
    let changed=false;
    const faults=m.items.filter(x=>x.kind==='fault');
    if(fault[i]){
      if(faults.length)faultSeen[i]=true;
      if(faults.some(x=>x.state==='repaired')||(faultSeen[i]&&!faults.length)){fault[i]=false;if(live(i))status(i);changed=true;}
    }
    const p=pending[i];
    if(!p||p.kind==='link')return changed;
    // a report sent before maintenance saw the new issue must not end it
    if(m.items.some(x=>x.kind===p.kind)||(p.event_id&&resolved.includes(p.event_id)))p.seen=true;
    if(p.seen&&m.status==='go'){pending[i]=null;next[i]=null;}
    return changed;
  }
  function action(name){
    if(name==='reset')reset();
    else if(name==='sos'){if(!live(0))throw Error(`${ids[0]}은 송신이 멈춘 상태라 SOS를 보낼 수 없습니다.`);state.ingest(packet(0,'event',{mode:config.simulation.mode,event_type:'sos',event_id:`${ids[0]}:${boot}:sos:${++sosCounter}`}));}
    else if(name==='stop')manualStop[1]=true;
    else if(name==='resume'){manualStop[1]=false;if(outage[1]){outage[1]=0;if(pending[1]?.kind==='link')pending[1]=null;}if(live(1))status(1);} // also ends a random outage
    else if(name==='random_on'){randomOn=true;}
    else if(name==='random_off'){randomOn=false;next=ids.map(()=>null);}
    else if(name==='issue'){
      const free=ids.map((_,i)=>i).filter(i=>!pending[i]&&!manualStop[i]);
      if(!free.length)throw Error('지금 이슈를 줄 수 있는 노드가 없습니다 (정비 대기 · 송신 복구 대기 · 송신 중단 중).');
      fire(free[Math.floor(random()*free.length)]);
    }
    else throw Error('없는 시연 조작입니다.');
  }
  function snapshot(){
    const t=now();
    return {stopped_node_ids:ids.filter((_,i)=>!live(i)),random_issues:{enabled:!!randomOn,nodes:ids.map((node_id,i)=>({node_id,
      pending:pending[i]?.kind||null,held:!!manualStop[i],next_in_ms:next[i]===null?null:Math.max(0,Math.round(next[i]-t))}))}};
  }
  return {reset,statuses,action,tick,maintenance,snapshot};
}
