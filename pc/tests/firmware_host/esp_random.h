// PC 시험용 esp_random 대체: 정해진 값을 돌려준다.
#pragma once
#include <cstdint>
inline uint32_t esp_random() { return 0x00051a2bu; }
