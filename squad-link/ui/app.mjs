import {rosterView,detailView,eventsView,telemetryView} from './views.mjs';
const $=s=>document.querySelector(s);
let config,selectedTab,selectedSoldier,latestState=null,pollBusy=false;
const time=t=>t?new Date(t).toLocaleTimeString('ko-KR',{timeZone:config.ui.timezone,hour12:false}):'없음';
function render(state){
 if(latestState&&Date.parse(state.server_time)<Date.parse(latestState.server_time))return;
 latestState=state;
 const stopped=state.demo?.stopped_node_ids||[];
 const stoppedSoldiers=state.soldiers.filter(s=>stopped.includes(s.assigned_node_id));
 $('#action-status').textContent=stoppedSoldiers.map(s=>s.connection_state==='lost'?`병사 ${s.soldier_id.slice(-2)} · 통신 두절 감지됨`:`병사 ${s.soldier_id.slice(-2)} · 송신 중단됨 · 두절 판정까지 약 ${Math.max(0,Math.ceil((s.timeout_ms-s.age_ms)/1000))}초`).join(' / ');
 const eventScroll=$('#events').scrollTop,telemetryScroll=$('#telemetry').scrollTop;
 selectedSoldier=state.soldiers.some(s=>s.soldier_id===selectedSoldier)?selectedSoldier:state.soldiers[0]?.soldier_id;
 const pending=state.events.filter(e=>e.event_state!=='resolved'),completed=state.events.filter(e=>e.event_state==='resolved');
 const metrics=[['분대원',state.soldiers.length,''],['연결',state.soldiers.filter(s=>s.connection_state==='connected').length,'fine'],['통신 두절',state.soldiers.filter(s=>s.connection_state==='lost').length,'warn'],['확인 전',state.events.filter(e=>e.event_state==='open').length,'danger']];
 $('#summary').innerHTML=metrics.map(([label,value,cls])=>`<div class="metric ${value?cls:''}"><span>${label}</span><strong>${value.toString().padStart(2,'0')}</strong></div>`).join('');
 $('#pending-count').textContent=pending.length;$('#completed-count').textContent=completed.length;
 document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tab===selectedTab)));
 // Preserve keyboard focus across live one-second updates.
 const focus=document.activeElement?.dataset;
 const focusKey=focus?.soldier?{key:'soldier',value:focus.soldier}:focus?.event?{key:'event',value:focus.event,action:focus.action}:null;
 $('#roster').innerHTML=rosterView(state,selectedSoldier);
 $('#soldier-detail').innerHTML=detailView(state,selectedSoldier,time);
 $('#events').innerHTML=eventsView(selectedTab==='pending'?pending:completed,state,time,selectedTab);
 $('#telemetry').innerHTML=telemetryView(state.telemetry||[],time);
 $('#events').scrollTop=eventScroll;$('#telemetry').scrollTop=telemetryScroll;
 if(focusKey){const buttons=[...document.querySelectorAll('button')];buttons.find(b=>b.dataset[focusKey.key]===focusKey.value&&(!focusKey.action||b.dataset.action===focusKey.action))?.focus({preventScroll:true});}
}
async function post(path){
 $('#error').hidden=true;
 try{const res=await fetch(path,{method:'POST'});const data=await res.json();if(!res.ok)throw Error(data.error||'처리 실패');if(data.state)render(data.state);}
 catch(e){$('#error').textContent=e.message;$('#error').hidden=false;}
}
document.addEventListener('click',e=>{
 const b=e.target.closest('button');if(!b||b.disabled)return;
 if(b.dataset.soldier){selectedSoldier=b.dataset.soldier;if(latestState)render(latestState);return;}
 if(b.dataset.tab){selectedTab=b.dataset.tab;if(latestState)render(latestState);return;}
 if(b.dataset.demo)post(`/api/demo/${b.dataset.demo}`);
 if(b.dataset.event)post(`/api/events/${encodeURIComponent(b.dataset.event)}/${b.dataset.action}`);
});
async function start(){
 try{
  const response=await fetch('/api/config');if(!response.ok)throw Error('설정 수신 실패');config=await response.json();selectedTab=config.ui.default_event_tab;
  document.title=`${config.app.name} 관제`;$('#app-name').textContent=config.app.name;
  $('.tag').textContent=config.input.mode==='device'?'실제 입력':'가상 데이터';
  if(config.input.mode==='device'||config.input.driver==='serial')document.querySelectorAll('[data-demo]').forEach(b=>b.disabled=true);
  const interval=config.simulation.heartbeat_interval_ms;
  const timeout=Math.max(config.communication.minimum_timeout_ms,config.communication.heartbeat_multiplier*interval+config.communication.grace_ms);
  $('#demo-help').textContent=config.input.driver==='serial'?'USB 입력 사용 중 · 시연 조작 비활성화':`가상 보고 ${interval/1000}초 · ${timeout/1000}초 초과 시 두절 · 초기화하면 저장된 사건이 삭제됩니다.`;
  // SSE provides live updates; periodic HTTP snapshots also recover missed updates.
  async function refresh(){
   if(pollBusy)return;pollBusy=true;
   try{const res=await fetch('/api/state',{cache:'no-store'});if(!res.ok)throw Error('상태 갱신 실패');render(await res.json());$('#server').textContent='관제 서버 연결';$('#server').classList.remove('disconnected');}
   catch(e){$('#server').textContent='서버 연결 끊김 · 갱신 중단';$('#server').classList.add('disconnected');}
   finally{pollBusy=false;}
  }
  await refresh();setInterval(refresh,config.ui.fallback_poll_ms||2000);
  const stream=new EventSource('/api/stream');
  stream.addEventListener('state',e=>{const state=JSON.parse(e.data);render(state);$('#server').textContent='관제 서버 연결';$('#server').classList.remove('disconnected');});
  stream.onerror=()=>{$('#server').textContent='서버 연결 끊김 · 갱신 중단';$('#server').classList.add('disconnected');};
 }catch(e){$('#error').textContent=e.message;$('#error').hidden=false;}
}
start();
