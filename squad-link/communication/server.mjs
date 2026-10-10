import {createAuditLog} from '../core/audit-log.mjs';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {createEventStore} from '../core/event-store.mjs';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {makeState} from '../core/state.mjs';
import {config as defaults,browserConfig} from '../core/config.mjs';
import {createSimulator} from './simulator.mjs';

export function createApp({config=defaults,persistence=config.storage.enabled}={}) {
  const state = makeState({config}), streams = new Set();
  const audit=persistence?createAuditLog(resolve(fileURLToPath(new URL('../',import.meta.url)),config.storage.audit_file)):null;
  const originalIngest=state.ingest;
  state.ingest=packet=>{
    let result;
    try{result=originalIngest(packet);}catch(e){audit?.packet(packet,null,e.message);throw e;}
    audit?.packet(packet,result);return result;
  };
  const simulator=createSimulator(state,config);
  const store=persistence?createEventStore(resolve(fileURLToPath(new URL('../',import.meta.url)),config.storage.event_file)):null;
  const saved=store?.load();
  const loggedLinks=new Set();
  function currentSnapshot(){
    const snapshot=state.snapshot();
    if(config.input.mode==='simulation'&&config.input.driver==='simulator')snapshot.demo=simulator.snapshot();
    for(const event of snapshot.events){
      if(['link_lost','link_restored'].includes(event.event_type)&&!loggedLinks.has(event.event_id)){
        loggedLinks.add(event.event_id);audit?.write(event.event_type,{source:event.source,node_id:event.node_id,event_id:event.event_id});
      }
    }
    store?.save(state.archive());return snapshot;
  }
  function broadcast() {
    const data = `event: state\ndata: ${JSON.stringify(currentSnapshot())}\n\n`;
    for (const res of streams) res.write(data);
  }
  function json(res,status,data) {
    res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
    res.end(JSON.stringify(data));
  }
  async function body(req) {
    let chunks='';
    for await (const chunk of req) {
      chunks+=chunk; if (chunks.length>config.server.max_body_chars) throw Error('요청 데이터가 너무 큽니다.');
    }
    return chunks?JSON.parse(chunks):{};
  }
  const server = http.createServer(async (req,res) => {
    try {
      const path = new URL(req.url,'http://localhost').pathname;
      if (req.method==='GET' && path==='/api/config') return json(res,200,browserConfig(config));
      if (req.method==='GET' && path==='/api/state') return json(res,200,currentSnapshot());
      if (req.method==='GET' && path==='/api/stream') {
        res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache','Connection':'keep-alive'});
        res.write(`event: state\ndata: ${JSON.stringify(currentSnapshot())}\n\n`);
        streams.add(res); req.on('close',()=>streams.delete(res)); return;
      }
      if (req.method==='POST' && path==='/api/ingest') {
        const result=state.ingest(await body(req)); broadcast();return json(res,200,result);
      }
      if (req.method==='POST' && path.startsWith('/api/demo/')) {
        if(config.input.mode!=='simulation'||config.input.driver!=='simulator')throw Error('실제 입력 모드에서는 시연 조작을 사용할 수 없습니다.');
        const demoAction=path.split('/').pop();
        if(demoAction==='reset'){audit?.resetSequence();audit?.write('demo_reset',{source:config.input.mode});}
        simulator.action(demoAction); broadcast();
        return json(res,200,{ok:true,state:currentSnapshot()});
      }
      if (req.method==='POST' && path.startsWith('/api/events/')) {
        const [, , , event_id,action]=path.split('/');
        state.action(decodeURIComponent(event_id),action);audit?.write('incident_action',{source:config.input.mode,event_id:decodeURIComponent(event_id),action});broadcast();return json(res,200,{ok:true,state:currentSnapshot()});
      }
      const files={'/':'index.html','/app.mjs':'app.mjs','/views.mjs':'views.mjs','/style.css':'style.css'};
      if (req.method==='GET' && files[path]) {
        const type=path.endsWith('.mjs')?'text/javascript':path.endsWith('.css')?'text/css':'text/html';
        res.writeHead(200,{'Content-Type':`${type}; charset=utf-8`});
        res.end(await readFile(new URL(`../ui/${files[path]}`,import.meta.url)));return;
      }
      json(res,404,{error:'없는 경로입니다.'});
    } catch (e) {json(res,400,{error:e.message});}
  });
  if(config.input.mode==='simulation'&&config.input.driver==='simulator')simulator.reset();
  state.restore(saved);
  for(const event of state.snapshot().events)loggedLinks.add(event.event_id);
  audit?.write('server_started',{source:config.input.mode,driver:config.input.driver,restored_events:state.archive().events.length});
  store?.save(state.archive());
  const timers=[setInterval(broadcast,config.server.broadcast_interval_ms)];
  if(config.input.mode==='simulation'&&config.input.driver==='simulator')timers.push(setInterval(()=>{simulator.statuses();broadcast();},config.simulation.heartbeat_interval_ms));
  function stop() {
    currentSnapshot();audit?.write('server_stopped',{source:config.input.mode});
    timers.forEach(clearInterval); for (const res of streams) res.end();
    streams.clear(); server.closeAllConnections();
    return new Promise(resolve=>server.close(resolve));
  }
  return {server,stop};
}
