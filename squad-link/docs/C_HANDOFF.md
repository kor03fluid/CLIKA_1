# C 인수인계 — PC 데이터 처리

## 책임 경계
사용자·Codex: PC 관제, 공통 입력 검증, 사건 관리·저장, USB 전달 프로그램.
C: 환경 노드 및 예비 노드 펌웨어·센서 연결, 고정 앵커 스캔과 관측 보고, 보드 현장 검증.
B: 무선 원본 패킷과 게이트웨이 USB 출력. 공통 MD와 다르면 임의 변경하지 말고 합의 후 수정.

## 완료한 것
- 분대 8명, 두 장치 배정, 미배정 6명, 노트북·휴대폰 동기화: 사용자 현장 확인.
- 반복 SOS 병합·확인·일괄 종료·완료 탭: 사용자 현장 확인.
- 환경·GPS 검증, 실패 상태·과거 좌표 구분: 가상 입력 검사 및 사용자 확인.
- 사건 확인·종료 상태 저장과 재시작 복원: 사용자 현장 확인.
- USB COM 입력 프로그램: 가상 바이트 입력→HTTP→관제까지 검사. 실제 COM 연결은 미확인.
- 처리 로그: 정상·중복·거부·순번 공백·재부팅·사건 조작·두절·복구. 자동 검사 완료, 사용자 현장 확인 대기.

## 아직 남은 것
- 환경/예비 노드 펌웨어, 실제 DHT11·ADC·추가 센서 측정.
- anchor_observation 수신 및 구역 추정 (현재 API는 해당 유형을 거부).
- 보드 간 BLE 송수신과 실제 게이트웨이 COM→서버 통합.
- 환경 온도 기준 경보 자동 생성. heat_exposure 사건 입력은 받을 수 있으나 온도로 자동 생성하지 않음.
- 전력·송신량·동시 센싱/스캔/보고 실측.
- 서버 다운 중 입력 패킷 재전송 큐, 로그 회전, 실서비스 인증.

## 실행·설정
`node server.mjs`, 기본 http://localhost:8080. 다른 기기는 같은 네트워크에서 노트북 IP:8080.
중앙 설정은 config/system.json. 변경 후 서버 재시작·화면 새로고침.
- input.mode: simulation/device. 보드가 만든 가상값은 simulation.
- input.driver: simulator/serial. serial이면 자동 가상 노드는 꺼짐.
- serial.port, baud_rate: 실제 COM과 Serial.begin에 맞추기.
- storage: 기록 위치와 저장 여부.
USB 설치·실행은 USB_SETUP.md 참조.

## 입력 인터페이스
PC 내부 수신 경계: POST /api/ingest, JSON 객체 1개, Content-Type application/json.
USB: UTF-8 NDJSON. 브리지가 한 줄을 한 HTTP 요청으로 전달. Arduino 시리얼 모니터와 동시 점유 금지.
GET /api/state 상태, GET /api/stream SSE state, GET /api/config 공개 화면 설정.
POST /api/events/{event_id}/ack 또는 resolve.
accepted:false는 중복·오래된 순번 등 의도적 미반영이며 HTTP 200. 형식 오류는 HTTP 400과 error.
현재 지원: soldier_status, event, environment, gps. 전체 필드는 공통 규격 MD.
중복 키는 source+node_id+boot_id+seq. 순번은 노드의 모든 패킷 유형에 공통. 원본·중계는 같은 키 유지.

## 파일과 기록
- core/state.mjs: 상태·사건·패킷 순서
- core/telemetry.mjs: 환경·GPS 검증/보관
- core/event-store.mjs: 사건 복원
- core/audit-log.mjs: 처리 로그
- communication/server.mjs: 입력 API/SSE
- communication/serial_bridge.py: COM→HTTP
- data/events.json: 현재 사건 이력·처리 상태
- data/telemetry.ndjson: 한 줄당 JSON 처리 로그. source로 가상/실제 구분.

로그의 sequence_gap_observed는 관측 순번 공백이다. 관측 범위·전송 경로·순서 역전 때문일 수도 있어 무선 손실 확정이 아니다. 늦게 온 패킷의 상태 덮어쓰기는 거부하되 신규 사건은 받을 수 있다. 서버 재시작 후 이전 프로세스의 순번 추적은 재개하지 않는다. 첫 패킷 이전 손실은 추정하지 않는다.
센서 값은 accepted 로그에 포함되지만 전체 원시 USB 바이트·잘못된 JSON 줄은 브리지 콘솔에만 기록한다. HTTP가 끊기면 패킷은 버리고 다음 패킷을 기다린다.
'시연 초기화 · 사건 삭제'는 사건 저장을 비우지만 감사 로그는 유지한다. 인수인계 시 사용자가 바꾼 설정과 data 폴더를 보존한다.

## 현장 완료 체크
1. A/B JSON을 USB로 받아 accepted 표시와 화면 갱신 확인.
2. 같은 패킷 반복 시 packet_ignored/duplicate 로그 확인.
3. USB 송신 중단 후 link_lost, 재접속 후 link_restored 확인.
4. SOS 확인·종료 후 서버 재시작, 사건 유지 확인.
5. 환경 실제 값과 가상 source를 구분하고 휴대폰에서 같은 사건 확인.
