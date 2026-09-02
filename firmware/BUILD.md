# BUILD.md — `node.ino` 빌드 재현 가이드

> **왜 이 파일이 있나:** 2026-08-04 첫 로컬 빌드에서 **함정 4개**를 만났다. 전부 *다른 PC에서
> 빌드하거나 라이브러리가 자동 갱신되면 그대로 재발하는* 종류다. 대회 제출 직전에 다시 겪으면
> 치명적이므로 채팅 기록이 아니라 저장소 안에 버전까지 못박아 남긴다. [D-046]

## 0. 검증된 환경 (이 조합에서 빌드 성공 확인)

| 항목 | 버전 |
|---|---|
| OS | Windows 11 Home 26200 |
| arduino-cli | **1.5.1** (2026-06-05) |
| ESP32 코어 | **esp32:esp32 3.3.11** |
| FQBN | `esp32:esp32:esp32` (DevKit WROOM-32) |
| 보드 USB 칩 | CP2102 (VID_10C4 / PID_EA60) |

**빌드 결과(기준선):** 플래시 **979,400 B / 1,310,720 B = 74 %**, RAM **48,804 B / 327,680 B = 14 %**
→ 코드가 커졌을 때 여유를 판단하는 기준. 플래시가 90 %를 넘기 시작하면 파티션 스킴 조정 검토.
(안전장치 [D-046] 추가 전은 978,288 B였다. 즉 안전장치 비용은 **+1,112 B**.)

---

## 1. 함정 4개와 해결

### 함정 ① 라이브러리 이름이 `painlessMesh`가 아니다
`arduino-cli lib install painlessMesh` → **`Library 'painlessMesh@latest' not found`**.
인덱스 등록명은 **`Painless Mesh`(공백 포함)** 이다. 소스코드의 `#include <painlessMesh.h>` 및
공식 문서 표기와 달라서, 이름을 그대로 옮겨 적으면 100 % 실패한다.

```
arduino-cli lib install "Painless Mesh"      # ← 공백. 이게 정답
```

> 참고: `Alteriom PainlessMesh`라는 서드파티 포크도 검색된다. **쓰지 말 것.** 우리는 공식(1.5.7).

### 함정 ② ArduinoJson 7이 깔리면 컴파일 불가 — 그리고 **혼자 되돌아온다**
`node.ino`는 `StaticJsonDocument<N>`을 쓴다. 이건 **v6 API**로, **v7에서 제거**됐다.
그런데 `arduino-cli lib install "ArduinoJson"`은 최신(7.4.3)을 가져온다.

**★ 진짜 함정은 여기다:** 6.21.5를 먼저 깔아도, 그 뒤에 `Painless Mesh`를 설치하면
의존성 해결이 **ArduinoJson을 7.4.3으로 다시 덮어쓴다.** 실제 로그:

```
Installing Painless Mesh@1.5.7...
Replacing ArduinoJson@6.21.5 with ArduinoJson@7.4.3...   ← 이것
```

따라서 **반드시 `Painless Mesh`를 먼저 설치하고, 그 다음에 ArduinoJson 6.21.5를 재고정**해야 한다.
순서를 반대로 하면 조용히 실패한다.

### 함정 ③ `AsyncTCP.h: No such file or directory`
`Painless Mesh`의 인덱스 의존성 목록에는 `ArduinoJson, TaskScheduler`만 있고 **AsyncTCP가 빠져 있다.**
ESP32 빌드에는 필수라 별도 설치해야 한다. 그런데 후보가 둘이다:

| 라이브러리 | 버전 | 판정 |
|---|---|---|
| `AsyncTCP` (구, me-no-dev) | 1.1.1~1.1.4 | ❌ 2020년판. **ESP32 코어 3.x(IDF 5.x) 비호환** |
| **`Async TCP`** (ESP32Async 유지보수판) | 3.5.0 | ✅ **이걸 쓸 것**(공백 포함 이름) |

### 함정 ④ 한글 경로가 GNU 툴체인을 깨뜨린다
저장소가 `C:\Users\<사용자>\Desktop\자소서\...`에 있어서 그대로 빌드하면:

```
ld.exe: cannot open output file C:\Users\<한글>\... : Invalid argument
```

`--build-path`만 영문으로 바꾸면 이번엔 `cannot find -lm / -lgcc`가 뜬다 — **SDK 자체가**
한글 경로 아래 있기 때문. 그래서 **SDK와 스케치북을 통째로 영문 경로로 옮겼다.**

| 항목 | 경로 |
|---|---|
| SDK(packages, 약 6 GB) | `C:\Users\Public\arduino15\` |
| 스케치북 | `C:\Users\Public\esp32\sketchbook\` |
| **`build_cache.path`** | `C:\Users\Public\arduino15\cache` ← **이걸 빼면 계속 실패** |
| 설정 파일 | `C:\Users\<사용자>\.arduinoIDE\arduino-cli.yaml` |

`directories.data/downloads/user`만 바꾸고 **`build_cache.path`를 빼먹으면** 캐시가 한글 경로에
남아 동일 증상이 재발한다. 이 한 줄이 핵심이다.

**결과적으로 저장소(`firmware/node/`)가 원본이고, 빌드 시 영문 경로로 복사해서 쓴다.**
저장소에서 직접 빌드하지 말 것.

---

## 2. 재현 스크립트 (순서대로 치기만 하면 됨)

```bash
# --- 0) 코어 ---
arduino-cli core install esp32:esp32@3.3.11

# --- 1) 단순 의존 라이브러리 ---
arduino-cli lib install "OneWire"
arduino-cli lib install "DallasTemperature"
arduino-cli lib install "Adafruit NeoPixel"

# --- 2) 메시 (★순서 중요: 이걸 ArduinoJson보다 먼저) ---
arduino-cli lib install "Painless Mesh"        # 공백 포함. painlessMesh 아님(함정 ①)
arduino-cli lib install "Async TCP"            # 공백 포함. 구 AsyncTCP 1.1.x 아님(함정 ③)

# --- 3) ★ArduinoJson 재고정 (반드시 Painless Mesh 뒤에) ---
arduino-cli lib install "ArduinoJson@6.21.5"   # 7.x면 StaticJsonDocument 없음(함정 ②)

# --- 4) 확인: 아래와 일치해야 함 ---
arduino-cli lib list
#   Adafruit NeoPixel 1.15.5
#   ArduinoJson       6.21.5   ← 7.x면 위 3) 다시 실행
#   Async TCP         3.5.0
#   DallasTemperature 4.0.6
#   OneWire           2.3.8
#   Painless Mesh     1.5.7
#   TaskScheduler     4.0.8    (Painless Mesh가 자동 설치)

# --- 5) 영문 경로로 복사 후 빌드 (함정 ④) ---
mkdir -p "C:/Users/Public/esp32/sketchbook/node"
cp firmware/node/node.ino firmware/node/config.h "C:/Users/Public/esp32/sketchbook/node/"
arduino-cli compile --fqbn esp32:esp32:esp32 "C:/Users/Public/esp32/sketchbook/node"

# --- 6) 업로드 (COM 포트는 `arduino-cli board list`로 확인) ---
arduino-cli upload -p COM3 --fqbn esp32:esp32:esp32 "C:/Users/Public/esp32/sketchbook/node"
```

편의 스크립트: `scripts/build_node.ps1` (복사 → 컴파일 → 업로드 → 시리얼 캡처까지 한 번에)

---

## 3. 하드웨어 메모

### 배선 (현재 기준)
| 부품 | 핀 | ESP32 |
|---|---|---|
| DS18B20 모듈 | DAT | **GPIO4** (`PIN_ONEWIRE`) |
| | VCC / GND | 3V3 / GND |
| WS2812 | DIN | **GPIO5** (`PIN_NEOPIXEL`) |
| | VCC / GND | VIN(USB 5 V) / GND |

DS18B20은 **모듈형**이라 4.7 kΩ 풀업이 보드에 내장 — 외부 저항 불필요.

### ⚠️ WS2812 전압 레벨 (미리 대비할 필요 없음. 증상 나오면 이걸 의심)
WS2812는 데이터선에 **5 V 로직**을 기대하는데 ESP32는 **3.3 V**로 내보낸다.
LED 1~2개는 대개 그냥 동작하지만, **여러 개 물렸을 때 색이 튀거나 안 켜지면
배선 실수가 아니라 이 전압 차 문제일 수 있다.**
→ 해결: 데이터선에 **직렬저항 300~470 Ω**, 또는 **레벨시프터**(74AHCT125 등).

DIN/DOUT은 **방향이 있다** — 화살표가 시작되는 쪽이 DIN. 반대로 꽂으면 아무것도 안 켜진다.

전류: 펌웨어는 픽셀 1개만 낮은 밝기로 켜므로 ~10 mA. USB로 충분하다.
**단 20개를 전부 흰색 최대 밝기로 켜면 최대 ~1.2 A**로 USB 5 V 공급을 초과한다 — 별도 전원 필요.

---

## 4. 알려진 미해결 항목 (빌드와 무관하지만 여기 적어둠)

**펌웨어 ↔ 게이트웨이 메시지 타입 어휘가 거의 안 맞는다.**

| | 타입 |
|---|---|
| `gateway.py`가 처리 | `META` `NODES` `DC` `ROUTE` `GT` `STATS` `TICK` |
| `node.ino`가 송신 | `MODE` `ROOT_READY` `ST` `HB` `LG` `DV` `DC` |
| **교집합** | **`DC` 하나뿐** |

`gateway.py`는 `META`로 `Config`를 만들고 `TICK`으로 프레임을 생성하는데, 펌웨어는 둘 다 안 보낸다.
따라서 **현재 실보드를 gateway에 직접 물리면 프레임 0개**다.
→ 실보드 end-to-end를 하려면 (a) 펌웨어가 `META`/`TICK`을 내보내거나
(b) 게이트웨이에 `HB`/`LG`→`NODES` 변환 어댑터를 넣어야 한다. 별도 작업으로 남김.
