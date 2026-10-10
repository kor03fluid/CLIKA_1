// PC에서 환경 노드의 JSON 출력 코드(json_out.cpp)만 빌드하기 위한 최소 Arduino 대체.
#pragma once
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>

#define HIGH 1
#define LOW 0

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
