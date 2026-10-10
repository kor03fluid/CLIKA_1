# A 보드와 USB 관제 연결

1. Python이 있는지 `python --version`으로 확인합니다.
2. `python -m pip install pyserial`로 USB 입력 라이브러리를 설치합니다.
3. `python communication/serial_bridge.py --list`로 포트를 확인합니다.
4. config/system.json에서 input.driver를 serial, serial.port를 해당 COM 포트로 변경합니다. input.mode는 simulation을 유지합니다. 센서 없는 보드 가상값은 실제 실측이 아닙니다.
5. A의 Serial.begin 속도와 serial.baud_rate를 맞춥니다. 기본 115200입니다.
6. Arduino 시리얼 모니터·플로터를 닫습니다. 서버 Ctrl+C 후 node server.mjs로 재시작합니다.
7. 새 터미널에서 python communication/serial_bridge.py를 실행합니다.
8. 관제에서 병사 01은 연결, 병사 02는 연결 대기, 나머지는 미배정이면 됩니다. 보드 한 대만 연결했을 때 병사 02를 연결로 표시하지 않습니다.

## A가 출력할 것
UTF-8 JSON 객체 한 줄 뒤에 개행을 출력합니다. source=simulation, node_id=halo_01, route=simulation, hop_count=0, relay_id=null입니다. 규격 전체 예시는 docs/SQUAD_LINK_공통데이터규격_v1.md를 따릅니다. boot_id는 부팅마다 바뀌어야 하고 seq는 같은 부팅에서 패킷 유형을 통틀어 증가합니다. 상태 패킷의 heartbeat_interval_ms는 실제 출력 간격과 일치시킵니다. 센서 미연결 실측은 null/unavailable이지만, 이번 가상값 실험은 source=simulation으로 명시합니다.

## 확인
보드의 JSON이 정상일 때 브리지에는 accepted:true가 표시되고 관제에도 나타납니다. USB를 빼고 보고 주기 기준 시간(5초 주기면 17초 초과)을 기다리면 두절이 됩니다. 다시 연결해 새 패킷이 들어오면 복구됩니다. 일부 보드는 포트 열기 때 재부팅될 수 있으므로 boot_id가 바뀌어야 합니다.

USB 라이브러리 설치 전에도 --stdin 모드는 실행할 수 있습니다. 잘못된 JSON과 보드 부팅 메시지는 SKIP, 규격 오류는 REJECT로 출력하고 계속 진행합니다. USB 재접속은 자동 재시도합니다. HTTP 전달 실패 패킷은 버리고 다음 주기의 새 패킷을 기다립니다. 이 브리지는 지연 재전송 큐를 아직 제공하지 않으므로 서버가 꺼진 동안의 SOS 보장 기능은 이후 보드 측 반복 전송과 함께 검증해야 합니다.

보드 간 BLE·실제 COM 포트 연결은 현장에서 별도 검증해야 합니다.
