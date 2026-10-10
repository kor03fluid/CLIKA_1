# Arduino Nano ESP32에 환경 모듈 펌웨어 올리기 (Windows, Arduino IDE 2)

대상 펌웨어: `firmware/env_module/` (기획서 5장 환경 모듈). 같은 소스가 ESP32 WROOM과 Arduino Nano ESP32에서 빌드된다.
빌드는 확인했다(arduino-esp32 3.3.12 `esp32:esp32:nano_nora`, Arduino ESP32 Boards 2.0.18 `arduino:esp32:nano_nora`, 둘 다 경고 없음). **Nano ESP32 실물 동작은 아직 확인하지 않았다.**
아래 순서대로 해 보고, 9절의 결과를 알려 주면 된다.

## 1. 준비물

| 준비물 | 비고 |
|---|---|
| Arduino Nano ESP32 | ESP32-S3 칩, 3.3V 로직 |
| USB-C 케이블 | **데이터 케이블**이어야 한다. 충전 전용 케이블이면 포트가 안 잡힌다 |
| Arduino IDE 2 | https://www.arduino.cc/en/software |
| 저장소 | GitHub `kor03fluid/CLIKA_1` → Code → Download ZIP(main) |
| 센서 | **없어도 된다.** 기본값이 가상 데이터라 보드만으로 시험된다 |

## 2. 한 번만 준비

### 2-1. 보드 패키지

1. Arduino IDE → **파일 → 기본 설정**.
2. "추가 보드 관리자 URL"에 다음 주소를 넣고 확인을 누른다.
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
3. 왼쪽 **보드 매니저** 아이콘을 누르고 `esp32`를 검색한다.
4. **esp32 by Espressif Systems**에서 3.x(3.3.x 권장)를 설치한다. 몇 분 걸린다.
   - **Arduino ESP32 Boards**(by Arduino, 2.0.18)로도 빌드를 확인했다. 이미 이것을 설치했다면 그대로 써도 된다(보드: Arduino ESP32 Boards → Arduino Nano ESP32).

### 2-2. 라이브러리

**설치할 것이 없다.** DHT11 읽기 코드는 펌웨어 폴더 안(`dht_reader.*`, Adafruit DHT 라이브러리 MIT)에 들어 있고, 조도는 `analogRead`로 읽는다.
이미 `DHT-sensor-library` 등을 설치했어도 상관없다(펌웨어는 폴더 안의 것을 쓴다).

## 3. 펌웨어 열기와 보드 설정

1. **파일 → 열기** → `CLIKA_1-main\firmware\env_module\env_module.ino`
   (탭이 여러 개 열리면 정상이다. `.cpp`·`.h` 파일이 같은 스케치다.)
2. 보드를 USB로 연결한다.
3. **도구 → 보드 → esp32 → Arduino Nano ESP32**를 고른다(목록이 길다. 위쪽 검색 상자에 `nano esp32`를 쳐도 된다).
4. **도구 → 포트**에서 `COMx (Arduino Nano ESP32)`를 고른다.
   - 포트가 안 보이면 7절을 본다.
   - COM 번호는 Windows **장치 관리자 → 포트(COM & LPT)**에서도 보인다.
5. 도구 메뉴의 나머지(Pin Numbering, USB Mode, Partition Scheme)는 **기본값 그대로** 둔다.
   - 펌웨어는 보드에 인쇄된 이름(D2, A0 …)을 쓰므로 Pin Numbering을 어느 쪽으로 해도 맞다.

## 4. 업로드

1. 왼쪽 위 **→(업로드)** 버튼을 누른다.
2. 아래 출력 창에 "컴파일 중"이 나온다. 처음에는 1~3분 걸린다.
3. 끝나면 `Sketch uses … bytes (21%) …`가 나오고 업로드가 시작된다(DFU 방식). 진행 표시가 100%까지 가면 끝이다.
4. 업로드가 끝나면 보드가 다시 시작한다. 이때 USB가 잠깐 끊겼다 다시 잡히므로 **COM 번호가 바뀔 수 있다.** 도구 → 포트를 다시 확인한다.

## 5. 동작 확인 (시리얼 모니터)

1. **도구 → 시리얼 모니터**를 연다. 오른쪽 아래를 **115200 baud**, 줄 끝 **Newline**으로 맞춘다.
2. 처음에는 **진단 줄이 꺼져 있어서** 데이터 줄만 나온다(규격 2장). 약 3초 뒤 아래 같은 줄이 30초쯤마다 나온다.
   감지가 있을 때는 바로 나온다.

```
{"schema_version":"1.0","packet_type":"environment","node_id":"env_01","boot_id":"boot_xxxx","seq":1,"source":"simulation",...,"payload":{"air_temperature_c":24.0,"humidity_pct":50,"light_raw":1831,...}}
```

3. 입력 칸에 `diag on`을 치고 Enter → `# {"type":"ok","node_id":"env_01","boot_id":"boot_xxxx","cmd":"diag on"}`이 나온다(보드에 저장).
4. `reboot`을 보낸다. 보드가 재시작하며 포트가 잠깐 끊기므로 시리얼 모니터가 멈추면 닫았다 다시 연다.
5. 재시작 직후의 부팅 줄은 모니터를 다시 여는 사이에 지나갈 수 있다. 다음 명령으로 상태를 확인한다.

| 보낼 명령 | 나와야 하는 것 |
|---|---|
| `config` | `# {"type":"config",...,"running_node_id":"env_01","sensors":"virtual",...,"fw":"env_module/1.0.0"}` |
| `stats` | `# {"type":"stats",...,"vsensor":true,...,"tx":{"packets":N,...}}` (N이 시간이 지나며 늘어남) |
| `scenario` | `# {"type":"scenario","scenario":true,"phase":"normal"}`처럼 지금 가상 시나리오 구간 |
| `vdetect sound` | 곧바로 `"sound_detected":true`인 environment 줄 |
| `vtemp 38` | `packet_type":"event"`, `"event_type":"heat_exposure"` 줄. 끝내려면 `vtemp off` |
| `check` | 2초 뒤 `# {"type":"check",...,"warnings":[...]}`. 센서가 없으면 A0 핀이 떠 있어서 조도 핀 경고가 나올 수 있다(정상) |
| `help` | 명령 목록 |

부팅 줄을 꼭 보고 싶으면 시리얼 모니터를 열어 둔 채 보드의 **RST 버튼**을 한 번 누른다. 포트가 다시 잡힌 뒤 열린 모니터에 `# {"type":"boot",...,"board":"nano_esp32",...}`가 나온다. 보드 USB 특성상 첫 줄은 놓칠 수 있다.

가상 시나리오(10분 반복): 30초 큰 소리 → 60초 설치물 충격 → 90~100초 리드 열림 → 150~160초 불꽃 반응 → 200~420초 공기 온도 상승·열 노출 사건·해제 → 480~500초 DHT11 실패(null) → 520~560초 어두워짐.

## 6. 보드 LED

| 상태 | 뜻 |
|---|---|
| 노란 LED(D13)가 짧게(0.3초) 켜졌다 꺼짐 | BLE 광고 창 하나가 나감(패킷 송신) |
| 감지 때 세 번 연달아 깜빡임 | 사건·감지 패킷은 같은 패킷을 세 번 광고 |

## 7. 막힐 때

| 증상 | 해결 |
|---|---|
| 도구 → 포트에 아무것도 없음 | 데이터 케이블인지 확인(다른 케이블로), 다른 USB 포트에 꽂기, 장치 관리자에 "알 수 없는 장치"가 있는지 확인 |
| 업로드 중 `No DFU capable USB device available` 등 DFU 오류 | 보드의 **RST 버튼을 빠르게 두 번** 눌러 부트로더 모드로 넣는다(RGB LED가 초록으로 천천히 밝아졌다 어두워짐) → 그 상태에서 바로 업로드. DFU는 COM 번호가 아니라 USB 장치로 찾으므로 포트 이름이 바뀌어도 된다 |
| 그래도 DFU 장치를 못 찾음(Windows 드라이버) | 장치 관리자에서 노란 느낌표 장치(`Nano ESP32`·`DFU` 등)가 있으면 드라이버가 없는 것이다. 보드 매니저에서 **Arduino ESP32 Boards**를 제거 후 다시 설치하고, 설치 중 뜨는 드라이버 설치 창(관리자 권한)에서 **설치/예**를 누른다 |
| 장치 관리자에 `USB JTAG/serial debug unit` 또는 `CH340`·`CP210x`로 보임 | Arduino 부트로더가 없는 보드(호환 보드 등)다. 아래 "복구 업로드"로 올린다 |
| 복구 업로드(위 방법이 다 안 될 때) | ① 보드의 **B1 핀을 GND에 점퍼선으로 연결한 채 RST를 한 번** 누른다(칩 내장 부트로더) ② 점퍼를 뺀다 ③ 도구 → 포트에서 새로 잡힌 COM을 고른다 ④ **도구 → 프로그래머 → Esptool** ⑤ **스케치 → 프로그래머를 이용해 업로드** ⑥ 끝나면 RST를 한 번 누른다. 그 뒤로는 일반 업로드(DFU)가 다시 될 수 있다(안 되면 같은 방법으로 계속 올리면 된다) |
| `DHT.h`·`Adafruit_Sensor.h`·`RBD_LightSensor.h: No such file` | 예전 펌웨어다. main을 다시 받는다(커밋 `36171e5` 이후는 라이브러리가 필요 없다) |
| `ADV_TYPE_NONCONN_IND` 또는 `setTxBufferSize` 오류 | 예전 펌웨어다. main을 다시 받는다(커밋 `0632f1f` 이후) |
| 시리얼 모니터에 아무것도 안 나옴 | 115200 확인. 업로드 직후·`reboot` 뒤에는 모니터를 닫았다 다시 연다. 3초 넘게 기다린다(첫 보고는 약 3초 뒤) |
| 글자가 깨져 보임 | baud 115200 확인 |
| `could not open port` / 액세스 거부 | 같은 COM을 연 프로그램(시리얼 모니터, C 시험 서버, 팀장 브리지)을 하나만 남기고 닫는다 |

## 8. PC 서버와 연결 (시리얼 모니터는 닫고)

| 하고 싶은 것 | VS Code 실행 목록(F5) | 볼 곳 |
|---|---|---|
| C 시험 서버에서만 보기 | **2. C 시험 서버: 환경 노드 USB 연결** → COM 입력 | `http://localhost:8090` |
| 팀장 서버까지 넘기기 | **11. 팀장 관제 서버 + 환경 보드 전달** → COM 입력 | C 화면 위쪽 "팀장 전달 N", 팀장 화면 `http://localhost:8080` "환경 · 위치"의 env_01 |
| 팀장 노트북의 서버로 | 명령 `python pc/server.py --serial COMx --forward-lead http://<팀장 IP>:8080/api/ingest` | 같은 Wi-Fi, 팀장 노트북 8080 방화벽 허용 |

C 시험 서버 화면의 **장치 명령** 칸에서도 `stats`, `check`, `vdetect sound` 같은 명령을 보낼 수 있다.

## 9. 센서를 연결할 때 (실물 센서가 오면)

| 센서 | 핀(보드 인쇄 이름) | 전원 |
|---|---|---|
| DHT11 DATA | **D2** | 3V3, GND |
| 조도 분압 출력 | **A0** | 3V3, GND |
| 소리 DO | **D3** | 3V3, GND |
| 불꽃 DO | **D4** | 3V3, GND |
| 충격 DO | **D5** | 3V3, GND |
| 리드스위치 | **D6** ↔ GND | 없음(내부 풀업) |

- 모듈 VCC는 **3V3** 핀에 연결한다. **VBUS**는 USB 5V이므로 모듈 출력이 5V가 되게 연결하지 않는다.
- GPIO에 꽂기 전에 멀티미터로 모듈 출력 전압을 잰다(3.3V 이하). 기록표는 `docs/c_sec5_env_module.md` 2절에 있다.
- 연결한 뒤 시리얼에서 다음을 보낸다.
  1. `sensors real`: 실제 센서로 전환한다(저장).
  2. `use sound on`, `use flame on`, `use shock on`, `use reed on`: 확인한 추가 센서만 켠다(저장).
  3. `check`: 경고가 없으면 된다.
- 다시 가상으로 돌아가려면 `sensors virtual`을 보낸다.

## 10. 알려 줄 것

| 항목 | 예 |
|---|---|
| COM 번호(업로드 뒤 최종) | `COM7` |
| `config` 응답 한 줄 | `# {"type":"config",...}` |
| environment 줄 한 줄 | `{"schema_version":"1.0","packet_type":"environment",...}` |
| (보였다면) 부팅 줄 | `# {"type":"boot",...,"board":"nano_esp32",...}` |
| 막힌 곳 | 오류 메시지 전체 복사 |
