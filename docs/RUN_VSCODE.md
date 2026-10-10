# VS Code에서 실행하기 (Windows 기준)

저장소에 VS Code 실행 설정(`.vscode/launch.json`, `.vscode/tasks.json`)이 들어 있어서, 폴더를 열고 목록에서 고른 뒤
**F5**로 실행한다. 팀장 공식 관제 서버도 저장소의 `squad-link/`에 들어 있어(팀장 원본 그대로) 같은 창에서 실행한다.

## 1. 한 번만 준비

| 설치 | 용도 | 확인 |
|---|---|---|
| [VS Code](https://code.visualstudio.com/) | 편집·실행 | — |
| [Python 3.9 이상](https://www.python.org/downloads/) — 설치 첫 화면에서 **"Add python.exe to PATH"** 체크 | C 시험 서버·도구 | 터미널에서 `python --version` |
| VS Code 확장 **Python**(Microsoft) | F5 실행·디버그 | 폴더를 열면 "권장 확장 설치" 알림이 뜬다 |
| [Node.js LTS(22 이상)](https://nodejs.org/) | 팀장 관제 서버(`squad-link`) | `node --version` |
| pyserial | USB(COM) 연결할 때만 | 아래 2-2 |
| Arduino IDE 2 또는 arduino-cli | 펌웨어 업로드할 때만 | 아래 4 |

저장소 받기: GitHub `kor03fluid/CLIKA_1` → Code → Download ZIP(압축 풀기) 또는 `git clone`.
VS Code에서 **파일 → 폴더 열기 → `CLIKA_1`**. 처음 열 때 "이 폴더의 작성자를 신뢰하십니까?"는 신뢰를 누른다.
Python 인터프리터를 묻거나 실행이 안 되면 **Ctrl+Shift+P → "Python: Select Interpreter"**에서 설치한 Python을 고른다.

## 2. 실행 (실행 및 디버그: Ctrl+Shift+D)

왼쪽 **실행 및 디버그** 화면 위쪽 목록에서 하나를 고르고 **F5**. 끌 때는 **Shift+F5**(또는 터미널에서 Ctrl+C).

| 목록 이름 | 하는 일 | 열어 볼 곳 |
|---|---|---|
| 1. C 시험 서버: 가상 시연 (demo, 보드 없이) | 가상 병사 2명·환경 노드·앵커로 규격 11장 시연 흐름 | 브라우저 `http://localhost:8090` |
| 2. C 시험 서버: 환경 노드 USB 연결 (COM 입력) | 환경 노드 USB를 읽어 저장·화면 표시. 실행할 때 COM 포트를 묻는다 | `http://localhost:8090` |
| 3. C 시험 서버: 환경 노드 USB + 가상 병사 2명 | 앵커 시험용. 환경 노드 + 가상 병사 | `http://localhost:8090` |
| 4. 팀장 서버로 펌웨어 JSON 예시 보내기 | 환경·열 노출 사건·앵커 예시 줄을 팀장 서버 `/api/ingest`로 보냄(아래 3) | `http://localhost:8080` |
| 5. 로그 요약 (report.py) | 수신·누락·송신량·시험 조건·오류 표. `logs/`를 주면 가장 최근 실행을 요약 | 터미널 출력 |
| 6. 단위 테스트 | 서버·도구 시험(C++ 컴파일러가 없으면 펌웨어 시험은 건너뜀) | 터미널 출력 |
| **7. 팀장 관제 서버 (공식, squad-link, 8080)** | 팀장의 공식 관제 화면(가상 병사 2명, 시연 버튼) | `http://localhost:8080` |
| 8. 팀장 USB 브리지 | 보드 USB 줄을 팀장 서버로 전달(아래 3-2, 설정 먼저) | 팀장 화면 |
| 9. 팀장 관제 서버 + C 시험 서버 같이 켜기 | 7번과 1번을 한 번에(멈추면 둘 다 꺼짐) | 8080·8090 |
| **10. 환경 보드 USB → C 검증 → 팀장 서버 전달** | 환경 모듈 보드(`firmware/env_module`)의 USB를 C 시험 서버가 받아 검사·중복 제거하고, 통과한 가상 데이터만 팀장 서버로 넘김(아래 3-3) | 8090 · 8080 |
| **11. 팀장 관제 서버 + 환경 보드 전달 같이 켜기** | 7번과 10번을 한 번에 | 8080 · 8090 |

### 2-1. 보드 없이 바로 해 보기

1. 목록에서 **1. C 시험 서버: 가상 시연** → F5.
2. 터미널에 `[squadlink] C 시험 서버 실행 중` 아래 주소가 뜨면 브라우저에서 `http://localhost:8090`(Ctrl+클릭으로 열림).
   `0.0.0.0`은 "모든 네트워크에서 받기"라는 서버 설정이라 브라우저 주소로 쓰면 `ERR_ADDRESS_INVALID`가 난다.
3. 약 15초 뒤 병사 01 SOS, 35초 뒤 병사 02 송신 중단(약 62초에 통신 두절), 85초에 복구.
4. 첫 화면(현황)을 옆으로 밀면 병사 한 명씩 상세 화면이 나온다(심박·움직임·수신 경과·두절 판정까지 남은 시간, 위치,
   그 병사의 사건, 그 병사를 본 앵커 RSSI, 노드 진단). 위쪽 탭·‹ › 버튼·키보드 ← →로도 넘기고, 현황의 분대원 카드를 누르면
   그 병사로 바로 간다. 주소 끝의 `#soldier_01`로 그 화면을 바로 열 수 있다.
5. 휴대폰: 같은 Wi-Fi에서 터미널에 "(같은 Wi-Fi의 휴대폰)"으로 나온 주소(`http://<노트북 IP>:8090`). 안 나오면 `ipconfig`의
   IPv4 주소. Windows 방화벽 알림이 뜨면 허용.

### 2-2. 환경 노드(ESP32) USB로 연결

1. **Ctrl+Shift+P → "Tasks: Run Task" → "준비: pyserial 설치"** (한 번만).
2. 같은 방법으로 **"USB 포트 목록 보기"** → ESP32의 COM 번호 확인(또는 장치 관리자 → 포트).
3. Arduino 시리얼 모니터를 닫는다(같은 COM은 한 프로그램만 연다).
4. 목록에서 **2. C 시험 서버: 환경 노드 USB 연결** → F5 → COM 포트 입력(예: `COM5`).
5. 화면의 **장치 명령** 칸에서 `stats`, 센서가 없으면 `vsensor on`, `vdetect sound`, `vtemp 38` 등을 보낸다.
6. 끝나면 **5. 로그 요약** → `logs/` 그대로 Enter → 가장 최근 실행이 요약된다.

## 3. 팀장 관제 서버 (`squad-link/`)

`squad-link/`는 팀장이 준 `SQUAD_LINK_step1.zip`을 **그대로** 넣은 것이다(서버 수정은 팀장 담당이라 C는 고치지 않는다).
팀장이 새 ZIP을 주면 `squad-link/` 폴더를 통째로 바꾼다. 설명서는 `squad-link/README.md`, `squad-link/docs/`.

### 3-1. 가상으로 보기 + 우리 펌웨어 JSON 보내기

1. **7. 팀장 관제 서버** → F5 → 터미널에 `SQUAD LINK: http://localhost:8080 (가상 데이터)` → 브라우저 `http://localhost:8080`.
2. 그대로 둔 채 **4. 팀장 서버로 펌웨어 JSON 예시 보내기** → F5 → `samples_simulation.ndjson`.
   - 팀장 서버 기본 `input.mode`는 `simulation`이라 가상판을 고른다(실측 예시는 `device` 모드에서 받음).
   - 환경 패킷은 "환경 · 위치"에 표시된다. 열 노출 사건·앵커 관측은 팀장 서버 확장 전이라 거부(`REJECT 400`)가 정상이다.
3. 끌 때는 디버그 막대의 빨간 네모(Shift+F5). C 시험 서버까지 함께 보려면 **9번**.

### 3-2. 환경 노드 보드를 팀장 서버에 바로 연결

팀장 문서(`squad-link/docs/USB_SETUP.md`)대로 `squad-link/config/system.json`을 바꾼다.

| 항목 | 값 |
|---|---|
| `input.driver` | `"serial"` (자동 가상 병사가 꺼진다) |
| `serial.port` | 환경 노드 COM (예: `"COM5"`) |
| `input.mode` | 센서 실측이면 `"device"`, `vsensor`·`vtemp` 시험이면 `"simulation"` (서버는 한 출처만 받는다) |
| `environment.node_ids` | 예비 보드를 쓰면 `"env_02"` 추가 |

그다음 **7. 팀장 관제 서버** F5 → **8. 팀장 USB 브리지** F5. 브리지 터미널에 받은 줄마다 `accepted:true`가 나오고,
`# `로 시작하는 진단 줄은 `SKIP: invalid NDJSON`으로 넘어간다(정상). 같은 COM은 한 프로그램만 열 수 있으니 C 시험 서버(2·3번)와
Arduino 시리얼 모니터는 끈다. 시험이 끝나면 `system.json`을 원래대로(`simulator`, `simulation`) 돌린다.

### 3-3. 환경 모듈 보드(가상 데이터) → C 검증 → 팀장 서버 (역할 분담대로)

기획서 10장의 역할대로 C가 USB 입력·검증·중복 제거를 맡고, 팀장 서버는 받기만 한다. 팀장 서버 설정(`system.json`)은 바꾸지 않는다(기본 `simulation`).

1. 보드에 `firmware/env_module`을 올린다(아래 4, 또는 작업 "환경 모듈 펌웨어 업로드"). 처음에는 **가상 데이터**(6개 센서 값을 보드가 만듦, `source: "simulation"`)다.
2. **11. 팀장 관제 서버 + 환경 보드 전달** → F5 → COM 포트 입력.
3. C 화면(`http://localhost:8090`) 위쪽에 "팀장 전달 N · 거절 N · 실패 N", 팀장 화면(`http://localhost:8080`) "환경 · 위치"에 `env_01`이 보인다.
4. C 화면 장치 명령에서 `diag on`을 한 번 보내면(보드에 저장) 시험 조건·`stats`가 C 로그에 남는다. 진단 줄은 팀장 서버로 넘어가지 않는다.

넘기는 것은 C 검사를 통과한 **새 가상 데이터**뿐이다. 중복·지연·규격 위반·실측은 넘기지 않는다(`--forward-source device`를 주면 실측도 넘김).
열 노출 사건·앵커 관측은 팀장 서버가 아직 받지 않아 "거절"로 세는 것이 정상이다(팀장 확장 예정).
이 방법은 C 시험 서버가 COM을 열므로 팀장 USB 브리지(8번)는 켜지 않는다.

두 서버는 포트가 달라(C 시험 8090, 팀장 8080) 한 노트북에서 같이 켤 수 있다.
팀장 서버 자체 시험은 **Tasks: Run Task → "팀장 서버 테스트 (node --test)"**.

## 4. 펌웨어 업로드

**Arduino IDE 2 (권장)**

1. 보드 매니저에서 **esp32 by Espressif Systems** 3.x 설치. 목록에 없으면 **파일 → 기본 설정 → 추가 보드 관리자 URL**에
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`을 넣고 다시 찾는다.
2. 저장소의 `DHT-sensor-library`, `Adafruit_Sensor`, `RBD_LightSensor` 폴더를 `문서\Arduino\libraries`에 복사.
3. `firmware\env_module\env_module.ino`(5장 환경 모듈, 권장) 또는 `firmware\env_node\env_node.ino` 열기 → 보드 **ESP32 Dev Module** → 포트 COMx → 업로드.
4. 시리얼 모니터 115200bps, 줄 끝 **Newline** → `stats`, 센서 없으면 `vsensor on`.
5. 예비 보드: `env_module`은 같은 펌웨어를 올리고 시리얼로 `id env_02`(소스 수정 없음). `env_node`는 `config.h`의 `NODE_ID`를 `0x32`로 바꿔 업로드.

**VS Code에서 arduino-cli로 (선택)**

[arduino-cli](https://arduino.github.io/arduino-cli/)를 설치하고 PATH에 넣은 뒤 한 번만:

```
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

그다음 **Ctrl+Shift+P → "Tasks: Run Task"** 에서 **펌웨어 빌드 / 펌웨어 업로드 / 시리얼 모니터 (115200)** 를 고른다(COM 포트를 묻는다).
업로드·모니터가 COM을 쓰는 동안에는 C 시험 서버를 끈다.

## 5. 자주 막히는 곳

| 증상 | 해결 |
|---|---|
| `python`을 찾을 수 없음 | Python 재설치 때 "Add python.exe to PATH" 체크, 또는 Ctrl+Shift+P → Python: Select Interpreter |
| `could not open port COM5` / 액세스 거부 | 시리얼 모니터·업로드·팀장 브리지 등 같은 COM을 연 프로그램을 닫는다. 포트 번호 재확인 |
| `pyserial` 없음 | 작업 "준비: pyserial 설치" |
| 브라우저에 `ERR_ADDRESS_INVALID` (`http://0.0.0.0:8090`) | 주소를 `http://localhost:8090`으로 바꾼다 |
| 8090 포트 사용 중 | 이미 켜진 C 시험 서버를 끄거나 `pc/server.py --port 8091` |
| 휴대폰에서 안 열림 | 같은 Wi-Fi인지, 노트북 IP가 맞는지, Windows 방화벽에서 Python 허용 |
| 화면의 확인·종료 버튼이 403 | `localhost`·IP 주소로 열기(노트북 이름으로 열면 `--allow-host 그이름` 필요) |
| 펌웨어 업로드가 멈춤 | 업로드 중 ESP32의 BOOT 버튼을 누르고 있기, USB 케이블(데이터용) 확인 |

Visual Studio(2022, 보라색 아이콘)를 쓰려면 "Python 개발" 워크로드를 설치하고 **파일 → 열기 → 폴더**로 `CLIKA_1`을 연 뒤
`pc\server.py`를 시작 항목으로 정하고 인수에 `--virtual demo`를 넣으면 같다. 펌웨어는 Arduino IDE로 올린다.
