/*
 * node.ino — failsafe-mesh ESP32 노드 펌웨어 (지시서 #4, Phase A)
 * 시뮬(sim/)의 node·network·verification 로직을 실물로 이식.
 *
 * 모듈(시뮬 대응):
 *   1) 하트비트/센싱  : 주기적으로 {id,x,y,temp,t} 브로드캐스트          (sim/node.py)
 *   2) Last-Gasp      : temp>=80℃ → 임종 패킷 1회 후 송신 중단           (sim/node.py)
 *   3) 교차검증        : 이웃 침묵(>silence_timeout)+고온 관측 → DEATH_VOTE (sim/verification.py)
 *   4) 루트 집계       : 서로 다른 관측자 K명 이상 → DEATH_CONFIRM → 시리얼  (sim/verification.py)
 *   5) LED            : ALIVE=초록 / DYING·DEAD=빨강
 *   자가치유 라우팅    : painlessMesh가 자동 우회(그 위에 죽음=1급 이벤트 계층)
 *
 * 의존 라이브러리(Arduino Library Manager): painlessMesh, ArduinoJson,
 *   OneWire, DallasTemperature, Adafruit NeoPixel.
 * 파라미터/핀: config.h. 노드별 ID/좌표는 빌드 플래그로 주입(flash_all.py).
 */
#include "config.h"
#include <Arduino.h>
#include <painlessMesh.h>
#include <ArduinoJson.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_NeoPixel.h>

// ─────────────────────────────────────────────────────────────
// ★ [2026-08-30] 메시 JSON 문서 용량 — **송·수신을 한 곳에서 정의한다**
//
// 이번 사고의 뿌리: 송신은 StaticJsonDocument<256>(HB/LG/DV/DC)·<160>(ST) 인데
// 수신 onReceive 만 <200> 이었다. 둘이 서로를 모르고 있었다.
// 256으로 만든 패킷을 200으로 파싱하니 deserializeJson 이 NoMemory 를 돌려주고
// **조용히 return** 했다 — 메시는 멀쩡히 붙어 있고 오류도 안 나는데
// 이웃 패킷이 전부 버려졌다. 임종신호 수신·투표 경로가 통째로 죽어 있었다.
//
// 용량 근거 (ArduinoJson v6, ESP32 32-bit):
//   가장 큰 패킷은 DC — 키 11개(type,id,x,y,death_t_est,t_source,nt,
//   last_temp,rep_peak,had_last_gasp,fake).
//   JSON_OBJECT_SIZE(11) = 8 + 11×16 = 184 B
//   + 문자열 복사분(t_source "last_gasp_node_stamp" 등) 약 60 B
//   = 약 250 B. 여기에 **2배 여유**를 둬 512 로 잡는다.
//   (RAM 사용률 14 % 라 여유가 충분하고, 필드가 늘어도 다시 안 터진다)
//
// ※ 송신과 수신에 **같은 상수**를 쓴다. 한쪽만 바꾸는 일이 다시 없게.
#define MESH_JSON_CAPACITY 512

enum NodeState { ALIVE, DYING, DEAD };

Scheduler        userScheduler;
painlessMesh     mesh;
OneWire          oneWire(PIN_ONEWIRE);
DallasTemperature sensors(&oneWire);
Adafruit_NeoPixel led(1, PIN_NEOPIXEL, NEO_GRB + NEO_KHZ800);

NodeState state = ALIVE;
float    curTemp = 25.0f;
float    lastTemp = 25.0f;
uint32_t dyingAtMs = 0;
bool     lastGaspSent = false;

// ★ [2026-09-01] 임종신호 재송 상태.
//   payload 를 **완성된 문자열로 굳혀** 둔다. 다시 직렬화하면 sendJson() 이 nt 를
//   새로 찍어(node.ino sendJson 참조) 사본마다 사망 시각이 달라진다. 그러면 게이트웨이가
//   3번째 사본을 먼저 받았을 때 사망 시각이 그만큼 늦게 기록된다. **각인은 한 번.**
String   lgPayload;
uint8_t  lgSendsLeft = 0;
uint32_t lgNextMs    = 0;

// ★ [2026-09-01] WARN(60℃) 을 처음 넘을 때 하트비트를 한 번 강제로 쏘았는지.
//   HB 10초 주기에서 60~80℃ 구간(실측 4.5~7.0초)에 하트비트가 안 들어가는 것을 막는다.
bool     warnAnnounced = false;

// 이웃 관측 테이블(교차검증용): id -> {마지막 수신 ms, 마지막 온도}
// [2.M P1] peakTemp 추가 — 시뮬 verification의 `rep_peak`과 같은 뜻.
//   노드가 죽으면 보고가 끊겨 lastTemp가 임계 근처에 고정되므로, **최고값**이 열 이력을 더 잘 담는다.
struct Neigh { uint32_t lastHeard; float lastTemp; float peakTemp; bool voted; };
#include <map>
std::map<int, Neigh> neigh;

// 루트 전용: suspect -> 관측자 집합(중복 제거해 K 집계)
#include <set>
std::map<int, std::set<int>> votes;
std::set<int> confirmed;

// ---- 온도 읽기(실 센서 또는 Wokwi 램프) ----
float readTemp() {
#if FAKE_TEMP_RAMP
  uint32_t now = millis();
  if (now < FAKE_RAMP_START_MS) return 25.0f;
  return 25.0f + FAKE_RAMP_DEG_PER_S * (now - FAKE_RAMP_START_MS) / 1000.0f;
#else
  sensors.requestTemperatures();
  float t = sensors.getTempCByIndex(0);
  return (t <= -100.0f) ? lastTemp : t;   // 읽기 실패 시 직전값 유지
#endif
}

// ---- 합성 데이터 안전장치 [D-046] ----
// FAKE_TEMP_RAMP=1이면 센서를 무시하고 펌웨어가 만든 가짜 온도를 펌웨어가 다시 읽는다.
// 그 상태의 로그가 실측으로 오인되는 사고를 막기 위해, **모든 송신 줄에** fake=1을 박는다.
// 배너는 로그 앞부분이 잘리면 사라지지만, 줄마다 붙는 필드는 영구히 남는다.
#if FAKE_TEMP_RAMP
  #define FAKE_FLAG 1
#else
  #define FAKE_FLAG 0
#endif

const char* stateName() {
  return (state == ALIVE) ? "ALIVE" : (state == DYING ? "DYING" : "DEAD");
}

// ---- 노드 각인 시각 [2.K §2 제약③] ----
// 왜 millis()가 아니라 mesh.getNodeTime()인가:
//   millis()는 **보드마다 부팅 시점이 달라** 노드 간 비교가 성립하지 않는다. 도착시각장
//   T(x,y)는 서로 다른 노드의 시각을 **같은 축 위에서** 빼는 연산이므로, 로컬 millis를 쓰면
//   ∇T가 곧바로 망가진다(= 방향 추정이 깨진다). painlessMesh의 getNodeTime()은 메시 전체가
//   동기화한 시각이라 이 비교가 성립한다. 게이트웨이 수신 시각을 쓰면 통신 지연이 같은 자리를
//   오염시키므로 그것도 금지다(H0 이래의 규약).
// ⚠ 한계: getNodeTime()은 uint32 마이크로초라 **약 71.6분마다 랩어라운드**한다. 그보다 긴
//   연속 운용에서는 랩 처리(상위 비트 카운터)가 필요하다. 현재 데모 길이에서는 발생하지 않는다.
double nodeTimeSec() {
  return (double)mesh.getNodeTime() / 1000000.0;
}

// ---- 송신 도우미 ----
void sendJson(JsonDocument& doc) {
  doc["fake"] = FAKE_FLAG;                   // ★ 모든 줄에 합성/실측 표시
  doc["nt"]   = nodeTimeSec();               // ★ [제약③] 메시 동기 노드 각인 시각(초)
  String s; serializeJson(doc, s);
  mesh.sendBroadcast(s);
  if (NODE_IS_ROOT) { Serial.println(s); }   // 루트는 자기 패킷도 게이트웨이로
}

void broadcastHeartbeat() {
  if (state == DEAD) return;
  StaticJsonDocument<MESH_JSON_CAPACITY> d;
  d["type"] = "HB"; d["id"] = NODE_ID; d["x"] = NODE_X; d["y"] = NODE_Y;
  d["temp"] = curTemp; d["t"] = millis() / 1000.0;
  d["ms"] = millis(); d["st"] = stateName();
  sendJson(d);
}

void sendLastGasp() {
  StaticJsonDocument<MESH_JSON_CAPACITY> d;
  d["type"] = "LG"; d["id"] = NODE_ID; d["x"] = NODE_X; d["y"] = NODE_Y;
  d["temp"] = lastTemp; d["t"] = millis() / 1000.0;
  d["ms"] = millis(); d["st"] = stateName();
  // ★ [2026-09-01] sendJson() 을 쓰지 않는다 — 그 함수는 호출할 때마다 nt 를 다시 찍는다.
  //   여기서 한 번만 각인하고, 완성된 문자열을 loop() 가 그대로 재전송한다.
  d["fake"] = FAKE_FLAG;
  d["nt"]   = nodeTimeSec();          // ★ 각인은 여기 딱 한 번
  lgPayload = "";
  serializeJson(d, lgPayload);
  mesh.sendBroadcast(lgPayload);
  if (NODE_IS_ROOT) { Serial.println(lgPayload); }
  lgSendsLeft = LAST_GASP_REPEATS - 1;
  lgNextMs    = millis() + LAST_GASP_GAP_MS;
  lastGaspSent = true;
}

void sendVote(int suspect, float suspectTemp) {
  StaticJsonDocument<MESH_JSON_CAPACITY> d;
  d["type"] = "DV"; d["suspect"] = suspect; d["observer"] = NODE_ID;
  d["last_temp"] = suspectTemp; d["t"] = millis() / 1000.0;
  sendJson(d);
}

// 상태 전이를 시리얼에 명시적으로 남긴다(전이 순서 검증용).
void announceState() {
  StaticJsonDocument<MESH_JSON_CAPACITY> d;
  d["type"] = "ST"; d["id"] = NODE_ID; d["st"] = stateName();
  d["temp"] = curTemp; d["ms"] = millis(); d["fake"] = FAKE_FLAG;
  d["nt"] = nodeTimeSec();                  // [제약③] ST는 sendJson을 안 거치므로 별도 주입
  String s; serializeJson(d, s); Serial.println(s);
}

// ---- LED ----
void setLed() {
  if (state == ALIVE) led.setPixelColor(0, led.Color(0, 90, 0));       // 초록
  else                led.setPixelColor(0, led.Color(120, 0, 0));      // 빨강(DYING/DEAD)
  led.show();
}

// 좌표 캐시(루트가 suspect 좌표를 알도록 HB/LG에서 기록)
std::map<int, std::pair<float,float>> posCache;
// [제약③] 노드 각인 시각 캐시 — 사망시각의 정본은 **죽은 노드 자신이 찍은 시각**이다.
//   lgNt   : 그 노드의 Last-Gasp 각인 시각 = 임계(80℃)를 밟은 바로 그 순간. 최선의 사망시각.
//   lastNt : 그 노드가 마지막으로 스스로 각인한 시각(마지막 HB). 차선.
std::map<int, double> lastNtCache;
std::map<int, double> lgNtCache;
// [2.M P2] LG를 받은 적 있는 노드. ★비대칭: 있으면 게이트웨이가 채택 구제, 없으면 무판단.
std::set<int> hadLastGasp;

// ---- 루트: 투표 집계 → 사망 확정 → 시리얼 ----
void rootTallyAndConfirm(int suspect, int observer, float lastTemp,
                         float sx, float sy) {
  if (!NODE_IS_ROOT || confirmed.count(suspect)) return;
  votes[suspect].insert(observer);
  if ((int)votes[suspect].size() >= K_CONFIRM) {
    confirmed.insert(suspect);
    StaticJsonDocument<MESH_JSON_CAPACITY> d;
    d["type"] = "DC";                       // Death Confirmed
    d["id"] = suspect; d["x"] = sx; d["y"] = sy;
    // ★ [제약③] 루트의 확정 시각(millis)을 쓰면 침묵 감지(3s)+투표 집계 지연이 통째로 섞여
    //   사망시각이 뒤로 밀리고, 그 지연이 노드마다 달라 ∇T를 오염시킨다. 그래서
    //   **suspect 자신이 찍은 시각**을 쓰고, 어느 것을 썼는지 t_source로 남긴다.
    if (lgNtCache.count(suspect)) {
      d["death_t_est"] = lgNtCache[suspect];
      d["t_source"] = "last_gasp_node_stamp";
    } else if (lastNtCache.count(suspect)) {
      d["death_t_est"] = lastNtCache[suspect];
      d["t_source"] = "last_heartbeat_node_stamp";
    } else {
      d["death_t_est"] = nodeTimeSec();     // 자기 각인을 한 번도 못 받은 경우(최후 수단)
      d["t_source"] = "root_confirm_time_UNRELIABLE";
    }
    d["nt"] = nodeTimeSec();                // 확정 시각 자체(진단용, 사망시각과 구분)
    d["last_temp"] = lastTemp;
    // [2.M P1/P2] 게이트웨이의 3분기 선별이 쓸 증거. 게이트웨이는 자기 스트림으로도 같은 값을
    //   재구성하지만, 루트가 본 값을 함께 실어 교차확인할 수 있게 한다.
    d["rep_peak"] = neigh.count(suspect) ? neigh[suspect].peakTemp : lastTemp;
    d["had_last_gasp"] = hadLastGasp.count(suspect) ? 1 : 0;
    d["fake"] = FAKE_FLAG;                  // ★ gateway가 소비하는 유일한 타입 — 표시 필수
    String s; serializeJson(d, s); Serial.println(s);
  }
}

// ---- 메시 수신 콜백 ----
void onReceive(uint32_t from, String& msg) {
  // ★ [2026-08-30] 원문 출력을 **파싱보다 먼저** 한다.
  //   예전엔 파싱 뒤에 있었고, 파싱이 실패하면 그 앞에서 return 해버려
  //   브리지가 남의 패킷을 한 줄도 안 흘렸다(자기 패킷만 보였다).
  //   브리지의 역할은 원문 중계다 — 해석은 게이트웨이가 한다.
  //   파싱이 실패해도 게이트웨이는 원문을 받아야 한다.
  if (NODE_IS_ROOT) Serial.println(msg);

  StaticJsonDocument<MESH_JSON_CAPACITY> d;
  DeserializationError err = deserializeJson(d, msg);
  if (err) {
    // 침묵시키지 않는다. 조용한 실패가 이번 사고를 며칠 숨겼다.
    if (NODE_IS_ROOT) {
      Serial.print(F("# PARSE_FAIL "));
      Serial.print(err.c_str());
      Serial.print(F(" len="));
      Serial.print(msg.length());
      Serial.print(F(" cap="));
      Serial.println(MESH_JSON_CAPACITY);
    }
    return;
  }
  const char* type = d["type"] | "";

  if (!strcmp(type, "HB") || !strcmp(type, "LG")) {
    int id = d["id"]; float tp = d["temp"] | 25.0f;
    float pk = neigh.count(id) ? max(neigh[id].peakTemp, tp) : tp;
    neigh[id] = { millis(), tp, pk, false };  // 침묵 판정은 **수신측 로컬 시계**로 (지연 측정이 목적)
    if (!strcmp(type, "LG")) hadLastGasp.insert(id);   // [2.M P2] 양성 증거(비대칭)
    posCache[id] = { d["x"] | 0.0f, d["y"] | 0.0f };
    // [제약③] 사망시각 재구성용으로는 **송신 노드가 찍은 nt**를 따로 보관한다.
    if (d.containsKey("nt")) {
      double nt = d["nt"].as<double>();
      lastNtCache[id] = nt;
      if (!strcmp(type, "LG") && !lgNtCache.count(id)) lgNtCache[id] = nt;
    }
  } else if (!strcmp(type, "DV")) {
    int suspect = d["suspect"], observer = d["observer"];
    auto p = posCache.count(suspect) ? posCache[suspect] : std::make_pair(0.0f,0.0f);
    rootTallyAndConfirm(suspect, observer, d["last_temp"] | 0.0f, p.first, p.second);
  }
}

// ---- 부팅 배너: 합성/실측 모드를 육안으로 즉시 구분 [D-046] ----
void printModeBanner() {
#if FAKE_TEMP_RAMP
  Serial.println(F("****************************************************"));
  Serial.println(F("*** WARNING: FAKE_TEMP_RAMP=1                    ***"));
  Serial.println(F("*** SYNTHETIC TEMPERATURE - NOT REAL SENSOR DATA ***"));
  Serial.println(F("****************************************************"));
  // 기계 판독용(사람이 보는 배너가 잘려도 남도록 JSON으로도 1회 선언)
  Serial.println(F("{\"type\":\"MODE\",\"fake\":1,\"src\":\"FAKE_TEMP_RAMP\"}"));
  // LED: 합성 모드면 부팅 시 보라 1회 깜빡(영상 촬영 중에도 눈으로 구분)
  led.setPixelColor(0, led.Color(80, 0, 80)); led.show(); delay(400);
  led.clear(); led.show(); delay(200);
#else
  Serial.println(F("[REAL SENSOR MODE] DS18B20 on GPIO4"));
  Serial.println(F("{\"type\":\"MODE\",\"fake\":0,\"src\":\"DS18B20\"}"));
#endif
}

void setup() {
  Serial.begin(115200);
  led.begin();
  delay(300);                 // USB-CDC/시리얼 안정화 후 배너 출력(배너 유실 방지)
  printModeBanner();
  setLed();
  sensors.begin();
  // [2026-08-17] 해상도 **9비트** 고정. 두 가지 이유가 있고 둘 다 중요하다.
  //   (1) 12비트(기본값)는 변환이 750 ms 이고 readTemp()가 그동안 **블로킹**한다. 그러면
  //       LAST_GASP_DELAY_MS(300) 보다 블로킹이 길어져 DYING→DEAD 지연이 붕괴하고,
  //       임종 신호가 메시로 나가기 전에 송신이 끊길 수 있다. 9비트는 93.75 ms 다.
  //   (2) ★ 지금까지 실측한 τ·t80 이 **전부 9비트 프로브에서 나왔다.** 12비트로 두면
  //       교정에 쓴 센서와 데모 센서가 다른 물건이 된다. 16개 전부 9비트로 통일한다.
  //   분해능은 0.5 ℃ 로 떨어지지만 사망 판정(80 ℃)에는 충분하다.
  //   ※ setWaitForConversion(false)는 **의도적으로 쓰지 않는다** — 루프 재구조화가 필요하고,
  //     (1)은 이 한 줄로 750→94 ms 가 되어 해소된다. 변경을 최소로 유지한다.
  sensors.setResolution(9);
  mesh.setDebugMsgTypes(ERROR | STARTUP);
  mesh.init(MESH_PREFIX, MESH_PASSWORD, &userScheduler, MESH_PORT);
  mesh.onReceive(&onReceive);
  // [2026-08-27 브링업 진단] 보드 인덱스 <-> painlessMesh 노드ID 대응을 부팅 시 1회 남긴다.
  //   메시가 붙었는지 확인하려면 어느 mid 가 어느 보드인지 알아야 한다.
  //   (나중에 'NODE_ID 대신 meshNodeId 로 식별' 안을 쓸 때도 이 매핑이 출발점이다.)
  // ★ [2026-08-27] 배너에 **역할**을 반드시 싣는다.
  //   NODE_IS_ROOT 는 컴파일 타임 상수라, BRIDGE_INDEX 를 바꾸면서 이 매크로를 안 고치면
  //   브리지가 조용히 루트가 아니게 되고 시리얼 중계가 통째로 멈춘다(게이트웨이 입력 0줄).
  //   보드는 멀쩡히 돌아가므로 **배너에 찍지 않으면 잡을 방법이 없다.**
  //   NODE_ID 만 보는 검증은 이 실패를 못 잡는다 — is_root 를 따로 찍어야 한다.
  Serial.print(F("{\"type\":\"MESHID\",\"id\":"));
  Serial.print(NODE_ID);
  Serial.print(F(",\"mid\":"));
  Serial.print(mesh.getNodeId());
  Serial.print(F(",\"is_root\":"));
  Serial.print(NODE_IS_ROOT ? 1 : 0);
  Serial.print(F(",\"bridge_index\":"));
  Serial.print(BRIDGE_INDEX);
  Serial.print(F(",\"role\":\""));
  Serial.print(NODE_IS_ROOT ? F("ROOT(bridge)") : F("NODE"));
  // ★ 사망 임계를 배너에 싣는다 — 시험용 임시값(40)을 그대로 데모에 들고 가는 사고를 막는 유일한 수단.
  //   flash_node.ps1 이 이 값을 읽어 "플래그 없이 구웠는데 80.0 이 아니면 FAIL" 로 자동 판정한다.
  Serial.print(F("\",\"death_threshold_c\":"));
  Serial.print(TEMP_THRESHOLD_C, 1);
  // ★ [2026-08-30] WARN_TEMP_C 도 배너에 싣는다.
  //   이날 사망확정이 구조적으로 불가능했던 원인이 이 상수였는데(임계 40 / WARN 60),
  //   배너에 없어서 **구운 뒤에 확인할 방법이 없었다.** 정적 점검으로 우연히 잡았을 뿐이다.
  //   투표(교차검증)가 성립하려면 이웃이 관측 가능한 온도 상한 = 임계값이 WARN 을 넘어야 하므로
  //   WARN < 임계값 이 불변식이다. config.h 의 static_assert 가 컴파일 때 막고,
  //   이 줄이 **구워진 실물에서** 같은 값을 눈으로 확인시킨다.
  Serial.print(F(",\"warn_temp_c\":"));
  Serial.print(WARN_TEMP_C, 1);
  // ★ [2026-08-31] 실제로 쓰는 WS2812 데이터 핀을 배너에 싣는다.
  //   n04 는 GPIO5 불량으로 18 로 구웠다. 배너에 없으면 **구운 뒤에 확인할 방법이 없고**,
  //   나중에 아무 생각 없이 다시 구우면 또 안 켜진다(임계값·WARN 을 배너에 실은 것과 같은 이유).
  Serial.print(F(",\"led_pin\":"));
  Serial.print(PIN_NEOPIXEL);
  Serial.println(F("}"));
  if (NODE_IS_ROOT) Serial.println("{\"type\":\"ROOT_READY\"}");
  announceState();              // 초기 상태(ALIVE)를 기준선으로 남긴다
}

uint32_t lastSense = 0, lastHb = 0;

// [2026-08-27 브링업 진단] 루트가 5초마다 메시 토폴로지를 원문 그대로 뱉는다.
//   "몇 대가 붙었는가 / 언제 붙었는가 / 뽑았다 꽂으면 다시 붙는가" 를 눈이 아니라
//   로그로 판정하기 위한 것이다. 판정 경로(HB/LG/DV/DC)는 건드리지 않는다.
//   게이트웨이는 모르는 타입이라 dropped_types 에 세고 버린다 — 무해.
// ★ [2026-08-31] 브리지 힙 절감 — 이 블록은 **루트에서만** 돈다(노드 동작은 안 바뀐다).
//
// 왜: 2026-08-31 측정에서 브리지가 30분에 3번 크래시했다. 크래시 직전에
//     `routePackage(): parsing failed. err=4` 가 찍혔는데, err=4 는 ArduinoJson 의
//     **NoMemory** 다 — 힙(또는 연속 블록)이 모자랐다는 뜻이다.
//     그 상황에서 `mesh.subConnectionJson()` 은 **5초마다 최대 577자 String 을 새로 만든다**
//     (30분에 338회 실측). 그런데 **게이트웨이는 TOPO 를 쓰지 않는다** — 모르는 타입이라
//     dropped_types 로 세고 버린다. 힙이 모자란 판에 쓰지도 않는 문자열을 만드는 것은 순수 손해다.
//     그래서 **서브트리 출력을 기본으로 끈다.** n_peers(정수 하나)는 그대로 남긴다.
//     브링업 진단이 다시 필요하면 -DTOPO_FULL_SUBTREE=1 로 켠다.
#ifndef TOPO_FULL_SUBTREE
#define TOPO_FULL_SUBTREE 0
#endif

uint32_t nextTopoMs = 0;
void logTopology() {
  if (!NODE_IS_ROOT) return;
  if ((int32_t)(millis() - nextTopoMs) < 0) return;
  nextTopoMs = millis() + 5000;
  Serial.print(F("{\"type\":\"TOPO\",\"ms\":"));
  Serial.print(millis());
  Serial.print(F(",\"mid\":"));
  Serial.print(mesh.getNodeId());
  Serial.print(F(",\"n_peers\":"));
  Serial.print(mesh.getNodeList().size());
#if TOPO_FULL_SUBTREE
  Serial.print(F(",\"sub\":"));
  Serial.print(mesh.subConnectionJson());
#endif
  Serial.println(F("}"));
}

// ★ [2026-08-31] 힙 계측 — 크래시 직전 값을 남기기 위한 것.
//   free      : 지금 남은 힙 총량
//   min_free  : 부팅 이후 최저치 (얼마나 아슬아슬했는지)
//   max_alloc : **연속으로 잡을 수 있는 가장 큰 블록** — NoMemory 는 총량이 아니라
//               이 값이 모자랄 때 난다(단편화). err=4 를 이해하려면 이 값이 필요하다.
//   숫자만 찍으므로 String 을 만들지 않는다(계측이 문제를 키우지 않게).
uint32_t nextHeapMs = 0;
void logHeap() {
  if (!NODE_IS_ROOT) return;
  if ((int32_t)(millis() - nextHeapMs) < 0) return;
  nextHeapMs = millis() + 5000;
  Serial.print(F("{\"type\":\"HEAP\",\"ms\":"));
  Serial.print(millis());
  Serial.print(F(",\"free\":"));
  Serial.print(ESP.getFreeHeap());
  Serial.print(F(",\"min_free\":"));
  Serial.print(ESP.getMinFreeHeap());
  Serial.print(F(",\"max_alloc\":"));
  Serial.print(ESP.getMaxAllocHeap());
  Serial.print(F(",\"peers\":"));
  Serial.print(mesh.getNodeList().size());
  Serial.println(F("}"));
}

void loop() {
  mesh.update();
  logTopology();
  logHeap();
  uint32_t now = millis();

  // 1) 센싱
  if (now - lastSense >= SENSE_MS) {
    lastSense = now;
    curTemp = readTemp();
    if (state != DEAD) lastTemp = curTemp;

    // ★★ [2026-09-01] WARN 교차 시 하트비트를 **강제로 한 번** 보낸다.
    //
    //   HEARTBEAT_MS 를 10초로 늦추면서 생긴 부작용을 막는 것이다.
    //   이웃의 사망 투표는 `silent && hot` 두 조건을 모두 요구하는데(아래 교차검증 블록),
    //   `hot` 은 **그 노드의 60℃ 이상 하트비트를 이웃이 받아 둔 적이 있을 때**만 참이다.
    //   실측(results/hw/t80_calib_curve.csv): 60℃ → 80℃ 구간이 **4.5~7.0초**뿐이다.
    //   10초 주기면 그 구간에 하트비트가 **한 개도 안 들어갈 수 있고**, 그러면
    //   임종신호를 놓쳤을 때 예비 경로인 투표까지 같이 죽는다.
    //
    //   교차 순간에 한 번만 쏘므로 트래픽은 노드당 런 전체에서 1개 늘 뿐이다.
    //   주기 타이머(lastHb)도 같이 리셋해 바로 뒤이어 또 나가지 않게 한다.
    if (state == ALIVE && !warnAnnounced && curTemp >= WARN_TEMP_C) {
      warnAnnounced = true;
      lastHb = now;
      broadcastHeartbeat();
    }

    // ★ [2026-08-31] t80 교정용 온도 트레이스 — **비루트 노드의 자기 시리얼에만** 찍는다.
    //   왜 필요한가: 비루트 노드는 HB 를 메시로만 보내고 자기 시리얼에는 안 찍는다
    //   (sendJson 의 `if (NODE_IS_ROOT)`). 그래서 t80 교정에 쓸 온도 곡선을 얻을 길이
    //   없었다. 무선으로 받으면 도착률이 10% 안팎이라 80℃ 통과 순간을 놓친다.
    //   루트(브리지)에서는 찍지 않는다 — 게이트웨이 입력 스트림을 늘리지 않기 위해서다.
    //   DEAD 이후에도 계속 찍는다: 파손 여유(125℃까지)를 외삽하려면 통과 뒤 기울기가 필요하다.
#if !NODE_IS_ROOT
    Serial.print(F("{\"type\":\"TT\",\"ms\":"));
    Serial.print(millis());
    Serial.print(F(",\"temp\":"));
    Serial.print(curTemp, 2);
    Serial.print(F(",\"st\":\""));
    Serial.print(stateName());
    Serial.println(F("\"}"));
#endif

    // 2) 임계 → DYING + Last-Gasp
    if (state == ALIVE && curTemp >= TEMP_THRESHOLD_C) {
      // [2026-08-17] `now`(루프 진입 시각, L248)가 아니라 **판정 순간의 millis()** 로 찍는다.
      //   readTemp()가 변환시간만큼 블로킹하므로 `now`는 그만큼 과거다. 그대로 쓰면
      //   임종 지연이 그 편향만큼 깎인다(실측: 300 설정인데 196 ms 였다 — G0 캡처 2026-08-17).
      state = DYING; dyingAtMs = millis(); setLed();
      announceState();          // 전이 기록: ALIVE → DYING
      sendLastGasp();           // 임종 신호는 전이 직후 1회
    }
  }

  // DYING → DEAD (임종 지연 후 송신 중단)
  // [2026-08-17] ②의 필수 동반 수정. dyingAtMs 를 판정 순간(=`now` 이후)으로 찍었으므로
  //   같은 루프에서는 `now < dyingAtMs` 다. uint32 뺄셈이라 `now - dyingAtMs` 는 약 42억으로
  //   **언더플로**해 300 을 넘겨버리고, DEAD 가 같은 루프에서 즉시 발동한다
  //   (= 임종 신호가 메시로 나가기 전에 송신 중단). 그래서 비교도 millis() 기준으로 바꾼다.
  //   millis() 는 항상 dyingAtMs 이후이므로 언더플로가 없다.
  if (state == DYING && millis() - dyingAtMs >= LAST_GASP_DELAY_MS) {
    state = DEAD; setLed();
    announceState();            // 전이 기록: DYING → DEAD (이후 송신 중단)
  }

  // ★ [2026-09-01] 임종신호 재송 — **DEAD 이후에도 계속한다.** 여기가 이 수정의 전부다.
  //   DEAD 는 하트비트를 멈추게 하는 것이지(도배 방지) 임종신호를 멈추라는 뜻이 아니다.
  //   같은 문자열을 그대로 다시 쏘므로 사망 시각은 첫 각인 그대로다.
  //   중복 사망은 생기지 않는다 — 게이트웨이(fw_adapter.py: lg_t 가 None 일 때만 기록)와
  //   메시 중계(아래 onReceive 의 lgNtCache) 양쪽이 **첫 LG 만** 채택한다.
  //   (int32_t) 캐스팅: uint32 뺄셈의 언더플로를 피한다. 이 프로젝트는 같은 자리에서
  //   이미 한 번 당했다 — dyingAtMs 언더플로로 임종신호 전에 DEAD 가 발동했다.
  if (lgSendsLeft > 0 && (int32_t)(millis() - lgNextMs) >= 0) {
    mesh.sendBroadcast(lgPayload);
    if (NODE_IS_ROOT) { Serial.println(lgPayload); }
    lgSendsLeft--;
    lgNextMs = millis() + LAST_GASP_GAP_MS;
  }

  // 1) 하트비트(ALIVE만)
  if (state == ALIVE && now - lastHb >= HEARTBEAT_MS) {
    lastHb = now; broadcastHeartbeat();
  }

  // 3) 교차검증: 이웃 침묵(>timeout) + 고온 정황 → 사망 투표(관측자=나)
  if (state != DEAD) {
    for (auto& kv : neigh) {
      Neigh& n = kv.second;
      // ★ [2.M P1] 이 게이트는 **판정이 아니라 후보 생성**이다(recall 우선).
      //   최종 화재/비화재 판정(3분기 + residual + Fix A)은 **게이트웨이**가 한다 —
      //   residual은 확정된 이웃 사망들의 평면 적합이 필요해 단일 노드에서 계산 불가능하기 때문.
      //   그래서 여기서는 **더 조이지 않는다**. 조이면 게이트웨이의 분기③이 볼 후보가 사라져
      //   진짜 화재사망을 놓친다(미탐지). lastTemp → peakTemp 로 바꾼 것도 같은 이유(더 관대).
      bool silent = (now - n.lastHeard) > SILENCE_TIMEOUT_MS;
      bool hot    = (n.peakTemp >= WARN_TEMP_C) || (curTemp >= WARN_TEMP_C);
      if (silent && hot && !n.voted) {
        n.voted = true;
        sendVote(kv.first, n.lastTemp);
      }
    }
  }
}
