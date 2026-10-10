#pragma once
// USB 시리얼 JSON 출력 (공통 데이터 규격 v1, docs/data_spec_v1.md). 한 줄에 객체 하나(NDJSON).
// BLE·센서와 분리해 두어 PC에서도 빌드해 출력 형식을 시험한다(pc/tests/test_env_module_contract.py).
// 데이터(JSON) 줄은 이 파일만 낸다. 다른 곳의 출력은 "# "로 시작하는 진단 줄이다.
#include <Arduino.h>
#include "packet.h"

// 숫자 node_id → 규격 문자열 ID (README 변환표, B와 확정할 안). out은 16B 이상.
void nodeName(uint8_t id, char* out, size_t len);

void printEnvironmentJson(const PktEnvironment& p);
void printEventJson(const PktEvent& p);
void printAnchorObsJson(const PktAnchorObs& p);
