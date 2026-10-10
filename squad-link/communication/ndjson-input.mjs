// JSON 한 줄씩 표준입력으로 받아 관제에 전달합니다. 실제 COM 포트 읽기는 아직 별도입니다.
import {createInterface} from 'node:readline';
import {config} from '../core/config.mjs';
const base=`http://localhost:${config.server.port}`;
const lines=createInterface({input:process.stdin,crlfDelay:Infinity});
for await(const line of lines){
 if(!line.trim())continue;
 try{
  const packet=JSON.parse(line);
  const res=await fetch(base+'/api/ingest',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(packet)});
  console.log(JSON.stringify({status:res.status,result:await res.json()}));
 }catch(error){console.error(JSON.stringify({error:error.message}));}
}
