#pragma once
// 환경 노드 설정. 핀·주기·임계값은 실물 확인과 센서 로그로 조정한다.
#include <Arduino.h>

// ===== 노드 식별 =====
// 무선 패킷의 숫자 ID와 규격 문자열 ID(안, 팀원 B와 확정. node.cpp nodeName):
//   0x01~0x1F halo_01~  · 0x20~0x27 gateway_01~ · 0x28~0x2F relay_01~ · 0x31~0x3F env_01~
#define NODE_ID 0x31  // env_01 (WROOM 1). 예비 WROOM은 0x32(env_02)로 빌드

// ===== 핀 (ESP32 WROOM DevKit 기준) =====
// 5V 출력 신호를 GPIO·ADC에 직접 넣지 않는다. 모듈은 3.3V로 공급하거나 분압·레벨 변환한다.
#define PIN_LED    2   // 보드 내장 LED. 송신 창 동안 켜짐
#define PIN_DHT    4   // DHT11 DATA
#define PIN_LIGHT  34  // 조도(포토레지스터 분압) 아날로그. ADC1 입력 전용 핀
#define PIN_SOUND  27  // 소리 센서 DO
#define PIN_FLAME  26  // 불꽃 센서 DO
#define PIN_SHOCK  25  // 충격 센서 DO
#define PIN_REED   33  // 리드스위치(핀-GND), 내부 풀업

// 추가 센서 사용 여부. 필수 센서(DHT11·조도)는 항상 사용
#define USE_SOUND 1
#define USE_FLAME 1
#define USE_SHOCK 1
#define USE_REED  1

// 디지털 모듈 출력의 활성 레벨. 모듈마다 다르므로 실물로 확인 후 수정
#define SOUND_ACTIVE_LEVEL HIGH
#define FLAME_ACTIVE_LEVEL LOW
#define SHOCK_ACTIVE_LEVEL HIGH
#define REED_OPEN_LEVEL    HIGH  // 자석 떨어짐(열림) → 풀업으로 HIGH
#define REED_DEBOUNCE_MS   50

// ===== 판단 (센서 로그로 조정) =====
// 공기 온도 기준 "환경 열 노출 주의". 개인 체온·과열 판정이 아니다.
#define HEAT_ON_C  35.0f
#define HEAT_OFF_C 34.0f  // 히스테리시스

// ===== 측정 주기 =====
#define DHT_READ_MS   2000  // DHT11은 1초 이상 간격 필요
#define LIGHT_READ_MS 500

// ===== 송신 정책 =====
// 기준(고정 5초)과 적응 설정을 비교한다. 시리얼 명령 "mode fixed|adaptive"로 전환
#define TX_MODE_ADAPTIVE_DEFAULT 1
#define TX_FIXED_INTERVAL_MS  5000
// 노드는 현재 정상 보고 주기를 heartbeat_interval_ms로 선언한다. 서버 두절 기준 = max(15초, 3×주기+2초)
#define ENV_HEARTBEAT_MS      30000  // 적응: 변화 없을 때 최대 간격 → 두절 기준 92초
#define ENV_ALERT_INTERVAL_MS 10000  // 적응: 열 노출·불꽃 상태 지속 중 간격
#define ENV_MIN_GAP_MS        3000   // 적응: 값 변화로 인한 송신 최소 간격
#define EVENT_MIN_GAP_MS      2000   // 감지(소리·충격 등) 즉시 송신 최소 간격(연속 반응 억제)
#define EVENT_REPEATS         3      // 사건·감지 패킷 반복 광고 창 수(같은 seq)
#define DELTA_TEMP_C    1.0f
#define DELTA_HUM_PCT   5
#define DELTA_LIGHT_RAW 400  // 12bit 원시값 기준(약 10%)

// ===== BLE 광고 =====
// 송신 출력은 실물 시험으로 수신 목표를 만족하는 낮은 고정값을 고른다.
#define BLE_TX_POWER       ESP_PWR_LVL_N0  // 0 dBm
#define TX_ADV_INTERVAL_MS 100
#define TX_WINDOW_MS       300  // 패킷 1회 = 광고 창 1개(약 3 광고 이벤트)
#define TX_REPEAT_GAP_MS   500
#define TX_QUEUE_LEN       6

// ===== 앵커 (병사 직접 방송 RSSI 관측) =====
#define ANCHOR_ENABLE 1
#define ANCHOR_SCAN_INTERVAL_MS 100
#define ANCHOR_SCAN_WINDOW_MS   100  // 패시브 스캔(스캔 요청 송신 없음). USB 전원이라 100% 듀티
#define ANCHOR_SCAN_CYCLE_S     10   // 스캔 결과 버퍼 정리 주기
#define ANCHOR_SCAN_RETRY_MS    1000 // 스캔 시작이 실패하면 이만큼 기다렸다 다시 시도
#define ANCHOR_MAX_SOLDIERS     8
#define ANCHOR_RSSI_ALPHA       0.3f  // EMA 평활 계수
#define ANCHOR_RSSI_DELTA_DB    6     // 보고된 값 대비 이만큼 바뀌면 즉시 보고
#define ANCHOR_STALE_MS         45000 // 이 시간 동안 못 받으면 보고에서 제외
#define ANCHOR_MIN_REPORT_MS    2000
#define ANCHOR_MAX_REPORT_MS    15000 // 변화 없어도 이 주기로 묶어 보고
