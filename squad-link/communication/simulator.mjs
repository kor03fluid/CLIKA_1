export function createSimulator(state,config) {
  let seq,online,boot,started,sosCounter;
  const ids=config.squad.node_ids;
  function packet(i,type,payload){return {schema_version:config.app.schema_version,packet_type:type,node_id:ids[i],boot_id:boot,seq:seq[i]++,source:'simulation',uptime_ms:Math.floor(performance.now()-started),payload,transport:{gateway_id:config.simulation.gateway_id,route:'simulation',hop_count:0,relay_id:null,rssi_dbm:null}};}
  function statuses(){ids.forEach((_,i)=>{if(online[i])state.ingest(packet(i,'soldier_status',{mode:config.simulation.mode,heart_rate_bpm:config.simulation.heart_rate_bpm[i],heart_rate_quality:'good',motion_state:config.simulation.motion_state,heartbeat_interval_ms:config.simulation.heartbeat_interval_ms,body_temperature_c:null,sensor_status:{heart_rate:'ok',imu:'ok',body_temperature:'not_implemented',gps:'disabled'}}));});}
  function reset(){state.reset();seq=ids.map(()=>0);online=ids.map(()=>true);sosCounter=0;boot=`demo_${Date.now()}`;started=performance.now();statuses();}
  function action(name){
    if(name==='reset')reset();
    else if(name==='sos')state.ingest(packet(0,'event',{mode:config.simulation.mode,event_type:'sos',event_id:`${ids[0]}:${boot}:sos:${++sosCounter}`}));
    else if(name==='stop')online[1]=false;
    else if(name==='resume'){online[1]=true;statuses();}
    else throw Error('없는 시연 조작입니다.');
  }
  return {reset,statuses,action,snapshot:()=>({stopped_node_ids:ids.filter((_,i)=>!online?.[i])})};
}
