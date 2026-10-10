#pragma once
// 원본 식별(규격 4장): node_id, boot_id, seq, uptime_ms.
// - node_id: 이번 부팅의 ID(settings). 부팅 중에는 바뀌지 않는다.
// - boot_id: 부팅마다 새로 만든다. 같은 boot_id로 seq만 초기화하지 않는다.
// - seq: 패킷 종류와 출처(device·simulation)를 통틀어 부팅 내 하나의 번호열. 재사용하지 않는다.
#include <Arduino.h>
#include "packet.h"

void identBegin();  // settingsBegin() 다음에 부른다
uint8_t identNodeId();
uint16_t identBootId();
void identName(char* out, size_t len);  // "env_01"
// 새 패킷 머리를 채우고 seq를 하나 올린다. 반복 광고에는 다시 부르지 않는다(같은 seq 유지).
void identFillHeader(PktHeader& h, uint8_t type, uint8_t flags);
