// PC 시험용 조도 센서 대체: 떠 있는 ADC처럼 시험이 정한 값을 돌려준다.
#pragma once
extern int g_light_raw;
namespace RBD {
class LightSensor {
 public:
  explicit LightSensor(int) {}
  int getRawValue() { return g_light_raw; }
};
}  // namespace RBD
