# SQUAD LINK 구조

| 위치 | 역할 |
|---|---|
| server.mjs | 서버 실행·종료 진입점 |
| config/system.json | 전체 운용 설정의 단일 원본 |
| core/config.mjs | 설정 읽기·검증, 공통 두절 계산 |
| core/state.mjs | 병사 상태, SOS 병합, 사건 처리, 두절 판단 |
| communication/server.mjs | HTTP API, SSE 동기화, 정적 화면 전달 |
| communication/simulator.mjs | 가상 장치 패킷 생성·시연 조작 |
| ui/index.html | 화면 구조 |
| ui/app.mjs | 서버 설정·상태 수신, 사건 탭, 화면 조작 |
| ui/style.css | 화면 스타일 |
| tests/ | 상태 및 관제 동기화 검사 |
| docs/ | 아키텍처와 공통 데이터 규격 |

설정 흐름: system.json → core/config.mjs → 상태 처리·가상 장치·서버. 화면은 /api/config에서 같은 원본의 공개 설정을 받습니다.

운용 설정은 system.json에서만 수정합니다. 수정 후 서버를 Ctrl+C로 종료하고 node server.mjs로 재실행합니다. 화면은 새로고침합니다. 실시간 파일 감시·자동 재시작은 아직 없습니다.

지역 변수, 실행 중 상태, 함수 인자는 해당 모듈에 둡니다. 설정 파일에는 조정 가능한 운용값만 넣습니다. 프로토콜의 event_state·packet_type 등 enum은 공통 규격에 따른 코드이며 임의 설정 변경 대상이 아닙니다. CSS 스타일은 ui/style.css에 둡니다.

실제 센서 연결 시 heartbeat_interval_ms는 하드웨어 패킷의 보고 주기로 판단합니다. 설정의 simulation.heartbeat_interval_ms는 가상 장치에만 적용하며 펌웨어를 자동 수정하지 않습니다.

환경·GPS 값 검증과 보관은 core/telemetry.mjs, NDJSON 입력 전달은 communication/ndjson-input.mjs, 실행 서버 대상 검사 도구는 tools/protocol-check.mjs에서 담당합니다.

## 관제 UI 구성
ui/views.mjs는 병사 행·상세·사건·환경 화면 생성, ui/app.mjs는 서버 수신·선택·조작, ui/style.css는 디자인을 맡습니다. 원형 프로필은 식별용 아이콘이며 실제 병사 사진이 아닙니다. 서버의 정적 파일 목록에 /views.mjs가 필요합니다. UI 갱신은 기존 API와 source 규격을 유지합니다.
