// 시험용: 팀장 관제 서버(squad-link)를 저장 없이 빈 포트에 띄우고 "PORT <번호>"를 한 줄 낸다.
// 표준입력이 닫히면 끝난다. 팀장 코드는 고치지 않고 createApp만 부른다.
// 사용: node lead_server_run.mjs <squad-link 폴더> [simulation|device]
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const [leadRoot, mode = 'simulation'] = process.argv.slice(2);
const root = resolve(leadRoot);
const {createApp} = await import(pathToFileURL(`${root}/communication/server.mjs`).href);
const {config} = await import(pathToFileURL(`${root}/core/config.mjs`).href);
const cfg = structuredClone(config);
cfg.input.mode = mode;
const app = createApp({config: cfg, persistence: false});
await new Promise(r => app.server.listen(0, '127.0.0.1', r));
console.log(`PORT ${app.server.address().port}`);
process.stdin.resume();
process.stdin.on('end', () => app.stop().then(() => process.exit(0)));
