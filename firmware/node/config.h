// config.h — 시뮬(sim/config.py) 파라미터를 펌웨어로 계승 [DECISIONS D-023]
// 노드별 값(ID/좌표/루트여부)은 플래시 시 빌드 플래그(-DNODE_ID=..)로 주입.
// 빌드 플래그가 없으면 아래 기본값 사용(Wokwi 단일보드 테스트용).
#pragma once

// ---- 노드 식별·좌표 (플래시 시 주입) ----
// ★ [2026-08-27] 브리지 예약 번호. 격자 노드 id 는 deploy_config.json 에서 **0..15** 이므로
//   브리지가 0 을 쓰면 격자점 (0.00, 0.00) 노드와 **같은 번호**가 된다.
//   그러면 브리지의 자기 HB/ST/LG 가 격자 노드 0 의 것으로 해석되어
//   좌표 (0,0) 이 붙고, 브리지 온도가 노드 0 의 rep_peak 을 오염시키며,
//   최악의 경우 브리지가 40℃를 넘으면 (0,0) 에 **유령 사망**이 찍힌다.
//   그래서 브리지는 0..15 밖의 예약 번호를 쓴다.
#define BRIDGE_INDEX 99
// ★ [2026-08-31] NODE_ID 는 **생성 헤더 node_id.h** 로 넘긴다. -D 플래그로 주지 않는다.
//   이유(실측): `compiler.cpp.extra_flags` 는 **모든 컴파일 단위**에 붙는다. 그래서 보드마다
//   NODE_ID 만 달라도 painlessMesh·AsyncTCP·ArduinoJson 까지 전부 다시 컴파일된다.
//   n03 굽기 실측 — compile+upload **616.8초** (포트대기 0.2 / read-mac 2.5 / 배너검증 4.7).
//   헤더로 넘기면 바뀌는 건 스케치 한 파일이라 라이브러리 오브젝트가 빌드 캐시에 남는다.
//
//   node_id.h 는 굽기 직전에 flash_node.ps1 이 한 줄로 만든다:  #define NODE_ID 5
//   ★ 생성이 실패하면 **컴파일이 그냥 통과하면 안 된다.** 옛 헤더가 남아 있으면 엉뚱한 id 로
//     구워지고, 그건 8/30 오굽기 사고와 같은 종류다. 없으면 #error 로 멈춘다.
#if defined(__has_include)
  #if __has_include("node_id.h")
    #include "node_id.h"
  #endif
#endif
#ifndef NODE_ID
  #error "NODE_ID 가 정의되지 않았다. firmware/node/node_id.h 를 생성하거나 -DNODE_ID 로 줄 것."
#endif
#ifndef NODE_X
#define NODE_X    30.0f    // 미터 (격자 좌표)
#endif
#ifndef NODE_Y
#define NODE_Y    30.0f
#endif
// ★★ BRIDGE_INDEX 와 반드시 같이 바뀌어야 하는 곳.
//   예전엔 (NODE_ID == 0) 이었다. 브리지 번호만 99 로 바꾸고 이 줄을 안 고치면
//   **브리지가 루트가 아니게 되어 시리얼 중계가 통째로 멈춘다**(게이트웨이 입력 0줄).
//   침묵으로 실패하는 종류라 반드시 함께 본다.
#ifndef NODE_IS_ROOT
#define NODE_IS_ROOT (NODE_ID == BRIDGE_INDEX)
#endif

// ---- 시뮬 계승 파라미터 (sim/config.py) ----
// ┌──────────────────────────────────────────────────────────────────┐
// │ ★★ 사망 임계 — 소스 기본값은 **항상 80.0f** 다. 여기에 임시값을    │
// │   박지 말 것. 박으면 반드시 잊고 그대로 데모에 간다.               │
// │                                                                  │
// │   시험용 낮은 임계는 **빌드 플래그로만** 준다:                     │
// │     -DTEMP_THRESHOLD_C=40.0f     (또는 -DDEATH_THRESHOLD_C=40.0f) │
// │                                                                  │
// │   40.0 은 손으로 센서를 감싸면 넘는 값이라 열풍기 없이 사망 경로를  │
// │   시험할 때 쓴다(열풍기는 데모 지오메트리로 영구 고정돼 있다).      │
// │                                                                  │
// │   되돌림 확인 = 부팅 배너의 death_threshold_c 값.                  │
// │   flash_node.ps1 이 "플래그 없이 구웠는데 80.0 이 아니면 FAIL" 로   │
// │   자동 판정한다 — 눈으로 기억하지 않아도 된다.                      │
// └──────────────────────────────────────────────────────────────────┘
// 두 이름을 모두 받는다. 코드가 쓰는 이름은 TEMP_THRESHOLD_C 지만,
// -DDEATH_THRESHOLD_C 로 줘도 조용히 무시되지 않게 여기서 이어 붙인다.
#ifdef DEATH_THRESHOLD_C
  #ifndef TEMP_THRESHOLD_C
    #define TEMP_THRESHOLD_C DEATH_THRESHOLD_C
  #endif
#endif
#ifndef TEMP_THRESHOLD_C
#define TEMP_THRESHOLD_C   80.0f    // temp_threshold: ALIVE→DYING (기본값 — 바꾸지 말 것)
#endif
// ★ [2026-08-30] WARN_TEMP_C 는 TEMP_THRESHOLD_C 를 따라가야 한다. 고정값이면 조용히 죽는다.
//   발견 경위 — (d) 실물 사망시험을 돌리기 직전 정적 점검에서 잡았다. 시험을 돌렸으면
//   "아무 일도 안 일어남" 으로만 보였을 것이다.
//   사고 구조: -DTEMP_THRESHOLD_C=40.0f 로 구우면 노드는 40℃에서 DYING → (300ms) → DEAD 가
//   되어 송신을 끊는다. 따라서 **이웃이 관측할 수 있는 온도의 상한은 40℃ 근처**다.
//   그런데 사망 투표 조건(node.ino 의 교차검증)은 peakTemp >= WARN_TEMP_C(=60) 였다.
//   → 투표가 영원히 안 나오고 K_CONFIRM(3)도 영원히 안 차서 **DC 가 구조적으로 불가능**했다.
//   게이트웨이가 소비하는 유일한 타입이 DC 이므로 화면에는 아무 징후도 안 뜬다 — 침묵 실패.
//   불변식: WARN_TEMP_C < TEMP_THRESHOLD_C. 아래 static_assert 로 컴파일 때 강제한다.
//   비율은 원설계(60/80 = 0.75)를 그대로 쓴다 — 새 상수를 만들지 않는다.
//   기본값 80.0f 에서는 0.75*80 = 60.0f 로 종전과 완전히 같다.
#ifndef WARN_TEMP_C
#define WARN_TEMP_C        (TEMP_THRESHOLD_C * 0.75f)   // warn_temp: 사망 교차검증 온도 근거
#endif
static_assert(WARN_TEMP_C < TEMP_THRESHOLD_C,
  "WARN_TEMP_C >= TEMP_THRESHOLD_C: 죽은 노드는 임계 온도 이상을 방송하지 못하므로 "
  "사망 투표가 영원히 성립하지 않는다. 임계값을 낮췄으면 WARN 도 같이 낮춰야 한다.");
#define LAST_GASP_DELAY_MS 300      // last_gasp_delay 0.3s

// ★★ [2026-09-01, 결정 (가′)] 하트비트를 1초 → 10초로 늦춘다.
//
//   왜: 브리지가 내보내는 노드 메시지가 **초당 약 1.3개**다(2시간 소크 실측).
//   노드 15대가 1 Hz 로 보내면 15개/초라 11배 초과공급이고, 그 결과
//     · 노드 하트비트 도착률이 **7.3%** 로 내려앉았고
//     · **단발인 임종신호가 91% 유실**됐다 — n07 실사망 시험이 그래서 실패했다
//     · 브리지 힙이 마르며 33분에 **2회 크래시**했다(uptime 42.8분 · 24.5분)
//   10초면 노드 송신이 1.6개/초라 처리량 안으로 들어온다. 계산상 도착률 87%.
//   근거·계산: docs/n07_사망시험_판정_20260901.md
#define HEARTBEAT_MS       10000    // heartbeat_period 10.0s

// ★★ 반드시 HEARTBEAT_MS 와 함께 움직인다. 이 값의 뜻은 **하트비트 3회분**이다.
//   3000 을 그대로 두면 하트비트 0.3회분이 되어, 살아 있는 노드가 하트비트를 한 번
//   놓칠 때마다 이웃이 **사망 투표를 던진다**(node.ino:453 `silent`).
//   대가: 침묵 기반 사망 감지가 3초 → 30초로 늦어진다. 예비 경로이므로 감수한다
//   (주 경로인 임종신호가 이 수정으로 살아난다). 사망 **순서**는 임종신호가 정하므로
//   30초 지연이 대본의 최소 사망 간격 20초(n14)를 뒤집지 않는다.
#define SILENCE_TIMEOUT_MS 30000    // silence_timeout 30.0s (= 3 x HEARTBEAT_MS)

// ★★ 임종신호 반복. 단발이면 「도착률 = 도달 확률」이라 87%에서도 13%를 잃는다.
//   3회면 계산상 유실 0.2%. 간격을 1초로 벌린 이유: 병목이 「가득 찬 큐」이면
//   짧은 간격의 반복은 **같이 버려진다.** 벌려야 상관이 줄어든다.
//   사망 시각은 **첫 각인을 그대로 들고 가므로** 반복해도 늦어지지 않는다
//   (node.ino sendLastGasp 참조 — 각인은 한 번, 전송은 여러 번).
#define LAST_GASP_REPEATS  3        // 총 전송 횟수(첫 1회 포함)
#define LAST_GASP_GAP_MS   1000     // 반복 간격
#define K_CONFIRM          3        // 사망확정 최소 관측 이웃 수
#define SENSE_MS           500      // 온도 샘플 주기

// ---- 메시(painlessMesh) — 인증정보는 secrets.h 로 분리 ----
// ★ 소스에 비밀번호를 박아두지 않는다. 저장소를 Public 으로 공개하면 같이 공개되고,
//   누구나 같은 SSID/비번으로 메시에 끼어들어 **가짜 사망 패킷**을 넣을 수 있다.
//   "결선 전에 바꾸자"는 반드시 잊히므로 구조로 막는다.
//   secrets.h 는 .gitignore 에 있고, secrets.h.example 을 복사해서 만든다.
#if defined(__has_include)
  #if __has_include("secrets.h")
    #include "secrets.h"
  #endif
#endif
#ifndef MESH_PASSWORD
  #error "secrets.h 가 없다. firmware/node/secrets.h.example 을 복사해 secrets.h 로 만들 것."
#endif

// ---- 핀 배치 (Wokwi diagram.json과 일치) ----
#define PIN_ONEWIRE  4     // DS18B20 데이터

// ★ [2026-08-31] WS2812 데이터 핀은 **빌드 플래그로 덮어쓸 수 있다.** 기본값은 5 그대로다.
//   왜: n04(NODE_ID 3)가 GPIO5 로는 LED 가 안 켜진다. 전원·펌웨어·굽기를 전부 배제했고
//   정상 LED 조립품으로 바꿔도 재현됐다(→ GPIO5 자체 불량 의심). 그 한 대만
//   `-DPIN_NEOPIXEL=18` 로 구워 살린다. **나머지 15대는 플래그 없이 구우면 5 그대로다.**
//   실제로 어느 핀으로 구워졌는지는 부팅 배너의 `led_pin` 으로 확인한다.
#ifndef PIN_NEOPIXEL
#define PIN_NEOPIXEL 5     // WS2812 데이터 (기본)
#endif

// ---- Wokwi/데스크 테스트: 실 센서 없이 온도 램프 주입 ----
// 실물에서는 0으로. Wokwi에서 1로 두면 t축을 따라 온도가 상승해 Last-Gasp까지 시연.
// ★ [D-063] 기본값 **0**(실센서). 제출물 경로에 합성 데이터가 들어갈 여지를 기본값으로 막는다.
//   D-046 안전장치(보라 LED·경고 배너·모든 줄의 fake=1)는 1로 켰을 때 여전히 작동한다.
//   Wokwi/데스크 시연에서 필요하면 빌드 플래그로 -DFAKE_TEMP_RAMP=1 을 준다.
#ifndef FAKE_TEMP_RAMP
#define FAKE_TEMP_RAMP 0
#endif
#define FAKE_RAMP_START_MS 4000     // 이 시각부터
#define FAKE_RAMP_DEG_PER_S 12.0f   // 초당 상승(℃) → ~7s 후 80℃ 돌파
