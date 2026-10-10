const states=new Set(['ok','unavailable','not_implemented','disabled']);
export function validateTelemetry(packet,config){
 const p=packet.payload;
 if(!p||typeof p!=='object')throw Error('payload가 필요합니다.');
 if(packet.packet_type==='gps'){
  if(!config.squad.node_ids.includes(packet.node_id)||typeof p.fix_valid!=='boolean')throw Error('GPS 노드·유효 여부 오류');
  if(!p.fix_valid){if(p.latitude_deg!==null||p.longitude_deg!==null||p.hdop!==null)throw Error('GPS 미수신 좌표는 null이어야 합니다.');}
  else if(!Number.isFinite(p.latitude_deg)||Math.abs(p.latitude_deg)>90||!Number.isFinite(p.longitude_deg)||Math.abs(p.longitude_deg)>180||(p.hdop!==null&&(!Number.isFinite(p.hdop)||p.hdop<0)))throw Error('GPS 좌표·품질 범위 오류');
 }else{
  if(!config.environment.node_ids.includes(packet.node_id))throw Error('미등록 환경 노드');
  if(!Number.isSafeInteger(p.heartbeat_interval_ms)||p.heartbeat_interval_ms<=0||!p.sensor_status||!['dht11','light'].every(k=>states.has(p.sensor_status[k])))throw Error('환경 보고 주기·센서 상태 오류');
  if(p.sensor_status.dht11==='ok'){
   if(!Number.isFinite(p.air_temperature_c)||!Number.isFinite(p.humidity_pct)||p.humidity_pct<0||p.humidity_pct>100)throw Error('환경 온습도 오류');
  }else if(p.air_temperature_c!==null||p.humidity_pct!==null)throw Error('미측정 온습도는 null이어야 합니다.');
  if(p.sensor_status.light==='ok'){
   if(!Number.isSafeInteger(p.light_raw)||p.light_raw<0||p.light_raw>config.environment.adc_max)throw Error('조도 ADC 범위 오류');
  }else if(p.light_raw!==null)throw Error('미측정 조도는 null이어야 합니다.');
  for(const [field,key] of Object.entries({sound_detected:'sound',flame_detected:'flame',shock_detected:'shock',reed_closed:'reed'})){
   if(field in p&&(!states.has(p.sensor_status[key])||(p.sensor_status[key]==='ok'?typeof p[field]!=='boolean':p[field]!==null)))throw Error('추가 환경 센서 값·상태 오류');
  }
 }
}
export function createTelemetry({now,iso,config}){
 const latest=new Map(),locations=new Map();
 function ingest(packet){
  const key=packet.node_id;const prior=latest.get(key);
  if(prior?.old_boots.has(packet.boot_id))return {accepted:false,reason:'previous_boot'};
  const old=prior?.old_boots??new Set();
  if(prior?.boot_id===packet.boot_id&&packet.seq<=prior.seq)return {accepted:false,reason:packet.seq===prior.seq?'duplicate':'out_of_order'};
  if(prior&&prior.boot_id!==packet.boot_id)old.add(prior.boot_id);
  const entry={node_id:key,packet_type:packet.packet_type,source:packet.source,boot_id:packet.boot_id,seq:packet.seq,payload:structuredClone(packet.payload),received_at:iso(),mono:now(),old_boots:old};
  latest.set(key,entry);
  if(packet.packet_type==='gps'&&packet.payload.fix_valid)locations.set(key,{...structuredClone(packet.payload),received_at:entry.received_at});
  return {accepted:true,latest:true};
 }
 function snapshot(){return [...latest.values()].map(({mono,old_boots,seq,boot_id,...e})=>({...structuredClone(e),age_ms:Math.floor(now()-mono),data_stale:now()-mono> (e.packet_type==='environment'?Math.max(config.communication.minimum_timeout_ms,config.communication.heartbeat_multiplier*e.payload.heartbeat_interval_ms+config.communication.grace_ms):config.environment.gps_stale_ms),last_valid_location:locations.get(e.node_id)??null}));}
 return {ingest,snapshot,reset(){latest.clear();locations.clear();}};
}
