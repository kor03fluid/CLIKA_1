// 펌웨어 JSON 줄을 팀장 서버의 입력 처리(squad-link/core/state.mjs의 ingest)에 넣고 결과를 JSON 한 줄씩 낸다.
// 사용: node lead_ingest_check.mjs <squad-link 폴더> <ndjson 파일>
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const [leadRoot, linesPath] = process.argv.slice(2);
const root = resolve(leadRoot);
const {makeState} = await import(pathToFileURL(`${root}/core/state.mjs`).href);
const {config} = await import(pathToFileURL(`${root}/core/config.mjs`).href);
const lines = readFileSync(linesPath, 'utf8').split('\n').filter(l => l.trim()).map(l => JSON.parse(l));
for (const mode of ['device', 'simulation']) {
  const cfg = structuredClone(config); cfg.input.mode = mode;
  const st = makeState({config: cfg});
  for (const p of lines) {
    let accepted = false, error = null;
    try { accepted = st.ingest(p).accepted === true; } catch (e) { error = e.message; }
    console.log(JSON.stringify({mode, packet_type: p.packet_type, source: p.source, seq: p.seq, accepted, error}));
  }
}
