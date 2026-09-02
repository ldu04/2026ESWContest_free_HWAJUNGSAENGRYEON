# 불사 (不死) — 고장을 데이터로 바꾸는 자가치유 산불 감시 메시

> **제24회 임베디드SW경진대회 · 자유공모 부문**
> **팀 화중생련(火中生蓮) · Hwajungsaengryeon** — 숭실대학교

산불 최전선에서 센서 노드는 **반드시 죽는다.** 기존 시스템은 그것을 손실로 처리하지만,
우리는 **관측**으로 쓴다. 노드가 타 죽는 순간 남기는 `(좌표, 자기가 각인한 사망시각)` 쌍을 모으면
도착시각장 `T(x, y)` 가 되고, 그 기울기에서 **화선의 방향·속도·도착예정시각(ETA)** 이 나온다.
노드가 파괴돼도 메시는 스스로 우회해 관측을 계속 실어 나른다. **죽음이 곧 데이터다.**

| | |
|---|---|
| **소스코드** | <https://github.com/ldu04/2026ESWContest_free_HWAJUNGSAENGRYEON> |
| **시연영상** | <https://youtu.be/ZDX_D-6ZaC0> |
| **실증 규모** | ESP32 **16노드** 4×4 격자 · 실제 열원으로 순차 소사 (2026-09-01) |
| **실측 성능** | 화선 방향 오차 **2.85°** · 속도 오차 **+1.67 %** · 대피 경보 **13/16 노드**가 사망 전 수신 |
| **라이선스** | **GPL-3.0-only** ([LICENSE](LICENSE)) |

> 위 성능 수치는 **이 저장소 안의 파일만으로 직접 재계산할 수 있다.** → [재현 ②](#재현--본편-런의-실측-수치를-직접-검산한다)

---

## ★ 어디를 보면 되는가 — 핵심 4파일

저장소 전체를 읽을 필요 없다. 이 네 개가 주장의 전부다.

| 파일 | 줄 | 무엇을 하는가 |
|---|---|---|
| **[`sim/estimator.py`](sim/estimator.py)** | 142 | **핵심 알고리즘.** 사망 이벤트 → ① 이웃과 함께 국소 평면 최소제곱 `t ≈ ax+by+c` → 기울기 `∇T` 에서 방향·속도 ② 전역 집계. `_fit_local` / `_fit_global` 두 함수가 전부다 |
| **[`sim/verification.py`](sim/verification.py)** | 190 | **오탐 방어.** "통신두절"과 "진짜 파괴"를 가르는 3분기 선별. 잠깐 끊긴 노드를 죽었다고 하면 없는 불을 그린다 |
| **[`firmware/node/node.ino`](firmware/node/node.ino)** | 354 | **노드 펌웨어.** 온도 감시 → 임계 초과 시 `mesh.getNodeTime()` 으로 **사망시각 자기각인** → 임종신호(Last-Gasp) → 송신 중단. 이웃 침묵 교차검증도 여기 |
| **[`gateway/fw_adapter.py`](gateway/fw_adapter.py)** | 416 | **펌웨어 ↔ 게이트웨이 변환.** 노드 방언을 추정기 입력으로. `getNodeTime()` 의 71.6분 랩어라운드 보정이 여기 있다 |

### 설계의 핵심 한 줄

> **사망시각은 죽은 노드가 자기 시계로 각인한 값이다. 게이트웨이 수신 시각이 아니다.**
> 통신 지연이 도착시각장을 오염시키면 `∇T` 가 곧바로 망가지기 때문이다.
> 이 규약이 `node.ino` · `fw_adapter.py` 전반에 박혀 있다.

---

## 디렉터리

```
sim/         시뮬레이터 · 추정기 · 집계 · 검증        ← 알고리즘 본체
firmware/    ESP32 노드 펌웨어 · 굽기 도구
gateway/     시리얼 수신 → 어댑터 → 추정기 → 대시보드
dashboard/   자체완결 HTML+JS 관제 플레이어 (서버 불필요)
tests/       자동 테스트 60건
scripts/     실험 하네스 (스트레스·스윕·감사)
tools/       점검·검산 도구 (본편 런 재계산 포함)
results/     측정 산출물 — stress/ 는 시뮬, hw/ 는 실보드 캡처
docs/        설계 결정·진행 기록·보고서 (DECISIONS.md 가 결정 대장)
licenses/    사용 오픈소스 라이선스 전문
```

---

## 재현 ① — 하드웨어 없이 돌려볼 수 있다

```bash
pip install -r gateway/requirements.txt

# 1) 자동 테스트 60건        (약 45초)
python -m pytest tests/ -q

# 2) 시뮬 전 구간 (모의 스트림 → 게이트웨이 → 추정기 → 대시보드 데이터)
python gateway/mock_serial.py
python gateway/gateway.py --in results/dashboard/mock_stream.jsonl --emit-dashboard

# 3) 펌웨어 방언까지 포함한 end-to-end (보드 없이)
python gateway/mock_fw_serial.py --fake 1
python gateway/gateway.py --in results/dashboard/mock_fw_stream.jsonl --fw --emit-dashboard

# 4) 대시보드: results/dashboard/gateway_data.js 를 dashboard/data.js 로 복사한 뒤
#    dashboard/index.html 을 브라우저로 연다 (서버 불필요)
```

> `mock_fw_serial.py` 로 만든 스트림은 **모든 줄에 `fake=1`** 이 박힌다.
> 합성 데이터가 실측으로 오인되지 않게 하는 안전장치다(`docs/DECISIONS.md` D-046).

---

## 재현 ② — 본편 런의 실측 수치를 직접 검산한다

맨 위 표의 **2.85° / +1.67 % / 13-of-16** 을 원자료에서 처음부터 다시 계산한다.
외부 파일이 필요 없다. 저장소만 클론하면 된다.

```bash
python tools/recompute_run205330.py
```

```
방향  참값 55.4826 °   추정 58.3293 °   오차 +2.8467 °  ->  2.85 °
속도  참값 0.0005785   추정 0.000588187   오차 +1.6745 %  ->  +1.67 %
사망  16 / 16 노드
경보  13 / 16 노드가 사망 전 수신
      리드타임  최소 87 · 중앙 344 · 최대 523 · 평균 351 초

docs/실측값_대장.md §6-A 대조 … 8개 항목 전부 일치
```

읽는 파일은 둘뿐이다.

| 파일 | 무엇 |
|---|---|
| `results/hw/run_205330.json` | 프레임 1,955개의 추정 산출물 (`est.dir` / `est.speed` / `est.alerts`) |
| `results/hw/run_205330_deaths.csv` | 사망 대장 16건 — 노드별 좌표·**자기각인 사망시각**·채택 분기 |

`results/hw/run_205330_raw.log` 는 게이트웨이 기동~종료 연속 원시 로그다.

> **리드타임의 사망시각은 프레임에서 노드가 처음 `DEAD` 로 보인 시각**이다.
> `deaths.csv` 의 `death_t_est`(노드가 자기 시계로 각인한 값)가 아니다 — 그쪽으로 재면
> 중앙 346 · 최대 526 · 평균 348 이 되어 대장과 2~3초 어긋난다. 경보 시각을 프레임에서
> 집으므로 사망 시각도 같은 시계에서 집어야 같은 축 위의 뺄셈이 된다.
> 덱 차트(`scripts/make_deck_charts.py` 의 `chart_leadtime`)도 같은 정의를 쓴다.
>
> **리드타임은 경보와 같은 게이트웨이 프레임 시계로 잰다.** `deaths.csv` 의 `death_t_est` 는
> 노드 자기 시계의 각인값이라 **사망 순서·영상 동기**에 쓰이며, 두 값의 차이는 스크립트가
> 나란히 출력한다.

> **「참값」이 셋이라는 점에 주의.** 원형 화선에서는 위치마다 법선이 달라 하나의 각도로
> 대표시키는 방법이 여럿이다. 보고서가 쓰는 헤드라인 참값은 **① 점화점 → 판 중심 (55.4826°)**
> 이고, ② 국소 법선 벡터평균은 57.2618°, ③ 전역 단일 평면적합은 54.7696° 다.
> 「판 중심」은 **실측 좌표의 바운딩박스 중심** (0.3030, 0.3015) 이다 — 명목 격자 중심
> (0.3000, 0.3000) 을 쓰면 55.6698° 가 나온다. 경위는 `docs/방향참값_출처_20260830.md`
> 와 `docs/DECISIONS.md` D-073 에 있다. 스크립트가 이 정의를 코드로 고정한다.

수치의 **정본**은 [`docs/실측값_대장.md`](docs/실측값_대장.md) 하나다.
값이 문서마다 다르면 이 대장이 이긴다. **반증된 가설과 실패한 회차도 지우지 않고 남겼다.**

---

## 빌드 — ESP32 노드

| 항목 | 값 |
|---|---|
| 보드 | ESP32 DevKit **WROOM-32** (FQBN `esp32:esp32:esp32`, USB 칩 CP2102) |
| 코어 | `esp32:esp32@3.3.11` |
| 센서 | DS18B20 (1-Wire, 9비트 해상도) |
| 표시 | WS2812 NeoPixel |

```bash
arduino-cli core install esp32:esp32@3.3.11

# ★ 설치 순서가 중요하다. Painless Mesh 를 먼저, ArduinoJson 을 마지막에.
arduino-cli lib install "OneWire" "DallasTemperature" "Adafruit NeoPixel"
arduino-cli lib install "Painless Mesh"      # 공백 포함. painlessMesh 아님
arduino-cli lib install "Async TCP"          # 공백 포함. 구 AsyncTCP 1.1.x 아님
arduino-cli lib install "ArduinoJson@6.21.5" # 7.x 면 StaticJsonDocument 가 없다

# ★ 메시 인증정보 — 커밋되지 않으므로 직접 만든다
cp firmware/node/secrets.h.example firmware/node/secrets.h
#   MESH_PREFIX / MESH_PASSWORD 를 채운다. 없으면 컴파일이 #error 로 중단된다.

# 굽기 (인덱스·역할·임계를 배너로 대조하고 build_log.csv 에 기록)
powershell -File scripts/build_node.ps1 -Upload
```

한글 경로가 GNU 툴체인을 깨뜨리므로 **영문 경로로 복사해 빌드**한다.
설치 함정 4가지와 해결은 [`firmware/BUILD.md`](firmware/BUILD.md).

## 게이트웨이 실행 (실보드)

```bash
python gateway/gateway.py --port auto --fw --emit-dashboard
```

`--port auto` 는 COM 번호를 고정하지 않고 포트를 순회하며 `role=ROOT(bridge)` 인 보드를 찾는다.
못 찾으면 연결된 포트 목록과 함께 **명시적으로 실패**한다.
라즈베리파이 배포 시 필요한 준비(`dialout` 그룹, PEP668 우회 등)는
[`gateway/requirements.txt`](gateway/requirements.txt) 주석에 있다.

---

## 개발 기록

- [`docs/DECISIONS.md`](docs/DECISIONS.md) — 설계 결정 대장 (D-000 ~ D-075). **가설이 반증된 것도 그대로 남긴다.**
- [`docs/실측값_대장.md`](docs/실측값_대장.md) — **이 프로젝트 모든 숫자의 정본**
- [`docs/PROGRESS.md`](docs/PROGRESS.md) — 단계별 진행·측정 결과
- [`results/stress/STRESS_REPORT.md`](results/stress/STRESS_REPORT.md) — 강건성·작동 한계선
- [`results/hw/`](results/hw/) — 실보드 시리얼 캡처 원본

---

## 라이선스

본 저장소는 **GPL-3.0-only** 로 배포됩니다 ([`LICENSE`](LICENSE)).
painlessMesh(GPL-3.0-only)를 링크하기 때문입니다.

| 라이브러리 | 버전 | 라이선스 |
|---|---|---|
| painlessMesh | 1.5.7 | GPL-3.0-only |
| AsyncTCP (ESP32Async) | 3.5.0 | LGPL-3.0 |
| TaskScheduler | 4.0.8 | BSD-3-Clause |
| ArduinoJson | 6.21.5 | MIT |
| OneWire | 2.3.8 | MIT |
| DallasTemperature | 4.0.6 | MIT |
| Adafruit NeoPixel | 1.15.5 | LGPL-3.0 |
| pyserial / NumPy | 3.5 / 2.4.4 | BSD-3-Clause |

MIT · BSD-3-Clause · LGPL-3.0 은 GPL-3.0 과 호환됩니다.
버전·용도 전체는 [`THIRD_PARTY.md`](THIRD_PARTY.md), 라이선스 전문은 [`licenses/`](licenses/) 에 있습니다.

Copyright (C) 2026 팀 화중생련 (Hwajungsaengryeon)
