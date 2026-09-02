# firmware/ — ESP32 노드 펌웨어 (지시서 #4, Phase A)

시뮬(`sim/`)에서 검증된 node·network·verification 로직을 Arduino-ESP32로 이식.
**Phase A는 코드 구조 + Wokwi 검증**까지(실물 플래시는 Phase B, 부품 도착 후).

```
firmware/
├── node/
│   ├── node.ino     # 메인 스케치(센싱·하트비트·Last-Gasp·교차검증·LED)
│   ├── config.h     # 시뮬 파라미터 계승 + 노드별 ID/좌표 주입점 [D-023]
│   └── nodes.csv    # 16노드 ID/좌표(시뮬 build_grid와 일치, id0=루트)
├── diagram.json     # Wokwi 회로(ESP32 + DS18B20 + WS2812)
├── wokwi.toml       # Wokwi(VS Code 확장) 설정
└── flash_all.py     # 16보드 순차 플래시(ID/좌표 빌드플래그 주입)
```

## 필요 라이브러리 (Arduino Library Manager)
`painlessMesh`, `ArduinoJson`, `OneWire`, `DallasTemperature`, `Adafruit NeoPixel`
ESP32 코어: 보드매니저에서 `esp32 by Espressif`.

## Wokwi로 컴파일·기본 로직 검증 (Phase A DoD 1) — [D-025]
> 이 개발기엔 arduino-cli가 없어 로컬 컴파일은 못 함. 아래 중 하나로 검증:

- **웹(간단):** [wokwi.com](https://wokwi.com) → New ESP32 project → `node/node.ino` 내용 붙여넣기,
  `diagram.json` 붙여넣기 → ▶ 실행. `config.h`의 `FAKE_TEMP_RAMP=1` 이라 ~11초 후 온도가 80℃를 넘어
  **Last-Gasp**가 발동하고 LED가 초록→빨강으로 바뀌며 시리얼에 `LG` 패킷이 찍힌다.
- **VS Code:** Arduino/arduino-cli로 컴파일 후 Wokwi 확장(`wokwi.toml`)으로 시뮬.

> Wokwi는 단일 보드 기준이라 painlessMesh **다중노드 메시 RF**는 Phase B(실물)에서 검증한다.

## 16보드 플래시 절차 (Phase A DoD 3)
동일 스케치를 **노드별 ID/좌표만 바꿔** 16번 굽는다. `nodes.csv`의 값을 빌드 플래그로 주입:

```bash
# 사전: arduino-cli + esp32 코어 + 위 라이브러리 설치
arduino-cli core install esp32:esp32
arduino-cli lib install painlessMesh ArduinoJson OneWire DallasTemperature "Adafruit NeoPixel"

# 명령만 확인(플래시 안 함)
python firmware/flash_all.py --dry-run

# 보드 하나씩 연결하며 순차 플래시
python firmware/flash_all.py --port COM5           # Windows
python firmware/flash_all.py --port /dev/ttyUSB0   # Linux/Pi
```
각 보드마다 `-DNODE_ID=n -DNODE_X=.. -DNODE_Y=.. -DFAKE_TEMP_RAMP=0`(실센서)이 주입된다.
id0 = **루트**(게이트웨이로 USB 시리얼 전송). 나머지 15개 = 일반 노드.

## 시뮬↔펌웨어 파라미터 매핑
`docs/DECISIONS.md` D-023 표 참조(temp_threshold·K_confirm·silence_timeout 등 그대로 계승).
