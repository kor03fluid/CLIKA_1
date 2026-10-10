import {appendFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
export function createAuditLog(path,{wall=()=>new Date()}={}){
 const heads=new Map();
 function write(kind,details={}){
  const row={recorded_at:wall().toISOString(),kind,...details};
  mkdirSync(dirname(path),{recursive:true});appendFileSync(path,JSON.stringify(row)+'\n','utf8');
 }
 function packet(packet,result,error){
  const summary=packet&&typeof packet==='object'?Object.fromEntries(['source','node_id','boot_id','seq','packet_type'].map(k=>[k,packet[k]])):{};
  if(error){write('packet_rejected',{...summary,error});return;}
  write(result.accepted?'packet_accepted':'packet_ignored',{...summary,reason:result.reason??null,latest:result.latest??null,...(result.accepted?{payload:packet.payload,transport:packet.transport}: {})});
  if(!result.accepted)return;
  const key=JSON.stringify([packet.source,packet.node_id]);const previous=heads.get(key);
  if(previous&&previous.boot!==packet.boot_id)write('reboot_observed',{...summary,previous_boot_id:previous.boot});
  if(previous&&previous.boot===packet.boot_id&&packet.seq>previous.seq+1)write('sequence_gap_observed',{...summary,from_seq:previous.seq+1,to_seq:packet.seq-1,count:packet.seq-previous.seq-1,note:'관측 순번 공백이며 무선 손실 확정이 아님'});
  if(!previous||previous.boot!==packet.boot_id||packet.seq>previous.seq)heads.set(key,{boot:packet.boot_id,seq:packet.seq});
 }
 return {write,packet,resetSequence(){heads.clear();}};
}
