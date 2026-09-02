"""fw_adapter.py — **펌웨어 방언 → 게이트웨이 방언** 변환 계층 [2.K §2].

문제([D-046]가 남긴 미해결):
  `gateway.py` 가 처리하는 타입 : META NODES DC ROUTE GT STATS TICK
  `node.ino` 가 송신하는 타입   : MODE ROOT_READY ST HB LG DV DC
  **교집합이 `DC` 하나뿐.** gateway는 `META`로 `Config`를 만들고 `TICK`으로 프레임을 만드는데
  펌웨어는 둘 다 안 보낸다 → 실보드를 물리면 **프레임 0개**, 그 전에 `self.cfg`가 None이라 예외.

원인(기록할 가치가 있음): **시뮬 우선 개발의 구조적 대가.**
  gateway는 **시뮬 출력 형식**에 맞춰 자랐고 펌웨어는 **실물에 자연스러운 형식**으로 자랐다.
  서로 다른 계약을 향해 각자 정상적으로 성장한 결과이며, "시뮬로만 검증한 구간의 **경계**에서
  계약 불일치가 드러난" 사례다. 어느 쪽도 버그가 아니라 **접합부가 없었을 뿐**이다.

═══════════════════════════════════════════════════════════════════════════════
제약 4개 (지시서 §2) — 이 파일이 지키는 것
═══════════════════════════════════════════════════════════════════════════════
 ① **`sim/estimator.py` 절대 불변.** 변환은 전부 이 어댑터 안에서만 한다.
    (2.J 포함 모든 강건성 검증이 그 파일 위에 서 있다.)
 ② **노드 좌표는 `deploy_config.json`** 에서 읽는다. 펌웨어가 보내는 좌표(`posCache`)는
    **신뢰하지 않는다** — 루트가 HB를 못 받은 노드는 (0,0)으로 남고, 그게 그대로 들어가면
    ∇T가 망가진다. 좌표의 정본은 **우리가 물리적으로 배치한 격자**다.
 ③ **시각은 반드시 노드 각인.** 게이트웨이 수신 시각을 쓰면 통신 지연이 도착시각장을 오염시켜
    방향 추정이 깨진다. 아래 `_node_time()` 이 유일한 시각 출처이며, 벽시계·수신순서를
    **절대** 쓰지 않는다.
 ④ **`fake` 필드를 명시적으로 통과시킨다.** 형식 변환 중 자기가 모르는 필드를 버리면
    [D-046]의 합성데이터 안전장치가 **바로 여기서 죽는다**. 이 파일은 `fake`를 노드별로
    추적하고 DC·NODES·STATS 전부에 실어 보낸다. `tests/test_fw_adapter.py`가 이를 고정한다.
"""
from __future__ import annotations

import json
import os

# 펌웨어가 노드 각인 시각을 싣는 필드 후보(우선순위 순).
#   nt : mesh.getNodeTime() 기반 **메시 동기 시각(초)** — 정본. 노드 간 비교 가능.
#   t  : millis()/1000 기반 **보드 로컬 시각(초)** — 부팅 시점이 달라 노드 간 비교 불가.
# ★ `t`만 있는(구) 펌웨어도 돌아가게 폴백하되, 그때는 `time_source="local_millis"`로 표시해
#   "노드 간 비교 불가"라는 사실이 로그에 남게 한다. 조용히 섞지 않는다.
NODE_TIME_FIELDS = ("nt", "t")

# ---- `nt` 랩어라운드 보정 상수 ----
# `mesh.getNodeTime()`은 **uint32 마이크로초**다(node.ino L85-86에 한계로 명시됨).
#   2^32 µs = 4294.967296 s ≈ **71.58 분**마다 0으로 되감긴다.
# 되감기면 `v - t0`가 통째로 음수가 되어 **사망 시각 순서가 뒤집힌다**. 값이 사라지는 게 아니라
# 그럴듯한 숫자로 바뀌므로 **조용히 틀린다** — 촬영이 71분을 넘으면 방향 추정이 통째로 무의미해진다.
# 되감김 판정은 **범위의 절반**을 임계로 쓴다. 정상 진행은 초 단위로 늘고, 되감김은 2147 s 이상
# 뒤로 튄다. 이 간격이 워낙 커서 재전송·순서뒤바뀜과 혼동될 여지가 없다.
NT_WRAP_S = 4294967296.0 / 1_000_000.0        # 4294.967296 s
NT_WRAP_GUARD_S = NT_WRAP_S / 2.0             # 2147.483648 s

# ★ [2026-08-31 소크] 뒤로 튀는 것이 **전부 랩어라운드는 아니다.**
#   그날 소크에서 노드 6대가 실시각 42분에 mesh nodeTime 을 동시에 ~0 으로 되돌렸는데,
#   감소량이 3057 s 로 랩 주기 4294.967 s 와 달랐다(진짜 랩은 같은 로그의 브리지에서
#   71.6분에 4293.4 s 감소로 따로 관측됐다). 위 GUARD 만으로는 둘을 구분하지 못해
#   3057 s 역행에 4294.967 s 를 더해 **1237 s 오차를 조용히 주입**한다.
#   → 보정 동작은 바꾸지 않는다(진짜 랩 보정을 깨뜨릴 수 있다). 대신 **분류해서 기록**한다.
NT_WRAP_TOL_S = 60.0          # |delta + NT_WRAP_S| 가 이보다 크면 '랩 같지 않은 역행'
UPTIME_WARN_S = 40.0 * 60.0   # 40분. 런 22분 + 여유 → 랩(71.6분) 전에 반드시 재인가하라는 경고선

_DEFAULT_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_config.json")


class FirmwareAdapter:
    """펌웨어 JSONL 한 줄을 먹고, 게이트웨이가 아는 JSONL 여러 줄을 뱉는다.

    사용:
        ad = FirmwareAdapter.from_file("gateway/deploy_config.json")
        for line in fw_lines:
            for out in ad.feed(line):
                gw.feed(out)
        for out in ad.flush():
            gw.feed(out)
    """

    def __init__(self, deploy: dict, tick_period_s: float = 1.0):
        self.deploy = deploy
        self.tick_period = tick_period_s
        self.sink_id = int(deploy.get("sink_id", 0))
        # 브리지 예약 번호 — firmware/node/config.h 의 BRIDGE_INDEX 와 같은 값이어야 한다.
        #   격자 id(0..15) 밖이라 좌표가 없고, 격자 노드로 오인되면 (0,0) 에 유령 사망이 생긴다.
        self.bridge_index = int(deploy.get("bridge_index", 99))
        self.n_bridge_self = 0                 # 브리지 자기보고를 버린 횟수(진단용)
        # ② 좌표 정본 — deploy_config 만 신뢰
        self.nodes = {int(n["id"]): {"x": float(n["x"]), "y": float(n["y"]),
                                     # ★ [2026-08-27] is_sink 는 **bridge_index 로만** 판단한다.
                                     #   실물의 싱크는 브리지(99)이고 격자점이 아니다. 격자 노드 0 은
                                     #   대본 B에서 t=0 에 **제일 먼저 죽는** 평범한 노드다.
                                     #   is_sink=True 로 남겨두면 gateway.py:177 의 생존자·경보 목록에서
                                     #   빠져, 첫 사망인데 화면에 아무 반응이 없는 것으로 보인다.
                                     #   JSON 의 is_sink 필드는 시뮬 유산이라 **읽지 않는다.**
                                     "is_sink": (int(n["id"]) == self.bridge_index)}
                      for n in deploy["nodes"]}
        self.cfg = dict(deploy["config"])

        self._meta_sent = False
        self._t0: float | None = None          # 첫 노드 각인 시각(상대시간 기준점)
        self._t_now = 0.0                      # 최신 노드 각인 시각(상대, 초)
        self._next_tick = 0.0
        self._time_source = None               # "mesh_nodetime" | "local_millis"
        # ---- `nt` 랩어라운드 추적 (71.58분 주기) ----
        self._nt_prev_raw: float | None = None  # 직전에 본 **원시** nt(보정 전)
        self._nt_epoch = 0.0                    # 누적 보정량(= NT_WRAP_S × 랩 횟수)
        self.nt_wraps = 0                       # 랩 감지 횟수(진단·리포트용)

        # 런타임 상태
        self.state = {nid: "ALIVE" for nid in self.nodes}
        self.temp = {nid: None for nid in self.nodes}
        self.last_seen_t = {nid: None for nid in self.nodes}   # ③ 노드 각인 최신 시각
        self.lg_t = {nid: None for nid in self.nodes}          # ③ Last-Gasp 자기 각인 시각
        self.fake = {nid: 0 for nid in self.nodes}             # ④ 노드별 합성 표시
        # ── [P1/P2] 판정 증거 — 게이트웨이의 3분기 선별이 쓸 재료 ──
        #   rep_peak       : 그 노드가 **보고한 온도의 최고값**(시뮬 verification의 rep_peak과 같은 뜻).
        #                    현재 온도가 아니라 **최고값**이어야 한다 — 노드가 죽으면 보고가 끊겨
        #                    마지막 값이 임계 근처에 고정되므로, 최고값이 열 이력을 더 잘 담는다.
        #   had_last_gasp  : LG를 한 번이라도 받았는가. [P2] **비대칭 증거**(있으면 채택 구제, 없으면 무판단).
        self.rep_peak = {nid: None for nid in self.nodes}
        self.had_lg = {nid: False for nid in self.nodes}
        self.session_fake = 0                                  # ④ 세션 전체(하나라도 합성이면 1)
        self.confirmed: set[int] = set()

        # 진단
        self.unknown_ids: set[int] = set()
        self.dropped_types: dict[str, int] = {}
        self.n_lines = 0
        self.warnings: list[str] = []
        # ★ 시각 역행을 조용히 넘기지 않는다 — 분류해서 산출물까지 나른다.
        self.time_regressions: list[dict] = []   # 랩/의심 전부
        self.suspect_regressions = 0             # 랩으로 설명되지 않는 역행 건수
        self._nt_raw_max: dict[int, float] = {}  # id -> 본 적 있는 최대 원시 nt(=uptime 대용)
        self._uptime_warned: set[int] = set()
        self._nt_prev_raw_before: float | None = None

    # ---------- 생성 ----------
    @classmethod
    def from_file(cls, path: str | None = None, tick_period_s: float = 1.0):
        with open(path or _DEFAULT_CFG, encoding="utf-8") as f:
            return cls(json.load(f), tick_period_s=tick_period_s)

    # ---------- ③-1 `nt` 랩어라운드 보정 ----------
    def _unwrap_nt(self, v: float, track: bool = True) -> float:
        """원시 `nt`(0 ~ 4294.967296 s 순환)를 **단조 증가하는 절대 초**로 편다.

        되감김을 만나면 이후 모든 값에 `NT_WRAP_S`를 누적해서 더한다. 71.58분을 넘는
        연속 촬영에서 사망 시각이 뒤집히는 것을 막는 유일한 방어다.

        track=False 는 **시계열 추적을 건드리지 않고 현재 보정량만 적용**할 때 쓴다.
          DC의 `death_t_est`는 '지금'이 아니라 **과거의 사망 순간**이라, 이걸로 직전값을
          갱신하면 정상 스트림이 뒤로 튄 것처럼 보인다. 그래서 읽기만 한다.
        """
        if self._nt_prev_raw is None:
            if track:
                self._nt_prev_raw = v
            return v

        delta = v - self._nt_prev_raw
        self._nt_prev_raw_before = self._nt_prev_raw
        if delta < -NT_WRAP_GUARD_S:
            # 되감김: 2147 s 이상 뒤로 튀었다 → 한 주기 넘어간 것으로 본다.
            if track:
                self._nt_epoch += NT_WRAP_S
                self.nt_wraps += 1
                self._nt_prev_raw = v
                drop = -delta                       # 실제로 뒤로 튄 양(양수)
                mismatch = abs(drop - NT_WRAP_S)
                looks_like_wrap = mismatch <= NT_WRAP_TOL_S
                if not looks_like_wrap:
                    self.suspect_regressions += 1
                self.time_regressions.append({
                    "n": self.nt_wraps, "prev_raw_s": round(self._nt_prev_raw_before, 3),
                    "new_raw_s": round(v, 3), "drop_s": round(drop, 3),
                    "wrap_period_s": round(NT_WRAP_S, 3),
                    "mismatch_s": round(mismatch, 3),
                    "classified": "WRAP" if looks_like_wrap else "SUSPECT_NOT_WRAP",
                    "injected_error_s": 0.0 if looks_like_wrap else round(NT_WRAP_S - drop, 3)})
                if looks_like_wrap:
                    self.warnings.append(
                        f"mesh nodeTime 랩어라운드 감지 #{self.nt_wraps} "
                        f"(uint32 µs, 주기 {NT_WRAP_S:.3f}s≈71.6분). 이후 시각에 "
                        f"{self._nt_epoch:.3f}s를 더해 보정한다.")
                else:
                    self.warnings.append(
                        f"★★ 시각이 {drop:.1f}s 뒤로 튀었는데 랩 주기 {NT_WRAP_S:.1f}s 와 "
                        f"{mismatch:.1f}s 어긋난다 — **랩어라운드가 아닐 수 있다.** "
                        f"그래도 한 주기를 더해 보정했으므로 이후 사망 시각에 "
                        f"약 {NT_WRAP_S - drop:+.1f}s 오차가 들어갔을 수 있다. "
                        f"이 회차를 그대로 쓰지 말 것. (2026-08-31 소크에서 실제로 관측된 현상)")
                return v + self._nt_epoch
            # track=False: 이 값은 '랩 이후'로 간주해 현재 보정량 + 한 주기
            return v + self._nt_epoch + NT_WRAP_S
        if delta > NT_WRAP_GUARD_S and self._nt_epoch > 0.0:
            # 랩 직후 도착한 **랩 이전** 패킷(지연·재전송). 한 주기를 빼서 제자리로 돌린다.
            return v + self._nt_epoch - NT_WRAP_S
        if track:
            self._nt_prev_raw = v
        return v + self._nt_epoch

    # ---------- ③ 시각: 노드 각인만 ----------
    def _node_time(self, m: dict) -> float | None:
        """패킷에 **노드가 스스로 찍은** 시각을 초 단위 상대시간으로 돌려준다.

        ★ 게이트웨이 수신 시각(time.time())·수신 순서는 **쓰지 않는다.** 통신 지연·재전송이
          도착시각장 T(x,y)를 오염시키면 ∇T가 곧바로 망가지기 때문이다(H0 이래의 규약).
        """
        for f in NODE_TIME_FIELDS:
            if f in m:
                try:
                    v = float(m[f])
                except (TypeError, ValueError):
                    continue
                src = "mesh_nodetime" if f == "nt" else "local_millis"
                # ★ 랩 보정은 `nt`(uint32 µs)에만 적용한다. `t`는 millis 기반(uint32 ms,
                #   49.7일 주기)이라 데모 길이에서 랩이 없고, 애초에 노드 간 비교가 불가라
                #   같은 축으로 펴는 의미가 없다.
                if f == "nt":
                    # ★ [2026-08-31] uptime 감시. 원시 nt 는 전원 인가 후 흐른 시간에 가깝다
                    #   (부팅 시 0 부근에서 시작해 71.58분에 되감긴다). 40분을 넘기면
                    #   런(22분) 도중 랩을 맞을 수 있으므로 **재인가하라고 시끄럽게 알린다.**
                    #   절차(런 전 전원 재인가)를 사람이 잊었을 때의 안전망이다.
                    nid_u = m.get("id")
                    if isinstance(nid_u, int):
                        if v > self._nt_raw_max.get(nid_u, -1.0):
                            self._nt_raw_max[nid_u] = v
                        if v > UPTIME_WARN_S and nid_u not in self._uptime_warned:
                            self._uptime_warned.add(nid_u)
                            self.warnings.append(
                                f"★ uptime 경고 — 노드 id {nid_u} 의 nodeTime 이 {v:.0f}s "
                                f"({v/60:.1f}분)로 {UPTIME_WARN_S/60:.0f}분을 넘었다. "
                                f"{NT_WRAP_S/60:.1f}분에 되감기므로 런 도중 랩을 맞을 수 있다. "
                                f"**런을 멈추고 전 노드·브리지 전원을 재인가할 것.**")
                    v = self._unwrap_nt(v)
                if self._time_source is None:
                    self._time_source = src
                    if src == "local_millis":
                        self.warnings.append(
                            "노드 각인 시각이 `t`(millis 기반, 보드 로컬)뿐이다. 부팅 시점이 달라 "
                            "노드 간 비교가 성립하지 않는다 → 방향 추정이 신뢰 불가. "
                            "펌웨어가 mesh.getNodeTime() 기반 `nt`를 싣도록 할 것.")
                elif self._time_source != src:
                    self.warnings.append(f"시각 출처가 섞였다: {self._time_source} ↔ {src}")
                if self._t0 is None:
                    self._t0 = v
                return v - self._t0
        return None

    # ---------- ④ fake ----------
    def _note_fake(self, nid: int | None, m: dict) -> None:
        if "fake" not in m:
            return
        try:
            fk = int(m["fake"])
        except (TypeError, ValueError):
            return
        if fk:
            self.session_fake = 1
        if nid is not None and nid in self.fake:
            # 한 번이라도 합성이면 계속 합성으로 본다(안전측: 표시를 지우지 않는다)
            self.fake[nid] = max(self.fake[nid], fk)

    # ---------- 출력 ----------
    def _meta(self) -> dict:
        return {
            "type": "META",
            "config": self.cfg,
            "sink_id": self.sink_id,
            "nodes": [{"id": nid, "x": n["x"], "y": n["y"], "is_sink": n["is_sink"]}
                      for nid, n in sorted(self.nodes.items())],
            # ④ 세션 수준 표시도 남긴다(대시보드 배지용)
            "fake": self.session_fake,
            "deployment": self.deploy.get("deployment", {}),
            "time_source": self._time_source,
        }

    def _nodes_line(self) -> dict:
        amb = 25.0
        return {"type": "NODES",
                "nodes": [{"id": nid,
                           "temp": (self.temp[nid] if self.temp[nid] is not None else amb),
                           "state": self.state[nid],
                           "rep_peak": (self.rep_peak[nid] if self.rep_peak[nid] is not None else amb),
                           "fake": self.fake[nid]}          # ④ 노드별 표시
                          for nid in sorted(self.nodes)]}

    def _stats_line(self) -> dict:
        return {"type": "STATS", "delivery_rate": 1.0,
                "n_dead": sum(1 for s in self.state.values() if s == "DEAD"),
                "fake": self.session_fake}                  # ④

    # ---------- 메인 ----------
    def feed(self, line) -> list[str]:
        """펌웨어 라인 1개 → 게이트웨이 라인 0개 이상(JSON 문자열)."""
        if isinstance(line, (bytes, bytearray)):
            line = line.decode("utf-8", "ignore")
        line = (line or "").strip()
        if not line:
            return []
        self.n_lines += 1
        try:
            m = json.loads(line)
        except Exception:
            return []                      # 배너 등 비-JSON 줄은 무시
        if not isinstance(m, dict):
            return []
        typ = m.get("type")
        out: list[dict] = []

        # --- 노드 식별 ---
        nid = None
        for key in ("id", "suspect"):
            if key in m:
                try:
                    nid = int(m[key])
                except (TypeError, ValueError):
                    nid = None
                break
        # ★ [2026-08-27] 브리지 자기보고는 **정상적으로** 버린다(오류가 아니다).
        #   브리지는 메시에 참여하는 실제 보드라 자기 HB/ST 를 브로드캐스트한다.
        #   그런데 브리지는 격자점이 아니므로 좌표가 없다. deploy_config 의 nodes 에도 없다.
        #   이걸 unknown_ids 에 넣으면 "배선/설정 오류"로 보이는 진단 목록이 매초 오염된다.
        #   그래서 예약 번호를 알고 **조용히, 그러나 세어서** 버린다.
        if nid is not None and nid == self.bridge_index:
            self.n_bridge_self += 1
            nid = None
        elif nid is not None and nid not in self.nodes:
            self.unknown_ids.add(nid)      # deploy_config에 없는 노드 → 좌표 불명 → 버린다
            nid = None

        self._note_fake(nid, m)            # ④ 어떤 타입이든 fake를 먼저 흡수
        t = self._node_time(m)             # ③ 노드 각인 시각
        if t is not None:
            self._t_now = max(self._t_now, t)
            # ★ **자기보고 타입에서만** 그 노드의 각인 시각으로 인정한다.
            #   DC는 루트가, DV는 관측자가 보낸 줄이라 거기 실린 nt는 **남의 시계**다.
            #   이걸 suspect의 각인으로 기록하면 사망시각에 루트의 확정 지연이 그대로 섞여
            #   제약③이 무너진다(테스트 test_falls_back_to_heartbeat_stamp_when_last_gasp_lost).
            if nid is not None and typ in ("HB", "LG", "ST"):
                self.last_seen_t[nid] = t

        # --- META는 첫 유효 라인에서 1회 ---
        if not self._meta_sent and typ in ("MODE", "ROOT_READY", "HB", "LG", "ST", "DV", "DC"):
            self._meta_sent = True
            out.append(self._meta())

        # --- 타입별 ---
        if typ in ("HB", "LG"):
            if nid is not None:
                if "temp" in m:
                    try:
                        tv = float(m["temp"])
                        self.temp[nid] = tv
                        pk = self.rep_peak[nid]
                        self.rep_peak[nid] = tv if pk is None else max(pk, tv)
                    except (TypeError, ValueError):
                        pass
                st = m.get("st")
                if st in ("ALIVE", "DYING", "DEAD") and self.state.get(nid) != "DEAD":
                    self.state[nid] = st
                if typ == "LG":
                    # ③ 임계를 밟은 **그 노드 자신의 각인 시각** = 가장 좋은 사망시각 추정
                    first_lg = self.lg_t[nid] is None
                    if t is not None and self.lg_t[nid] is None:
                        self.lg_t[nid] = t
                    self.had_lg[nid] = True          # [P2] 양성 증거(비대칭)

                    # ★★★ [2026-09-01] LG 만으로 사망을 확정한다.
                    #
                    #   기존 설계: 사망은 오직 DC(Death Confirmed) 로만 death_log 에 들어갔다.
                    #   DC 가 나가려면 서로 다른 이웃 K_CONFIRM(3)명이 각각
                    #     (그 노드의 60도 이상 HB 를 이전에 목격했다) AND (30초 침묵을 감지했다)
                    #   를 만족해 투표(DV)를 브리지까지 보내야 하고, 그 투표 3개가 전부
                    #   도달한 뒤에야 브리지가 DC 를 만들어 다시 브리지→게이트웨이 구간을
                    #   거친다. 실측 도착률(6~7%)에서 "서로 다른 셋이 각각 도달"은
                    #   "LG 1개 도달"보다 확률이 한참 낮다 — 그래서 (가′) 로 LG 를 3~5회
                    #   반복해도 사망이 5회 연속 전부 미확정이었다(n07 ×4, n12 ×1).
                    #
                    #   LG 는 이미 "그 노드 자신이 임계를 넘었다"는 가장 직접적인 1차 증거다.
                    #   도달 즉시 확정한다. DC 가 그래도 나중에 오면 `nid not in self.confirmed`
                    #   가 거짓이 되어 조용히 무시된다(중복 사망 방지, 아래 elif "DC" 블록 참조).
                    #   비화재사망 방어(3분기 선별)는 death_log 진입 **이후** 게이트웨이 쪽에서
                    #   그대로 걸리므로 이 변경과 무관하게 유지된다.
                    if first_lg and nid not in self.confirmed:
                        self.confirmed.add(nid)
                        self.state[nid] = "DEAD"
                        out.append(self._dc(nid, m))

                    if self.state.get(nid) == "ALIVE":
                        self.state[nid] = "DYING"

        elif typ == "ST":
            st = m.get("st")
            if nid is not None and st in ("ALIVE", "DYING", "DEAD"):
                if self.state.get(nid) != "DEAD":
                    self.state[nid] = st
                if "temp" in m:
                    try:
                        self.temp[nid] = float(m["temp"])
                    except (TypeError, ValueError):
                        pass

        elif typ == "DV":
            pass                            # 투표는 루트가 집계 → DC로만 반영

        elif typ == "DC":
            if nid is not None and nid not in self.confirmed:
                self.confirmed.add(nid)
                self.state[nid] = "DEAD"
                out.append(self._dc(nid, m))

        elif typ in ("MODE", "ROOT_READY"):
            pass                            # 배너류: fake만 흡수(위에서 처리)

        else:
            self.dropped_types[str(typ)] = self.dropped_types.get(str(typ), 0) + 1

        # --- 틱 경계: 노드 각인 시각이 넘어갈 때만 ---
        while self._meta_sent and self._t_now >= self._next_tick:
            out.append(self._nodes_line())
            out.append(self._stats_line())
            out.append({"type": "TICK", "t": round(self._next_tick, 3)})
            self._next_tick += self.tick_period

        return [json.dumps(o, ensure_ascii=False) for o in out]

    def _dc(self, nid: int, m: dict) -> dict:
        """DC 변환 — 좌표는 deploy_config(②), 시각은 노드 각인(③), fake는 통과(④)."""
        n = self.nodes[nid]
        # ③ 사망시각 우선순위:
        #   1) 그 노드의 Last-Gasp 자기 각인 시각 (임계를 밟은 바로 그 순간)
        #   2) 그 노드가 마지막으로 스스로 각인한 시각 (마지막 HB)
        #   3) 펌웨어 DC가 실어준 death_t_est — ★ 이건 **루트의 확정 시각**이라 통신·집계 지연이
        #      섞여 있다. 마지막 수단으로만 쓰고 출처를 표시한다.
        if self.lg_t.get(nid) is not None:
            t_death, src = self.lg_t[nid], "last_gasp_node_stamp"
        elif self.last_seen_t.get(nid) is not None:
            t_death, src = self.last_seen_t[nid], "last_heartbeat_node_stamp"
        else:
            raw = m.get("death_t_est")
            if raw is None:
                t_death, src = self._t_now, "adapter_fallback_no_stamp"
            else:
                # death_t_est 도 펌웨어가 nodeTimeSec()으로 찍은 **nt 도메인 절대값**이므로
                # 같은 랩 보정을 거쳐야 한다. 단 과거 시각이라 추적은 갱신하지 않는다.
                t_death = self._unwrap_nt(float(raw), track=False) - (self._t0 or 0.0)
                src = "firmware_dc_root_confirm_time"
            self.warnings.append(
                f"노드 {nid}: 자기 각인 시각이 없어 {src} 로 대체했다 — 이 죽음의 시각은 "
                f"통신·집계 지연을 포함하므로 방향 추정 근거로 약하다.")
        fake = max(self.fake.get(nid, 0), int(m.get("fake", 0) or 0))
        if fake:
            self.session_fake = 1
        amb = float(self.cfg.get("ambient", 25.0))
        return {"type": "DC", "id": nid, "x": n["x"], "y": n["y"],
                "death_t_est": round(float(t_death), 4),
                "last_temp": m.get("last_temp", self.temp.get(nid) or 0.0),
                # [P1] 판정 증거 — 게이트웨이의 3분기 선별이 쓴다
                "rep_peak": (self.rep_peak.get(nid) if self.rep_peak.get(nid) is not None else amb),
                # [P2] LG 유무. ★비대칭: True면 채택 구제, False면 **아무 판단도 하지 않는다**
                "had_last_gasp": int(bool(self.had_lg.get(nid))),
                "fake": fake,                       # ④ ★ 이 한 줄이 안전장치의 생명선
                "t_source": src}                    # ③ 시각 출처를 항상 명시

    def flush(self) -> list[str]:
        """스트림 종료 — 마지막 틱 하나를 강제로 내보내 잔여 DC가 프레임에 반영되게 한다."""
        if not self._meta_sent:
            return []
        out = [self._nodes_line(), self._stats_line(),
               {"type": "TICK", "t": round(max(self._t_now, self._next_tick), 3)}]
        self._next_tick = max(self._t_now, self._next_tick) + self.tick_period
        return [json.dumps(o, ensure_ascii=False) for o in out]

    # ---------- 진단 ----------
    def report(self) -> dict:
        return {"lines_in": self.n_lines, "time_source": self._time_source,
                "session_fake": self.session_fake, "confirmed": sorted(self.confirmed),
                "unknown_ids": sorted(self.unknown_ids),
                "dropped_types": dict(self.dropped_types),
                "nt_wraps": self.nt_wraps,
                "suspect_regressions": self.suspect_regressions,
                "time_regressions": self.time_regressions,
                "uptime_over_warn": sorted(self._uptime_warned),
                "nt_raw_max_s": {k: round(v, 1) for k, v in sorted(self._nt_raw_max.items())},
                "warnings": list(dict.fromkeys(self.warnings))}


def adapt_stream(fw_lines, deploy_path: str | None = None, tick_period_s: float = 1.0):
    """펌웨어 라인 이터러블 → 게이트웨이 라인 제너레이터. (어댑터도 함께 돌려준다)"""
    ad = FirmwareAdapter.from_file(deploy_path, tick_period_s=tick_period_s)

    def gen():
        for ln in fw_lines:
            for o in ad.feed(ln):
                yield o
        for o in ad.flush():
            yield o

    return gen(), ad
