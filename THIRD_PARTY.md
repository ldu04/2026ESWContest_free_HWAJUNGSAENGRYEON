# 오픈소스 고지 (Third-Party Notices)

본 프로젝트는 아래 오픈소스를 사용합니다. 각 라이선스 전문은 [`licenses/`](licenses/) 에 포함했습니다.

---

## 노드 펌웨어 (`firmware/node/`)

| 라이브러리 | 버전 | 라이선스 | 원본 | 용도 |
|---|---|---|---|---|
| **painlessMesh** | 1.5.7 | **GPL-3.0-only** ([전문](licenses/painlessMesh-GPL-3.0.txt)) | <https://gitlab.com/painlessMesh/painlessMesh> | 자가치유 WiFi 메시 · 노드 간 브로드캐스트 · **메시 동기 시각(`getNodeTime()`)** |
| **AsyncTCP** (ESP32Async 유지보수판) | 3.5.0 | LGPL-3.0 ([전문](licenses/AsyncTCP-LGPL-3.0.txt)) | <https://github.com/ESP32Async/AsyncTCP> | painlessMesh 의 TCP 백엔드 (직접 호출 없음) |
| **TaskScheduler** | 4.0.8 | BSD-3-Clause ([전문](licenses/TaskScheduler-BSD-3-Clause.txt)) | <https://github.com/arkhipenko/TaskScheduler> | painlessMesh 가 요구하는 협조적 스케줄러 |
| **ArduinoJson** | **6.21.5** | MIT ([전문](licenses/ArduinoJson-MIT.txt)) | <https://arduinojson.org> | 노드 패킷(HB/LG/DV/DC) 직렬화 |
| **OneWire** | 2.3.8 | MIT ([전문](licenses/OneWire-MIT.txt)) | <https://github.com/PaulStoffregen/OneWire> | DS18B20 1-Wire 버스 |
| **DallasTemperature** | 4.0.6 | MIT ([전문](licenses/DallasTemperature-MIT.txt)) | <https://github.com/milesburton/Arduino-Temperature-Control-Library> | DS18B20 온도 읽기 · 해상도(9비트) 설정 |
| **Adafruit NeoPixel** | 1.15.5 | LGPL-3.0 ([전문](licenses/Adafruit_NeoPixel-LGPL-3.0.txt)) | <https://github.com/adafruit/Adafruit_NeoPixel> | WS2812 상태 표시 LED |

> **ArduinoJson 은 6.x 를 고정한다.** 7.x 에서 `StaticJsonDocument` 가 제거돼 빌드가 깨진다.
> 설치 순서도 중요하다 — 자세한 내용은 [`firmware/BUILD.md`](firmware/BUILD.md).

## 게이트웨이 (`gateway/`)

| 패키지 | 버전 | 라이선스 | 용도 |
|---|---|---|---|
| pyserial | 3.5 | BSD-3-Clause | 브리지 ESP32 시리얼 수신 |
| NumPy | 2.4.4 | BSD-3-Clause | 최소제곱 평면적합 · 벡터 집계 |

## 플랫폼

| 항목 | 버전 | 라이선스 |
|---|---|---|
| Arduino core for ESP32 | 3.3.11 | LGPL-2.1 (core) / Apache-2.0 (ESP-IDF 구성요소) |

---

## ★ 라이선스 판단 — 본 프로젝트는 GPL-3.0 으로 배포합니다

노드 펌웨어(`firmware/node/node.ino`)는 **painlessMesh(GPL-3.0)** 와 링크됩니다.
GPL-3.0 은 강한 카피레프트라, 이를 링크한 저작물을 배포할 때 **전체를 GPL-3.0 호환 조건으로
배포해야 합니다.** 저장소를 Public 으로 공개하는 것 자체가 배포에 해당하므로,
프로젝트 전체 라이선스를 **GPL-3.0** 으로 둡니다. ([`LICENSE`](LICENSE))

- 함께 쓰는 MIT · BSD-3-Clause · LGPL-3.0 은 모두 GPL-3.0 과 **호환**되므로 충돌이 없습니다.
- 저작권 표시와 라이선스 전문은 [`licenses/`](licenses/) 에 원문 그대로 보존했습니다.
- 링크로 갈음하지 않고 전문을 동봉한 이유: GPL/LGPL 은 **라이선스 사본 첨부를 요구**하며,
  MIT·BSD 는 **저작권 표시와 라이선스 문구의 보존**을 요구합니다. 원격 링크는 이를 충족하지 않습니다.

### painlessMesh 라이선스 — 설치본 원본 기준 확인 (2026-08-28)

2차 자료가 아니라 **설치된 파일 자체**를 열어 확인했다.

| 확인 항목 | 결과 |
|---|---|
| `LICENSE` 파일 | GPL-3.0 전문 674줄. 첫 두 줄이 아래 인용 |
| `library.properties` | **`license=` 필드 없음** (`name` `version` `author` `maintainer` `sentence` `paragraph` `category` `url` 만) |
| `library.json` | **`license` 필드 없음** (`name` `keywords` `description` `repository` `version` `frameworks` `platforms` `dependencies` `authors` `headers`) |
| 소스 헤더(`src/painlessMesh.h`) | 라이선스 문구 없음 |
| 이중 라이선스 / 링킹 예외 | **없음.** `dual` `alternative licen` `commercial licen` `exception` 검색 결과 해당 조항 없음 |

`LICENSE` 첫 두 줄 원문:

```
                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007
```

**"or later" 는 선언돼 있지 않다.** 파일 안에 `any later version` 이 나오는 곳은 574·587·640행인데,
574·587행은 **§14 Revised Versions 조문 자체**이고 640행은 **부칙 "How to Apply These Terms to Your
New Programs"(623행 시작)의 예시문**이다. 셋 다 GPL 표준 문구이지 painlessMesh 저작자의 선언이 아니다.

§14 원문 (563~578행):

```
  Each version is given a distinguishing version number.  If the
Program specifies that a certain numbered version of the GNU General
Public License "or any later version" applies to it, you have the
option of following the terms and conditions either of that numbered
version or of any later version published by the Free Software
Foundation.  If the Program does not specify a version number of the
GNU General Public License, you may choose any version ever published
by the Free Software Foundation.
```

⇒ **판정: `GPL-3.0-only`** (SPDX). 버전 3이 `LICENSE` 파일로 특정돼 있고 "or later" 선언이 없으므로,
버전 선택권 없이 **GPL-3.0 조건만** 따른다. 본 프로젝트도 같은 조건으로 배포한다.

> 주의: 배포 카탈로그·패키지 인덱스에는 종종 `GPL-3.0` 으로만 표기되나, 그것은 요약 표기이고
> **원본 파일 기준으로는 `or later` 가 없다.** 위 표가 그 근거다.

> 시뮬레이터(`sim/`)·게이트웨이(`gateway/`)·대시보드(`dashboard/`)는 painlessMesh 와 링크되지
> 않으나, 하나의 저작물로 함께 배포하므로 동일하게 GPL-3.0 을 적용합니다.
