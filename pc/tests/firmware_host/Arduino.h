// PC에서 환경 노드의 일부(json_out.cpp·node.cpp·ble_tx.cpp)만 빌드하기 위한 최소 Arduino 대체.
#pragma once
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#define HIGH 1
#define LOW 0
#define OUTPUT 1

inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}

struct String {
  std::string s;
  String(const char* p, size_t n) : s(p, n) {}
};

struct HostSerial {
  int printf(const char* fmt, ...) __attribute__((format(printf, 2, 3))) {
    va_list ap;
    va_start(ap, fmt);
    int n = vprintf(fmt, ap);
    va_end(ap);
    return n;
  }
  size_t print(const char* s) { return fputs(s, stdout) >= 0 ? strlen(s) : 0; }
};

extern HostSerial Serial;

// 시험이 정하는 가짜 시각
extern uint32_t g_millis;
inline uint32_t millis() { return g_millis; }
