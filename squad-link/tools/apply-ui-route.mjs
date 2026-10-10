// UI만 교체한 기존 프로젝트의 정적 라우트를 추가합니다. 나머지 서버 코드는 보존합니다.
import {readFileSync,writeFileSync} from 'node:fs';
const file=new URL('../communication/server.mjs',import.meta.url);
let code=readFileSync(file,'utf8');
if(code.includes("'/views.mjs':'views.mjs'")){console.log('UI 모듈 경로가 이미 등록되어 있습니다.');}
else{
 const marker="'/app.mjs':'app.mjs'";
 if(!code.includes(marker))throw Error('서버 파일 형식이 달라 자동 수정하지 않았습니다. 정적 파일 목록에 /views.mjs를 추가해야 합니다.');
 code=code.replace(marker,marker+",'/views.mjs':'views.mjs'");writeFileSync(file,code,'utf8');
 console.log('UI 모듈 경로 등록 완료. 서버를 재시작하세요.');
}
