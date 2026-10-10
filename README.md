# CLIKA_1

Arduino 센서 라이브러리 모음.

| 폴더 | 센서 | 원본 | 라이선스 |
|---|---|---|---|
| `MPU6050/` | MPU-6050 6축 IMU (가속도/자이로, Madgwick 쿼터니언 필터) | [kriswiner/MPU6050](https://github.com/kriswiner/MPU6050) | 명시 없음 |
| `HCSR04-ultrasonic-sensor-lib/` | HC-SR04 초음파 거리 센서 | [gamegine/HCSR04-ultrasonic-sensor-lib](https://github.com/gamegine/HCSR04-ultrasonic-sensor-lib) | MIT |
| `RBD_LightSensor/` | 포토레지스터 조도 센서 | [alextaujenis/RBD_LightSensor](https://github.com/alextaujenis/RBD_LightSensor) | MIT |
| `DHT-sensor-library/` | DHT11/DHT22 온습도 센서 | [adafruit/DHT-sensor-library](https://github.com/adafruit/DHT-sensor-library) | MIT |
| `Adafruit_Sensor/` | Adafruit Unified Sensor (DHT 라이브러리 의존성) | [adafruit/Adafruit_Sensor](https://github.com/adafruit/Adafruit_Sensor) | Apache-2.0 |

## 펌웨어·PC (SQUAD LINK 팀원 C 담당)

데이터 형식은 팀 공통 규격 [`docs/data_spec_v1.md`](docs/data_spec_v1.md)(v1.0)을 따른다.

| 폴더 | 내용 | 상태 |
|---|---|---|
| `docs/data_spec_v1.md` | SQUAD LINK 공통 데이터 규격 v1 (팀 공유 문서 원문) | - |
| `docs/c_hw_test.md` | 팀원 C 실물 시험 절차와 기록표(단독 확인·연동·수신 누락·송신량·전류·인계) | 실물 도착 후 사용 |
| `firmware/env_node/` | 환경 노드 (ESP32 WROOM): DHT11·조도·추가 센서, 열 노출 사건, 앵커 관측, 규격 v1 USB 출력 | 빌드·JSON 출력 시험 |
| `pc/` | C 시험 서버·도구: 환경 노드 USB 출력·앵커 관측 확인, 실물 시험 측정(`report.py`), 펌웨어 출력 규격 시험, 가상 노드. **공식 PC 관제는 팀장 서버(`node server.mjs`)** | 단위 테스트·가짜 시리얼 시험 |

## 설치

각 라이브러리 폴더를 Arduino `libraries` 폴더(보통 `~/Documents/Arduino/libraries/`)에 복사한 뒤 Arduino IDE를 재시작한다.
`MPU6050/`은 라이브러리 형식이 아니라 스케치 모음이므로 `.ino` 파일을 직접 연다.

## 빠른 사용 예

```cpp
#include <HCSR04.h>
#include <RBD_LightSensor.h>
#include <DHT.h>

HCSR04 hc(2, 3);                 // trig, echo
RBD::LightSensor light(A0);
DHT dht(4, DHT22);

void setup() {
  Serial.begin(115200);
  dht.begin();
}

void loop() {
  Serial.print("dist(cm): ");  Serial.println(hc.dist());
  Serial.print("light(%): ");  Serial.println(light.getPercentValue());
  Serial.print("temp(C): ");   Serial.println(dht.readTemperature());
  Serial.print("hum(%): ");    Serial.println(dht.readHumidity());
  delay(2000);                 // DHT22는 최소 2초 간격 필요
}
```
