#pragma once
// 환경 모듈 펌웨어 설정 (기획서 5장 "환경 모듈과 예비 모듈").
// 데이터 형식: 공통 데이터 규격 v1 (docs/data_spec_v1.md), BLE 바이트 배치: 부록 A 초안 (docs/appendix_a_ble.md).
// 같은 펌웨어를 env_01과 예비 WROOM(env_02)에 올린다. 노드 ID는 빌드가 아니라 시리얼 "id env_02"로 정해 NVS에 남긴다.

#define FW_NAME    "env_module"
#define FW_VERSION "1.0.0"

#define DEFAULT_NODE_ID 0x31  // env_01. 부록 A: 0x31~0x3F = env_01~env_15, 예비 WROOM은 0x32(env_02)

// ----- 핀 (ESP32 DevKit 기준, 실물 확인 후 수정) -----
// 전원은 USB 5V. 모듈 VCC는 보드 3V3 핀에 연결하고, 5V 출력 신호를 GPIO·ADC에 직접 넣지 않는다.
// 만능기판은 배선·고정용이다. GPIO를 늘리는 칩(멀티플렉서·IO 확장)은 쓰지 않는다: 센서 6개 = GPIO 6개 직결.
#if defined(ARDUINO_NANO_ESP32)
// Arduino Nano ESP32 (ESP32-S3, u-blox NORA-W106). 보드에 인쇄된 이름(D2·A0 …)을 쓴다.
// 보드 메뉴 Pin Numbering이 기본("By Arduino pin")이든 "By GPIO number"든 이 이름이 맞는 GPIO로 바뀐다.
// 3.3V 로직이다. 모듈 VCC는 3V3 핀, 5V가 필요하면 VBUS(USB 5V)에서 받되 출력은 분압해 넣는다.
#define BOARD_NAME "nano_esp32"
#define PIN_LED    LED_BUILTIN  // D13(GPIO48) 노란 LED. 광고 창 동안 켜짐
#define PIN_DHT    D2   // GPIO5  DHT11 DATA (필수)
#define PIN_LIGHT  A0   // GPIO1  조도 분압 출력, ADC1 (필수)
#define PIN_SOUND  D3   // GPIO6  소리 센서 DO (추가)
#define PIN_FLAME  D4   // GPIO7  불꽃감지 센서 DO (추가)
#define PIN_SHOCK  D5   // GPIO8  충격 센서 DO (추가)
#define PIN_REED   D6   // GPIO9  리드스위치(핀–GND), 내부 풀업 (추가)
#else
// ESP32 WROOM DevKit
#define BOARD_NAME "esp32_wroom"
#define PIN_LED    2   // 보드 내장 LED. 광고 창 동안 켜짐
#define PIN_DHT    4   // DHT11 DATA (필수)
#define PIN_LIGHT  34  // 조도 분압 출력, ADC1 입력 전용 (필수)
#define PIN_SOUND  27  // 소리 센서 DO (추가)
#define PIN_FLAME  26  // 불꽃감지 센서 DO (추가)
#define PIN_SHOCK  25  // 충격 센서 DO (추가)
#define PIN_REED   33  // 리드스위치(핀–GND), 내부 풀업 (추가)
#endif

// 디지털 모듈의 반응 레벨(모듈마다 다르므로 실물로 확인)
#define SOUND_ACTIVE_LEVEL HIGH
#define FLAME_ACTIVE_LEVEL LOW
#define SHOCK_ACTIVE_LEVEL HIGH
#define REED_OPEN_LEVEL    HIGH  // 자석 떨어짐(열림) → 풀업으로 HIGH
#define REED_DEBOUNCE_MS   50

// ----- 데이터 출처 -----
// 가상(기본): 실물 센서를 확인하기 전에는 보드가 6개 센서 값을 가상으로 만들고 source "simulation"으로 보낸다
//   (기획서 10장·팀장 지시: 실물 없는 부분은 가상 데이터 시험으로 표시하고 실제 검증 완료로 표시하지 않는다).
// 실제: 센서를 연결·확인한 뒤 시리얼 "sensors real"(NVS에 남김). 그때는 확인한 추가 센서만 "use sound on" 등으로 켠다
//   (규격 1장·12장: 추가 환경센서는 검증 후 적용). 꺼진 센서는 JSON에서 필드와 sensor_status 키가 모두 빠진다.
#define DEFAULT_VIRTUAL  1
#define DEFAULT_USE_MASK 0x00  // 실제 센서 모드에서 켤 추가 센서(DET_SOUND | DET_FLAME | DET_SHOCK | DET_REED)

// ----- 환경 열 노출 주의 (공기 온도 기준. 개인 체온·과열 판정이 아니다) -----
#define HEAT_ON_C  35.0f
#define HEAT_OFF_C 34.0f  // 히스테리시스

// ----- 센싱 (센싱 태스크) -----
#define SENSE_PERIOD_MS    20    // 센싱 태스크 주기
#define SENSE_TASK_STACK   4096
#define SENSE_OVERRUN_MS   100   // 센싱 한 번이 이보다 길면 지연으로 센다(동시 운용 시험)
#define DHT_READ_MS        2000  // DHT11은 1초 이상 간격 필요
#define DHT_FAIL_LIMIT     3     // 이만큼 연달아 실패해야 측정 불가(null). 그 전까지는 직전 값
#define LIGHT_READ_MS      500
#define VTEMP_HUMIDITY_PCT 50.0f  // 가상 습도 기준(가상 센서 ±2%). vtemp 중 실측 습도가 없을 때도 이 값
#define VSENSOR_TEMP_C     24.0f  // 가상 센서 기준 공기 온도(±0.4°C). 시나리오에서 37°C까지 오른다
#define VSENSOR_LIGHT_RAW  1800   // 가상 센서 기준 조도 원시값(±150). 시나리오에서 약 200(어두움)

// ----- 보고 정책 -----
#define DEFAULT_ADAPTIVE      1      // 1 적응, 0 고정 5초. 시리얼 "mode fixed|adaptive"(NVS에 남김)
#define TX_FIXED_INTERVAL_MS  5000
#define ENV_HEARTBEAT_MS      30000  // 적응: 변화 없을 때 최대 간격 → 서버 두절 기준 92초
#define ENV_ALERT_INTERVAL_MS 10000  // 적응: 열 노출·불꽃 반응이 이어지는 동안
#define ENV_MIN_GAP_MS        3000   // 적응: 값 변화로 인한 송신 최소 간격
#define EVENT_MIN_GAP_MS      2000   // 감지 즉시 송신 최소 간격
#define EVENT_REPEATS         3      // 사건·감지 패킷 반복 광고 창 수(같은 seq)
#define DELTA_TEMP_C    1.0f
#define DELTA_HUM_PCT   5
#define DELTA_LIGHT_RAW 400          // 12bit 원시값 기준(약 10%)
#define LOOP_OVERRUN_MS 100          // 보고 루프 한 바퀴가 이보다 길면 지연으로 센다

// ----- BLE 송신 -----
#define BLE_TX_POWER       ESP_PWR_LVL_N0  // 0 dBm
#define TX_ADV_INTERVAL_MS 100
#define TX_WINDOW_MS       300  // 패킷 1회 = 광고 창 1개
#define TX_REPEAT_GAP_MS   500
#define TX_QUEUE_LEN       6
#define SERIAL_TX_BUFFER   4096  // USB 시리얼 송신 버퍼(바이트, WROOM의 UART). 앵커 보고 묶음이 루프를 막지 않게
#define SERIAL_TX_TIMEOUT_MS 50  // 보드 자체 USB(Nano ESP32의 TinyUSB CDC): PC가 포트를 열고 읽지 않을 때 쓰기 대기 한도

// ----- 고정 앵커 (병사 방송 스캔 → 직접 수신 RSSI 보고) -----
#define DEFAULT_ANCHOR          1     // 5장: 고정 앵커 역할. 시리얼 "anchor on|off"(NVS에 남김)
#define ANCHOR_SCAN_INTERVAL_MS 100
#define ANCHOR_SCAN_WINDOW_MS   100   // 패시브 스캔(스캔 요청 송신 없음). USB 전원이라 상시
#define ANCHOR_SCAN_CYCLE_S     10
#define ANCHOR_SCAN_RETRY_MS    1000
#define ANCHOR_SCAN_WATCHDOG_MS 5000
#define ANCHOR_QUEUE_RETRY_MS   300
#define ANCHOR_TX_RESERVE       1     // 사건·감지 패킷용으로 비워 두는 송신 큐 칸
#define ANCHOR_MAX_SOLDIERS     8
#define ANCHOR_RSSI_ALPHA       0.3f
#define ANCHOR_RSSI_DELTA_DB    6
#define ANCHOR_STALE_MS         45000
#define ANCHOR_MIN_REPORT_MS    2000
#define ANCHOR_MAX_REPORT_MS    15000

// ----- 진단 줄 ("# {...}") -----
// 규격 2장: 디버그 문구를 JSON 데이터 스트림에 섞지 않는다. 기본은 꺼짐 = USB에는 규격 JSON 줄만 나간다.
// 시험 보드는 "diag on"(NVS에 남김)으로 부팅·경고·자동 stats 줄을 켠다. 직접 보낸 명령의 응답은 항상 나온다.
#define DEFAULT_DIAG 0

// ----- 점검 ("check") -----
#define CHECK_ADC_SAMPLES  16
#define CHECK_ADC_HIGH_MV  3000  // 조도 분압 출력이 이보다 높으면 포화·과전압 의심
#define CHECK_ADC_LOW_MV   30    // 이보다 낮으면 단선·접지 단락 의심(아주 어두운 곳일 수도 있음)
#define CHECK_WATCH_MS     2000  // 디지털 핀 변화를 지켜보는 시간
