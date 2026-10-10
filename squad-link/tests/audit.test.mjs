import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createAuditLog} from '../core/audit-log.mjs';
test('audit records accepted, ignored, rejected, sequence gaps and reboot without false gaps from duplicates',()=>{
 const dir=mkdtempSync(join(tmpdir(),'squad-audit-'));const path=join(dir,'audit.ndjson');
 try{
  const audit=createAuditLog(path);const p={source:'simulation',node_id:'halo_01',boot_id:'a',seq:0,packet_type:'event',payload:{event_type:'sos',event_id:'sos1'}};
  audit.packet(p,{accepted:true});audit.packet({...p,seq:3},{accepted:true});
  audit.packet({...p,seq:3},{accepted:false,reason:'duplicate'});
  audit.packet({...p,seq:100},null,'invalid payload');
  audit.packet({...p,seq:4},{accepted:true});audit.packet({...p,boot_id:'b',seq:0},{accepted:true});
  audit.write('incident_action',{source:'simulation',event_id:'sos1',action:'resolve'});
  const lines=readFileSync(path,'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(lines.filter(l=>l.kind==='sequence_gap_observed').length,1);
  assert.equal(lines.find(l=>l.kind==='sequence_gap_observed').count,2);
  assert.equal(lines.filter(l=>l.kind==='reboot_observed').length,1);
  assert.equal(lines.filter(l=>l.kind==='packet_rejected').length,1);
  assert.equal(lines.filter(l=>l.kind==='packet_ignored').length,1);
  assert.equal(lines.at(-1).action,'resolve');assert.ok(lines.every(l=>l.recorded_at));
 }finally{rmSync(dir,{recursive:true,force:true});}
});
