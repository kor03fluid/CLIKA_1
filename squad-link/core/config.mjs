import {readFileSync} from 'node:fs';
export function validateConfig(c) {
  const positive=(v,label)=>{if(!Number.isSafeInteger(v)||v<=0)throw Error(`설정 오류: ${label}은 양의 정수여야 합니다.`);};
  if(!['simulator','serial'].includes(c.input.driver))throw Error('설정 오류: input.driver');
  if(typeof c.serial.port!=='string'||!c.serial.port)throw Error('설정 오류: serial.port');
  for(const [key,value] of Object.entries(c.serial))if(key!=='port'&&(!Number.isFinite(value)||value<=0))throw Error('설정 오류: serial.'+key);
  if(!['simulation','device'].includes(c.input.mode))throw Error('설정 오류: input.mode');
  if(!Array.isArray(c.environment.node_ids)||new Set(c.environment.node_ids).size!==c.environment.node_ids.length||c.environment.node_ids.some(id=>typeof id!=='string'||!id||c.squad.node_ids.includes(id)))throw Error('설정 오류: 환경 노드 ID');
  positive(c.environment.adc_max,'adc_max');positive(c.environment.gps_stale_ms,'gps_stale_ms');
  if(typeof c.storage.enabled!=='boolean'||typeof c.storage.event_file!=='string'||!c.storage.event_file||typeof c.storage.audit_file!=='string'||!c.storage.audit_file)throw Error('설정 오류: storage');
  positive(c.squad.soldier_count,'soldier_count');
  positive(c.server.port,'port');if(c.server.port>65535)throw Error('설정 오류: port 범위');
  for(const [k,v] of Object.entries(c.server))if(k.endsWith('_ms')||k==='max_body_chars')positive(v,k);
  for(const [k,v] of Object.entries(c.communication))positive(v,k);
  positive(c.simulation.heartbeat_interval_ms,'heartbeat_interval_ms');
  if(!Array.isArray(c.squad.node_ids)||c.squad.node_ids.length<2||c.squad.node_ids.length>c.squad.soldier_count||new Set(c.squad.node_ids).size!==c.squad.node_ids.length||c.squad.node_ids.some(n=>typeof n!=='string'||!n))throw Error('설정 오류: 장치 ID는 중복 없이 최소 2개, 병사 수 이하로 지정하세요.');
  if(c.simulation.heart_rate_bpm.length!==c.squad.node_ids.length||c.simulation.heart_rate_bpm.some(v=>!Number.isFinite(v)||v<=0))throw Error('설정 오류: 장치마다 양의 가상 심박값을 지정하세요.');
  if(!['normal','covert'].includes(c.simulation.mode)||!['moving','still','unknown'].includes(c.simulation.motion_state))throw Error('설정 오류: 가상 운용 모드·움직임');
  positive(c.ui.fallback_poll_ms,'fallback_poll_ms');
  if(!['pending','completed'].includes(c.ui.default_event_tab))throw Error('설정 오류: 사건 탭');
  new Intl.DateTimeFormat('ko-KR',{timeZone:c.ui.timezone});
  return c;
}
export const config=validateConfig(JSON.parse(readFileSync(new URL('../config/system.json',import.meta.url),'utf8')));
export const timeoutMs=(interval,c=config)=>Math.max(c.communication.minimum_timeout_ms,c.communication.heartbeat_multiplier*interval+c.communication.grace_ms);
export const browserConfig=(c=config)=>({app:c.app,input:c.input,environment:c.environment,squad:c.squad,ui:c.ui,simulation:{heartbeat_interval_ms:c.simulation.heartbeat_interval_ms},communication:c.communication});
