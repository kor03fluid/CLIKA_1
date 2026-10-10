#pragma once
// 노드 식별: boot_id와 패킷별 seq·uptime_ms.
#include <Arduino.h>
#include "packet.h"

void nodeBegin();
uint16_t nodeBootId();
// 새 패킷 머리를 채우고 seq를 하나 올린다. 반복 광고에는 다시 부르지 않는다.
void nodeFillHeader(PktHeader& h, uint8_t type, uint8_t flags);
