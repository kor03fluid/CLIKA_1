// 실행 진입점: 설정과 실제 기능은 하위 모듈에 있습니다.
import {createApp} from './communication/server.mjs';
import {config} from './core/config.mjs';
const app=createApp();
app.server.listen(config.server.port,config.server.host,()=>console.log(`${config.app.name}: http://localhost:${config.server.port} (가상 데이터)`));
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>app.stop().then(()=>process.exit()));
