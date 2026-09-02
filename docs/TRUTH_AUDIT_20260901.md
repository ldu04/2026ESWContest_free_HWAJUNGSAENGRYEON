# TRUTH CONSISTENCY AUDIT — 2026-09-01

범위: firmware · gateway · dashboard · scripts · tools · tests · sim · docs · 생성물
자동화: `tools/check_truth.py` (신설). 검사 25건 중 **실패 3건 (P0 2 · P1 1)**.

> **감사 원칙대로 코드는 고치지 않았다.** 아래 P0/P1 은 전부 **보고만** 한 것이다.
> 단, 이 감사를 지시받기 **전에** 이미 고친 것이 2건 있다(§적용된 변경).

---

## P0 — 실행 결과를 바꿀 수 있는 충돌

### P0-1. `preflight.py` 의 하트비트 주기가 1초 (실제 10초) — **정상 런을 불합격 처리한다**

| | |
|---|---|
| concept | heartbeat period |
| current (정본) | **10000 ms** — `firmware/node/config.h:98` |
| conflicting | **1.0 s** — `tools/preflight.py:231` `exp = seconds / 1.0` |
| why same concept | 둘 다 「노드가 하트비트를 몇 초마다 보내는가」다. preflight 는 이 값으로 관측창의 **기대 개수**를 만들고 도착률을 낸다 |
| execution path | **런 직전 go/no-go 점검.** `preflight.py:239` `add(lo >= 60.0, ...)` 가 불합격을 낸다 |
| affected behavior | 기대 개수가 **10배 과다** → 도착률이 **10배 낮게** 계산된다. 도착률 100 % 인 완벽한 메시가 **10 %** 로 찍혀 60 % 문턱에 걸린다. **정상 판을 불합격으로 세운다** |
| recommended fix | `exp = seconds / (HEARTBEAT_MS/1000)` 으로 정본에서 읽기. 상수 복제를 없앤다 |

> 같은 자리에서 이미 한 번 당했다 — 주석에 「2026-09-01 에 이걸 5초로 잘못 알고 도착률을
> 5배 부풀려 계산한 적이 있다」고 적혀 있다. 그 수정이 **결정 (가′)의 1000→10000 을 예상하지
> 못했다.** 값을 복제하는 한 같은 사고가 반복된다.

### P0-2. `preflight.py` 의 `V_EXPECT` 가 옛 v — **정상 설정을 불합격 처리한다**

| | |
|---|---|
| concept | front speed `v_front_expected` |
| current (정본) | **0.000579 m/s** — `gateway/deploy_config.json` (D-075) |
| conflicting | **0.000523** — `tools/preflight.py:35` `V_EXPECT = 0.000523` (D-074) |
| execution path | `preflight.py:70` 이 설정 파일 값과 비교해 불합격 판정 |
| affected behavior | 현재 설정이 **정답인데 "기대 0.000523" 으로 불합격**이 뜬다 |
| recommended fix | `V_EXPECT` 를 없애고 설정 파일을 정본으로 삼되, **"오늘 이 값으로 돌린다"는 확인**이 목적이면 CLI 인자로 받는다 |

---

## P1 — 테스트/검산/분석을 오염시키는 충돌

### P1-1. `scripts/night_robustness.py` 가 **D-069 시대 v** 를 하드코딩

- current: `0.000579` / conflicting: `V_FRONT = 0.00061` (`night_robustness.py:39`, 두 세대 전)
- 파생값도 같이 굳어 있다: `DT_WINDOW = 590.2 s` · `ALERT_HORIZON = 327.9 s` (주석)
- 실행 경로: 런에는 안 들어간다. **그러나 보고서용 강건성 분석을 지금 다시 돌리면
  현재 대본과 다른 규모의 숫자가 나온다** — 제출물 안에서 숫자가 어긋난다
- fix: `deploy_config.json` 에서 읽도록

### P1-2. `docs/촬영_타임라인.md` — **옛 대본이 "할 일 체크박스" 형태로 살아 있다**

- `체류 18초 고정`(§3 제목) · `n07→n09 의 14초` · `체류 18초로 t80 을 넘기는가`
- 전부 **D-069 시대**(현재: 체류 21초 · n07→n09 **7.0초**)
- 역사 서술이 아니라 **`- [ ]` 미완료 체크박스**라서 현장에서 그대로 수행될 수 있다
- `check_values.py` 의 RUNTIME_DOCS 3종에 **포함돼 있지 않아** 검사도 안 된다
- fix: 문서 상단에 「D-069 시대 기록」 명시 또는 현재 값으로 갱신

### P1-3. `dashboard/data.js` (24.5 MB) 안에 옛 참값이 박제

- `speed_true: 0.000523` · `alert_horizon: 382.4091778202677`
- 중단·시각오염된 01:12 회차 산출물이다(`docs/아침보고서.md` 에 기록)
- 런 때 새로 생성되지만, **그 전에 대시보드를 열면 옛 회차가 현재처럼 보인다**
- fix: 런 전에 지우거나, 대시보드에 생성 시각·v 를 표시

---

## P2 — 역사 기록으로 남은 옛값 (실행 영향 없음)

| 위치 | 옛값 | 판정 |
|---|---|---|
| `sim/config.py` `heartbeat_period=1.0` · `silence_timeout=3.0` | 시뮬 규모 | **정상** — 실물 경로는 `_derive_scale()` 이 `dt_window`/`alert_horizon` 만 덮어쓰고 이 둘은 쓰지 않는다. 실물 진입점 `confirm_external()` 은 `death_t_est` 를 인자로 직접 받는다 |
| `sim/config.py` `dtdt_window_s=3.0` (주석 「heartbeat 1s → 3~4 표본」) | 주석이 옛 전제 | `dtdt_gate=False` 라 실물에서 미사용. **주석만 오해 소지** |
| `docs/체류변경_대응계산_20260831.md` `0.610 (현행)` | D-069 | 8/31 의사결정 문서. 다만 "현행" 딱지는 이제 틀림 |
| `docs/DECISIONS.md` 외 이력 문서 다수 | D-069/D-074 | 의사결정 이력이므로 보존이 맞다 |
| `gateway/gateway.py:83` 주석의 옛 v | — | 주석 |

---

## Missing propagation — 정본이 바뀌었는데 안 따라간 곳

| 정본 변경 | 따라가야 할 곳 | 상태 |
|---|---|---|
| `HEARTBEAT_MS` 1000 → **10000** (가′) | `gateway.py HEARTBEAT_S_EXPECTED` | ✅ 따라감 (10.0) |
| 〃 | `SILENCE_TIMEOUT_MS` (=3×HB) | ✅ 30000 |
| 〃 | **`preflight.py` 도착률 나눗수** | ❌ **P0-1** |
| 〃 | `preflight.py` 「임종신호 1회」 근거 주석 | ❌ 이제 3회(`LAST_GASP_REPEATS=3`) — 유실확률 식이 `1−(1−p)³` 로 바뀌었다 |
| 〃 | `check_values.py` 정본표 | ✅ (오늘 수정, §적용된 변경) |
| `v` 0.000523 → **0.000579** (D-075) | `dt_window`·`alert_horizon` | ✅ 자동 유도 |
| 〃 | `run_cue.py` | ✅ 설정에서 읽음 |
| 〃 | `D1_리허설_절차서.md` §1-B·§4-6 | ✅ (오늘 수정) |
| 〃 | `docs/실측값_대장.md` §2 정본표 | ✅ (오늘 수정, §적용된 변경) |
| 〃 | **`preflight.py V_EXPECT`** | ❌ **P0-2** |
| 〃 | **`night_robustness.py V_FRONT`** | ❌ **P1-1** |
| 〃 | `residual_gate_s` | ⚠ **근사만 적용**(69.1×0.523/0.579=62.4). 실측 재도출 미완 |

---

## Invariant violations

검사한 불변식 — **위반 0건**:

    silence_timeout = 3 × heartbeat          ✅ 30000 = 3×10000
    warn_temp = 0.75 × temp_threshold        ✅ 60.0 = 0.75×80.0
    temp_threshold = 80.0 (헌장 §1 동결)      ✅
    node ids = 0..15 연속 · 16개              ✅
    bridge id ∉ node ids                     ✅ 99
    bridge id: firmware ↔ deploy_config      ✅ 99 = 99
    grid = 4×4                               ✅
    K_confirm: firmware ↔ sim                ✅ 3 = 3
    last_gasp_delay: firmware ↔ sim          ✅ 0.3s = 0.3s
    체류: run_cue ↔ route_table ↔ preflight   ✅ 21 = 21 = 21
    ORIGIN 3개 스크립트                        ✅ (0.02, −0.11)

⚠ **불변식은 아니지만 기록해 둘 것** — `route_table.py:35 UPTIME_WARN_MIN = 40.0` 과
`preflight.py:36 UPTIME_LIMIT_S = 40*60` 은 **71.6분 랩어라운드**를 근거로 한 값이다.
그러나 `docs/실측값_대장.md:90` 은 **브리지 크래시를 24.5분에 실측**했고 「40분 규칙만으로는
부족하다」고 적어 두었다. 두 도구 모두 그 발견을 반영하지 않았다.
다만 그 24.5분은 **구 펌웨어(1 Hz, 15 msg/s 부하)** 관측이고 현재는 1.5 msg/s 라
**같은 문턱이 유효한지 미검증**이다 — 추측으로 값을 바꾸지 않고 그대로 둔다.

---

## Truth inventory — 현재 참값

| concept | value | unit | authoritative source | decision | derived-from | status |
|---|---|---|---|---|---|---|
| death threshold | 80.0 | ℃ | `config.h:68` | 헌장 §1 | — | **frozen** |
| warn threshold | 60.0 | ℃ | `config.h:82` | — | `0.75 × death` | derived |
| heartbeat period | 10000 | ms | `config.h:98` | 가′ | — | current |
| silence timeout | 30000 | ms | `config.h:106` | 가′ | `3 × heartbeat` | derived |
| last-gasp delay | 300 | ms | `config.h:87` | — | — | current |
| last-gasp repeats | 3 | 회 | `config.h:113` | 가′ | — | current |
| last-gasp gap | 1000 | ms | `config.h:114` | 가′ | — | current |
| K confirmation | 3 | 개 | `config.h:115` | — | — | current |
| sense period | 500 | ms | `config.h:116` | — | — | current |
| node count | 16 | 개 | `deploy_config.json` | — | — | frozen |
| node ID mapping | nXX → XX−1 | — | `deploy_config.json` `_doc` | 2026-08-26 | — | frozen |
| bridge ID | 99 | — | `config.h:13` + `deploy_config` | — | — | frozen |
| coordinates | 실측 16점 | m | `deploy_config.json` | `measured:true` | 자로 잼 | frozen |
| grid | 4×4 | — | `deploy_config.json` | — | — | frozen |
| spacing | 0.20 | m | `deploy_config.json` | 2026-08-17 | 살상반경 1.75cm | frozen |
| radio_range | 0.36 | m | `deploy_config.json` | — | `spacing × 1.8` | derived |
| **front speed** | **0.000579** | m/s | `deploy_config.json` | **D-075** | 이동여유 7초 역산 | **current** |
| dwell | 21 | s | `run_cue.py` + `route_table.py` | D-074 | `round(1.7×t80)` | current |
| dt_window | 621.8 | s | (유도) | — | `radio/v` | derived |
| alert_horizon | 345.4 | s | (유도) | — | `spacing/v` | derived |
| residual gate | 62.4 | s | `deploy_config.json` | D-075 | ⚠ **1/v 근사** | **experimental** |
| 총 런 | 23:19 (1399) | s | `route_table.py --solve 7` | D-075 | 동선표 | current |
| n07→n09 이동여유 | 7.0 | s | 동선표 | D-075 | 이동 실측 floor | current |
| t80 중앙값 | 12.49 | s | `docs/실측값_대장.md` | D-074 | 실측 | frozen |

---

## Recommended automation

| 검사 대상 | authoritative source | expected | 검사 위치 | 자동화 |
|---|---|---|---|---|
| 하트비트 전파 | `config.h HEARTBEAT_MS` | `HB/1000` | `gateway.py`, `preflight.py` | ✅ **구현됨** |
| v 전파 | `deploy_config.json` | 그 값 | `preflight.py`, `night_robustness.py` | ✅ **구현됨** |
| 파생값 | v · radio · spacing | `radio/v`, `spacing/v` | 문서 사본 | ✅ **구현됨** |
| 체류 3중 복제 | — | 3곳 동일 | `run_cue`/`route_table`/`preflight` | ✅ **구현됨** |
| ORIGIN 3중 복제 | — | 3곳 동일 | 스크립트 3종 | ✅ **구현됨** |
| 정본표 메타검사 | 실제 정본 | 일치 | `check_values.py RULES` | ✅ **구현됨** |
| 불변식 9종 | — | — | 전역 | ✅ **구현됨** |
| 파이 ↔ 노트북 판 일치 | 노트북 저장소 | md5 동일 | 파이 `~/failsafe-mesh` | ⬜ 미구현(파이 접속 필요) |
| 생성물 신선도 | 런 시작 시각 | 이후 생성 | `dashboard/data.js` | ⬜ 미구현 |

    python tools/check_truth.py          # P0/P1 있으면 종료코드 1
    python tools/check_truth.py --all    # 전체 25건 출력

---

## 적용된 변경 (이 감사 지시 **이전**에 수행)

1. `docs/실측값_대장.md` §2 — 정본표가 D-074(v=0.523) 였다. D-075 로 갱신하고 옛값 열을 남겼다.
2. `tools/check_values.py` `RULES` — 정본이 `0.000523` 과 **`1000 ms`** 였다.
   즉 「옛 값 검사기」가 옛 값을 들고 있어 통과해도 보장이 없었다. 정본을 현재로 맞췄다.

이 감사에서 발견한 P0-1 · P0-2 · P1-1 · P1-2 · P1-3 은 **고치지 않았다.**

---

TRUTH AUDIT STATUS: **FAIL**  (P0 2건 · P1 3건)
