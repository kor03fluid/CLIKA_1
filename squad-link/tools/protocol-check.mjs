// 서버가 실행 중일 때: node tools/protocol-check.mjs
import assert from 'node:assert/strict';
import {config} from '../core/config.mjs';
const base=`http://localhost:${config.server.port}`;
if(config.input.mode!=='simulation')throw Error('이 검사는 simulation 모드에서 실행하세요.');
const boot=`check_${Date.now()}`;
const transport={gateway_id:config.simulation.gateway_id,route:'simulation',hop_count:0,relay_id:null,rssi_dbm:null};
const packet={schema_version:config.app.schema_version,packet_type:'environment',node_id:config.environment.node_ids[0],boot_id:boot,seq:0,source:'simulation',uptime_ms:0,transport,payload:{air_temperature_c:26,humidity_pct:48,light_raw:Math.min(1200,config.environment.adc_max),heartbeat_interval_ms:config.simulation.heartbeat_interval_ms,sensor_status:{dht11:'ok',light:'ok'}}};
async function send(p){const r=await fetch(base+'/api/ingest',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(p)});const result=await r.json();if(!r.ok)console.log('서버 응답:',r.status,result);return {status:r.status,result};}
assert.equal((await send(packet)).status,200);assert.equal((await send(packet)).result.reason,'duplicate');
assert.equal((await send({...packet,seq:1,payload:{...packet.payload,humidity_pct:101}})).status,400);
const gps={...packet,packet_type:'gps',node_id:config.squad.node_ids[0],seq:0,payload:{fix_valid:true,latitude_deg:37.5,longitude_deg:127,hdop:1.2}};
assert.equal((await send(gps)).status,200);
assert.equal((await send({...gps,seq:1,payload:{fix_valid:false,latitude_deg:null,longitude_deg:null,hdop:null}})).status,200);
console.log('통과: 환경 수신, 중복 거부, 잘못된 습도 거부, GPS 수신→미수신. 관제 하단에서 확인하세요. 모든 값은 가상입니다.');
