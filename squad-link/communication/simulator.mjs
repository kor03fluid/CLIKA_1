import {timeoutMs} from '../core/config.mjs';
export function createSimulator(state,config,{random=Math.random,now=()=>performance.now()}={}) {
  let seq,manualStop,boot,started,sosCounter,issueCounter,fault,outage,pending,next,randomOn;
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
  function reset(){state.reset();seq=ids.map(()=>0);manualStop=ids.map(()=>false);fault=ids.map(()=>false);outage=ids.map(()=>0);pending=ids.map(()=>null);next=ids.map(()=>null);randomOn=ri.enabled;sosCounter=0;issueCounter=0;boot=`demo_${Date.now()}`;started=performance.now();statuses();}
  const delay=()=>ri.min_delay_ms+Math.floor(random()*(ri.max_delay_ms-ri.min_delay_ms+1));
  function kindFor(i){
    const kinds=[['impact',5],['fault',3],...(manualStop[i]?[]:[['link',2]])];
    let r=random()*kinds.reduce((s,[,w])=>s+w,0);
    for(const [k,w] of kinds)if((r-=w)<0)return k;
    return kinds[0][0];
  }
  function fire(i,kind=kindFor(i)){
    const t=now();
    if(kind==='impact')state.ingest(packet(i,'event',{mode:config.simulation.mode,event_type:'impact',event_id:`${ids[i]}:${boot}:impact:${++issueCounter}`}));
    else if(kind==='fault'){fault[i]=true;if(live(i))status(i);}
    else outage[i]=t+outageMs;
    pending[i]={kind,at:t,seen:false};next[i]=null;
  }
  /** Per second: ends link outages, schedules and fires random issues. Returns true when the state changed. */
  function tick(){
    const t=now();let changed=false;
    ids.forEach((_,i)=>{
      if(outage[i]&&t>=outage[i]){outage[i]=0;if(pending[i]?.kind==='link')pending[i]=null;if(live(i))status(i);changed=true;}
      if(!randomOn||pending[i]||manualStop[i])return;
      if(next[i]===null)next[i]=t+delay();
      else if(t>=next[i]){fire(i);changed=true;}
    });
    return changed;
  }
  /** A maintenance report for a simulated node: a repaired sensor works again; back in service ends the issue. */
  function maintenance(node,m){
    const i=ids.indexOf(node);const p=pending[i];
    if(i<0||!m||!p||p.kind==='link')return false;
    // a report sent before maintenance saw the new issue must not end it
    if(m.status!=='go'||m.items.some(x=>x.kind===p.kind))p.seen=true;
    if(!p.seen)return false;
    let changed=false;
    if(fault[i]&&!m.items.some(x=>x.kind==='fault'&&x.state==='open')){fault[i]=false;if(live(i))status(i);changed=true;}
    if(m.status==='go'){pending[i]=null;next[i]=null;}
    return changed;
  }
  function action(name){
    if(name==='reset')reset();
    else if(name==='sos')state.ingest(packet(0,'event',{mode:config.simulation.mode,event_type:'sos',event_id:`${ids[0]}:${boot}:sos:${++sosCounter}`}));
    else if(name==='stop')manualStop[1]=true;
    else if(name==='resume'){manualStop[1]=false;if(live(1))status(1);}
    else if(name==='random_on'){randomOn=true;}
    else if(name==='random_off'){randomOn=false;next=ids.map(()=>null);}
    else if(name==='issue'){
      const free=ids.map((_,i)=>i).filter(i=>!pending[i]&&!manualStop[i]);
      if(!free.length)throw Error('모든 노드가 이전 이슈의 정비를 기다리는 중입니다.');
      fire(free[Math.floor(random()*free.length)]);
    }
    else throw Error('없는 시연 조작입니다.');
  }
  function snapshot(){
    const t=now();
    return {stopped_node_ids:ids.filter((_,i)=>!live(i)),random_issues:{enabled:!!randomOn,nodes:ids.map((node_id,i)=>({node_id,
      pending:pending[i]?.kind||null,next_in_ms:next[i]===null?null:Math.max(0,Math.round(next[i]-t))}))}};
  }
  return {reset,statuses,action,tick,maintenance,snapshot};
}
