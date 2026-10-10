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
#define INPUT 0
#define INPUT_PULLUP 2
#define RISING 1
#define FALLING 2
#define IRAM_ATTR

#include <math.h>  // Arduino처럼 isnan·sinf·lroundf를 전역 이름으로
using std::isnan;

inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline void analogReadResolution(int) {}

// 시험이 정하는 핀 입력과 인터럽트(핀 번호별)
extern int g_pin_level[64];
extern void (*g_isr[64])();
inline int digitalRead(uint8_t pin) { return g_pin_level[pin]; }
inline int digitalPinToInterrupt(int pin) { return pin; }
inline void attachInterrupt(int pin, void (*fn)(), int) { g_isr[pin] = fn; }

// FreeRTOS 잠금 대체(단일 스레드 시험)
struct portMUX_TYPE { int unused; };
#define portMUX_INITIALIZER_UNLOCKED {0}
#define portENTER_CRITICAL(m) ((void)(m))
#define portEXIT_CRITICAL(m) ((void)(m))
#define portENTER_CRITICAL_ISR(m) ((void)(m))
#define portEXIT_CRITICAL_ISR(m) ((void)(m))

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
