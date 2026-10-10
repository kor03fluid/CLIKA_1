#pragma once
// 보드마다 다른 설정을 NVS(플래시)에 남긴다. 같은 펌웨어를 env_01과 예비 WROOM(env_02)에 올리고
// 시리얼 명령으로 ID·켠 추가 센서·앵커 역할을 정한다(5장: 예비 WROOM은 같은 환경 펌웨어를 준비한 교체용).
#include <stdint.h>

struct Settings {
  uint8_t node_id;   // 부록 A 숫자 ID, 0x31~0x3F(env_01~env_15)
  bool    virtual_sensors;  // 데이터 출처: 가상(true, 기본) / 실제 센서(false)
  uint8_t use_mask;  // 실제 센서 모드에서 켠 추가 센서(DET_SOUND·DET_FLAME·DET_SHOCK·DET_REED)
  bool    anchor;    // 고정 앵커 역할(병사 방송 스캔·관측 보고)
  bool    adaptive;  // 보고 정책: 적응(true) / 고정 5초(false)
  bool    diag;      // 진단 줄("# ...")을 USB에 낼지. 기본 꺼짐(규격 2장)
};

void settingsBegin();  // NVS에서 읽는다. 없거나 범위 밖이면 기본값(config.h)
const Settings& settings();

// 저장하고 바로 settings()에 반영한다. 노드 ID는 저장만 하고 재시작 후 적용한다(부팅 중 ID가 바뀌지 않게).
bool settingsSetNodeId(uint8_t id);  // 환경 노드 범위가 아니면 false
uint8_t settingsSavedNodeId();
void settingsSetVirtual(bool on);
void settingsSetUse(uint8_t mask);
void settingsSetAnchor(bool on);
void settingsSetAdaptive(bool on);
void settingsSetDiag(bool on);
void settingsFactory();  // 기본값으로 되돌린다(부팅 번호는 남겨 boot_id가 겹치지 않게)

bool validEnvNodeId(uint8_t id);
// "env_02" → 0x32. 환경 노드 이름이 아니면 false
bool parseEnvNodeName(const char* s, uint8_t* id);
