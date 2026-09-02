# gateway/ — 라즈베리파이 게이트웨이 (지시서 #4, Phase A)

루트 ESP32가 USB 시리얼로 보내는 JSON 라인을 받아, **시뮬 `sim/estimator.py`를 그대로 재사용**해
도착시각→방향·속도·ETA·경보를 산출하고, 지시서 #3과 **동일한 Snapshot(dict)** 을 만들어 대시보드에 먹인다.
이게 포팅의 최대 이득 — 추정 알고리즘은 이미 #1·#2·#2b에서 검증됐으므로 **코드째 재사용**. [D-024]

```
gateway/
├── serial_source.py    # 라인 소스 추상화(파일/stdin/mock/실 pyserial 공통)
├── mock_serial.py      # 시뮬 engine으로 '게이트웨이 방언' 스트림 생성(어댑터 우회)
├── mock_fw_serial.py   # ★ 'node.ino 방언' 합성 스트림 생성(어댑터 검증용)  [2.K §2]
├── fw_adapter.py       # ★ 펌웨어 방언 → 게이트웨이 방언 변환 계층        [D-049]
├── deploy_config.json  # ★ 노드 좌표 정본(우리가 물리 배치한 격자)          [제약②]
└── gateway.py          # 시리얼 → estimator 재사용 → Snapshot → dashboard/data.js
```

## ★ 두 방언 (헷갈리면 프레임이 0개가 된다)

| | 타입 |
|---|---|
| `gateway.py`가 **소비** | `META NODES DC ROUTE GT STATS TICK` |
| `node.ino`가 **송신** | `MODE ROOT_READY ST HB LG DV DC` |

**교집합이 `DC` 하나뿐**이라 실보드를 그냥 물리면 `META`가 없어 `cfg=None`, `TICK`이 없어 **프레임 0개**다.
그래서 실보드 입력에는 반드시 **`--fw`**(어댑터)를 붙인다. [D-046 → D-049]

## end-to-end (하드웨어 없이, Phase A DoD 2)
```bash
# 1) 모의 시리얼 스트림 생성
python gateway/mock_serial.py                 # → results/dashboard/mock_stream.jsonl

# 2) 게이트웨이: 스트림 → estimator 재사용 → 대시보드 데이터
python gateway/gateway.py --in results/dashboard/mock_stream.jsonl --emit-dashboard
#   → results/dashboard/gateway_data.js (window.SNAPSHOTS, #3 플레이어 스키마 동일)

# 3) 재생: dashboard/data.js 를 gateway_data.js 로 바꿔 index.html 열면 그대로 재생됨
#    (또는 한 줄 파이프: python gateway/mock_serial.py --out - | python gateway/gateway.py --in - --emit-dashboard)
```

**검증됨:** 게이트웨이가 시리얼 스트림만 보고 재구성한 최종 추정(방향 2.115°, 속도 0.096%)이
시뮬 engine 직접값과 **완전히 일치** → estimator 재사용 파이프라인 정상.

## ★ end-to-end · **펌웨어 방언** 경로 (보드 없이, 어댑터 포함) [2.K §2]
```bash
# 1) node.ino 방언 합성 스트림 (fake=1 = 합성 표시가 박힌다)
python gateway/mock_fw_serial.py --fake 1     # → results/dashboard/mock_fw_stream.jsonl

# 2) 어댑터를 거쳐 게이트웨이로
python gateway/gateway.py --in results/dashboard/mock_fw_stream.jsonl --fw --emit-dashboard
#   → 프레임 92개 · 확정사망 12 · results/dashboard/gateway_deaths.csv (★ fake 컬럼)
```
**검증됨(배관만):** 펌웨어 474줄 → 게이트웨이 289줄 → **프레임 92개**, `fake=1`이 **12/12건 CSV까지 도달**.
> ⚠ `mock_fw_serial.py`의 온도 모델은 벤치 격자용 단순 선형 전선이다. 여기서 나오는 방향·속도 수치는
> **자기가 만든 전선을 자기가 맞힌 동어반복**이므로 **성능 근거로 인용 금지**. 성능은 `sim/`이 낸다.

## 실물(Phase B~, 부품 도착 후)
```bash
pip install pyserial
python gateway/gateway.py --port COM5 --fw --emit-dashboard   # ★ --fw 필수(펌웨어 방언)
```
**배치를 바꾸면 `deploy_config.json`만 고친다** — 실물 좌표는 펌웨어가 아는 값이 아니라
**우리가 자로 재서 놓은 값**이고, 이 파일이 없으면 방향 추정 자체가 불가능하다.
실물엔 ground-truth 전선이 없으므로 대시보드는 참전선(빨강 점선)을 생략하고 추정만 표시
(app.js가 `fire_front` 없을 때 자동 guard). HUD 방향/속도 오차도 참값이 없어 표시 안 함(정직).

## 시리얼 라인 스키마(루트 ESP32 → 파이)
`META`(설정·노드 좌표) → 이후 매 틱 `NODES`(상태·온도) · `DC`(확정 사망) · `ROUTE`(자가치유 트리) ·
`STATS`(전달률) · (`GT`는 모의 전용) · `TICK`(경계). 자세한 건 `mock_serial.py` 상단 주석.
