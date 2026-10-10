# SQUAD LINK

## 실행
VS Code에서 squad-link 폴더를 열고 터미널에서 `node server.mjs`를 실행합니다. 기본 주소는 http://localhost:8080 입니다. 추가 패키지 설치는 필요 없습니다.

## 설정 변경
`config/system.json`에서 값을 바꿉니다. 서버 Ctrl+C → `node server.mjs` → 크롬 Ctrl+Shift+R 순서로 반영합니다.

- squad.soldier_count: 명단 인원수 (기본 8)
- squad.node_ids: 명단 앞에서부터 배정할 장치 ID (기본 2개)
- simulation.heart_rate_bpm: 장치별 가상 심박값. node_ids 개수와 일치해야 합니다.
- simulation.heartbeat_interval_ms: 가상 보고 주기 (기본 5000ms)
- communication: 두절 판정의 최솟값·주기 배수·여유 시간
- server.port: 접속 포트
- ui.timezone: 화면 시간대

## 폴더 구조
[아키텍처 설명](docs/ARCHITECTURE.md)을 참고하세요. 공통 패킷 규격은 docs 폴더에 있습니다.

## 사건 처리
같은 병사의 미종료 SOS는 하나로 묶고 요청 횟수를 표시합니다. 확인은 종료가 아닙니다. SOS 조치 종료는 해당 병사의 미종료 SOS를 일괄 완료합니다. 종료 사건은 처리 완료 탭으로 이동합니다. 다른 유형 사건은 별도입니다.

## C 팀원 연동
GET /api/state, GET /api/stream(SSE), GET /api/config, POST /api/ingest(JSON), POST /api/events/{event_id}/ack 또는 resolve.
개발 서버는 simulation 소스의 soldier_status/event만 받습니다. 실제 장치 입력은 다음 단계에서 연동합니다.

## 검증
`node --test tests/*.test.mjs`로 실행합니다. 브라우저 실제 클릭 및 휴대폰 접속·BLE 연동은 별도 현장 확인이 필요합니다. 기록은 메모리에 저장되어 서버 종료 시 사라집니다.

## 프로토콜 확장 검사
서버 실행 후 새 터미널에서 `node tools/protocol-check.mjs`를 실행합니다. 하단 환경·GPS 카드에서 가상 온습도·조도와 GPS 미수신/과거 좌표를 확인합니다. 이 검사는 halo_01의 부팅 ID를 시험용으로 바꾸므로 기존 가상 스트림과 함께 사용할 때 검사가 끝난 후 '정상 상태로 초기화'를 누릅니다.

`input.mode`는 simulation 또는 device입니다. device에서는 자동 가상 송신과 시연 버튼이 꺼지고 실제 source만 받습니다. 보드가 센서 대신 만든 값은 simulation으로 보내야 합니다. NDJSON 표준입력 전달 도구는 `communication/ndjson-input.mjs`입니다. 실제 COM 포트, BLE 펌웨어 및 보드 송수신은 아직 연결·검증 전입니다.

환경·GPS·상태·사건의 노드 순번은 공통 스트림으로 검사합니다. GPS 미수신 시 과거 유효 좌표를 수신 시각과 별도로 표시합니다. anchor_observation 및 구역 추정, 디스크 기록 복원은 다음 구현입니다.

## 사건 기록 저장
설정 storage.enabled=true이면 프로젝트의 data/events.json에 사건 및 처리 상태를 저장합니다. 서버 재시작 시 사건을 복원하고 측정값·연결 상태는 새 수신을 기다립니다. 가상 모드에서는 자동 가상 송신이 즉시 시작됩니다. 저장 경로는 storage.event_file에서 지정합니다. '정상 상태로 초기화'는 사건 기록도 비우는 시연 초기화입니다. 유지할 기록이 있으면 누르지 마세요. 손상된 저장 파일은 조용히 덮어쓰지 않고 서버 시작을 실패시킵니다. 환경·GPS 원시 기록과 모든 패킷의 장기 로그는 아직 저장하지 않습니다.

## USB 연결
[USB 연결 가이드](docs/USB_SETUP.md)를 따릅니다. communication/serial_bridge.py가 실제 COM 입력을 HTTP로 전달합니다. input.driver=serial이면 자동 가상 송신이 꺼져 보드 입력만 표시합니다. source 모드와 입력 경로는 서로 독립적입니다.

## 처리 로그와 인수인계
`data/telemetry.ndjson`에 정상 수신·중복·거부·순번 공백·재부팅·사건 조작·두절·복구를 기록합니다. 순번 공백은 무선 손실 확정이 아닙니다. 시연 초기화는 사건을 삭제하지만 처리 로그는 보존합니다. C 인수인계는 docs/C_HANDOFF.md를 참조하세요. 보드가 오기 전 소프트웨어 경계까지만 완료했으며 실제 USB·BLE 연결은 별도 검증합니다.
