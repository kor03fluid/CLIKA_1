import {mkdirSync,readFileSync,writeFileSync,renameSync} from 'node:fs';
import {dirname} from 'node:path';
export function createEventStore(path){
 let previous=null;
 function load(){
  let text;
  try{text=readFileSync(path,'utf8');}catch(e){if(e.code==='ENOENT')return null;throw e;}
  const data=JSON.parse(text);
  if(data.version!==1||!Array.isArray(data.events)||!Array.isArray(data.incident_ids))throw Error('사건 저장 파일 형식 오류');
  previous=JSON.stringify(data);return data;
 }
 function save(data){
  const text=JSON.stringify({version:1,...data});if(text===previous)return;
  mkdirSync(dirname(path),{recursive:true});
  writeFileSync(path+'.tmp',text+'\n','utf8');renameSync(path+'.tmp',path);previous=text;
 }
 return {load,save};
}
