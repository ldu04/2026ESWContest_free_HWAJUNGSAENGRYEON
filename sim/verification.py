"""verification.py — 통신두절 vs 사망 판정 (오탐 방어, 지시서 #1 §5, #2d 3분기 선별).

"조용해진 노드"가 진짜 파괴인지 일시적 링크 끊김인지 구분(rule1 다수결·rule3 지속성).
그 위에 **화재사망 vs 비화재사망**을 가려 estimator에 넣을지 결정(#2d).

[#2d] 규칙2(온도)를 OR게이트에서 **3분기 선별**로 교체 [D-029] (estimator 수학은 불변):
  ① 자기(보고) 온도가 상승(rep_peak ≥ warn_temp) → 화재사망 = 채택
  ② 자기 온도 이력 있는데 상승 없음 → 비화재사망 = 제외(노드 손실·라우팅은 정상)
  ③ 자기 저온 + 이웃 고온 → 도착시각 평면 residual 정합이면 잠정 채택, 이상치면 제외
config.nonfire_gate=False 면 기존 OR게이트(비교용).

[#2e-2] 분기③에서 accepted 이웃 <min_samples 라 residual을 못 구하는 경우가 COOL 비화재 누수의 98.9%였다
(#2e-1 진단). 그 지점만 `_sample_poor()`로 분리하고 세 동작을 config 플래그로 고른다 [D-033]:
  **기본 = Fix A `nonfire_strict_gate=True`** — 증거를 못 구하면 제외 [D-036 채택]
  Fix B `dtdt_gate` = 메시가 수신한 보고 온도의 상승률 dT/dt로 판정(현재 비활성, #2e-3에서 재검토)
  둘 다 off = [D-030] 레거시 관대 채택(#2d까지의 동작, 비교용 보존)
estimator 평면적합 수학은 이번에도 불변 — 바뀐 건 "어떤 죽음을 넣을지"뿐.
"""
from __future__ import annotations

import numpy as np

from .node import NodeState


class Verifier:
    def __init__(self, cfg, neighbors: dict[int, list[int]] | None = None):
        self.cfg = cfg
        self.neighbors = neighbors or {}
        self.confirmed: set[int] = set()          # 화재사망으로 확정(estimator 채택)
        self.excluded_nonfire: set[int] = set()   # 사망이나 비화재로 분류(estimator 제외)
        self.false_positives: int = 0             # 살아있는데 확정(헤드라인 오탐)
        self.confirm_log: list[dict] = []
        self.accepted: dict[int, tuple] = {}      # id -> (x,y,t) 화재사망(residual 적합용)
        self.residual_log: list[float] = []       # 진단: 채택 화재사망들의 residual 분포
        self.sample_poor_log: list[dict] = []     # 진단(#2e-2): 분기③ 표본부족 판정 기록
        self.decision_log: list[dict] = []        # [P1] 실물 경로 판정 기록(어느 분기가 걸렀나)
        self.residual_n_log: list[int] = []       # [2.N §3] residual 적합에 실제로 쓰인 표본 수

    # --- 도착시각 평면 residual: 후보 죽음이 국소 화선 평면에 맞는가 ---
    def _residual(self, uid, pos, t_est):
        acc = [self.accepted[j] for j in self.neighbors.get(uid, []) if j in self.accepted]
        # [2.N §3] 분기③ 전용 하한. None이면 min_samples 폴백(비트 동일).
        need = (self.cfg.residual_min_samples
                if getattr(self.cfg, "residual_min_samples", None) is not None
                else self.cfg.min_samples)
        if len(acc) < need:
            return None                           # 표본 부족 → 판정 불가(관대 채택) [D-030]
        self.residual_n_log.append(len(acc))       # 진단: 적합에 쓰인 표본 수
        A = np.array([[x, y, 1.0] for (x, y, _t) in acc])
        b = np.array([tt for (_x, _y, tt) in acc])
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        pred = sol[0] * pos[0] + sol[1] * pos[1] + sol[2]
        return abs(t_est - pred)

    # --- 분기③에서 residual 표본이 부족할 때의 판정 (#2e-2) ---
    def _sample_poor(self, uid, info) -> bool:
        """accepted 이웃 <min_samples 라 시공간 정합을 못 쓸 때 무엇을 할 것인가.

        ★ **기본 = Fix A `nonfire_strict_gate=True`** — 시공간 증거를 못 구하면 **제외**한다 [D-036].
          Fix B `dtdt_gate`: 자기 **보고 온도 상승률**로 판정. 가파르면 화재, 평평하면 비화재.
            dT/dt조차 없으면(보고 2건 미만 = dropout 등) 관대 채택으로 되돌아간다 — 증거 없이 버리지 않기 위해.
            (현재 비활성. 임계가 전선 속도에 비례해 ≥0.8 m/s에서만 유효 → #2e-3에서 속도 스케일링과 재검토.)
          둘 다 off = [D-030] **레거시 관대 채택**(#2d까지의 동작). 비교·회귀 확인용으로 보존.
        둘 다 켜지면 더 보수적인 Fix A가 이긴다(A는 이미 무조건 제외라 AND의 결과와 같다).
        """
        cfg = self.cfg
        if cfg.nonfire_strict_gate:                      # Fix A — 증거 없으면 제외
            self.sample_poor_log.append({"uid": uid, "slope": info.get("rep_slope"),
                                         "accepted": False, "by": "strict"})
            return False
        if cfg.dtdt_gate:                                # Fix B — 자기 상승률로 판정
            sl = info.get("rep_slope")
            ok = True if sl is None else (sl >= cfg.dtdt_min_c_per_s)
            self.sample_poor_log.append({"uid": uid, "slope": sl,
                                         "accepted": ok, "by": "dtdt_na" if sl is None else "dtdt"})
            return ok
        self.sample_poor_log.append({"uid": uid, "slope": info.get("rep_slope"),
                                     "accepted": True, "by": "lenient"})   # [D-030] 기존 동작
        return True

    # ── [P1] 시뮬과 실물이 **같은 규칙**을 쓰도록 분리한 순수 판정부 ──
    # 이 함수가 배포판 기본 방어의 정본이다(#2d 3분기 [D-029] + #2e-2 Fix A [D-036]).
    # 시뮬(`confirm`)과 실물(`confirm_external`, 게이트웨이)이 **둘 다 여기를 통과**한다.
    # ★ 새 방어를 발명하지 않는다 — 기존 분기 순서·비교연산을 그대로 옮겼을 뿐이며,
    #   `lastgasp_evidence`가 꺼진 기본 조건에서는 리팩터 전과 **비트 동일**하다(회귀로 확인).
    def _classify(self, uid, pos, death_t_est, info, neighbor_hot) -> tuple[bool, str]:
        cfg = self.cfg
        if not cfg.nonfire_gate:                          # (비교용) 기존 OR 게이트
            return ((info["last_temp"] >= cfg.warn_temp) or neighbor_hot), "orgate"

        # ── [P2] Last-Gasp 증거 — ★**비대칭**으로만 쓴다 ──
        # 근거(명세 §8): 온도 임계 하나가 방아쇠와 판별자를 겸할 수 없다. LG는 온도 보고와 독립인
        #   "죽기 직전 스스로 신호를 보냈다"는 **양성 증거**이고, 펌웨어는 LG를 **임계(80 ℃)를 밟은
        #   순간에만** 낸다. 즉 LG 수신 = 그 노드가 스스로 사망 임계를 넘었다고 보고한 것이다.
        # ★ 비대칭 규칙:
        #   · LG 있음 → 열적 사망의 강한 증거. rep_peak이 유실·정체됐어도 분기①로 **구제**한다.
        #   · LG 없음 → **아무것도 하지 않는다.** 화재가 너무 빨라 LG를 못 보냈거나 패킷이 유실됐을
        #     수 있으므로, 없다고 비화재로 단정하면 **진짜 화재를 버린다(미탐지)**.
        #   대칭 규칙(LG 없으면 기각)으로 만들면 미탐지가 생긴다 — 그래서 하지 않는다.
        # 배터리 소진·크래시로 죽은 노드는 애초에 LG를 못 보내므로 이 경로로 구제되지 않는다.
        if cfg.lastgasp_evidence and info.get("had_last_gasp"):
            return True, "branch1_last_gasp"

        # #2d 3분기 [D-029] (residual-on-all은 바람 baseline 열화로 기각, [D-031])
        self_hot = info.get("rep_peak", info["last_temp"]) >= cfg.warn_temp
        if self_hot:                                      # ① 자기 온도 상승 → 화재(채택)
            return True, "branch1_self_hot"
        if neighbor_hot:                                  # ③ 자기 저온+이웃 고온 → residual 정합
            r = self._residual(uid, pos, death_t_est)
            if r is not None:
                return (r <= cfg.residual_gate_s), "branch3_residual"
            return self._sample_poor(uid, info), "branch3_sample_poor"
        return False, "branch2_both_cold"                 # ② 자기·이웃 모두 저온 → 비화재 제외

    # ── [P1] 실물 경로용 진입점 ──
    def confirm_external(self, uid: int, pos, death_t_est: float, info: dict,
                         t: float) -> dict | None:
        """rule1(K표 다수결)은 **펌웨어가 이미 수행**했으므로 3분기 선별만 적용한다.

        시뮬의 `confirm`과 **같은 `_classify`·`_residual`·`_sample_poor`·`accepted` 장부**를 쓴다.
        반환: 채택되면 estimator에 넣을 이벤트 dict, 제외되면 None.
        """
        if uid in self.confirmed or uid in self.excluded_nonfire:
            return None
        neighbor_hot = info.get("neighbor_max_temp", self.cfg.ambient) >= self.cfg.warn_temp
        is_fire, branch = self._classify(uid, pos, death_t_est, info, neighbor_hot)
        self.decision_log.append({"id": uid, "branch": branch, "accepted": int(is_fire),
                                  "rep_peak": info.get("rep_peak"),
                                  "neighbor_max_temp": info.get("neighbor_max_temp"),
                                  "had_last_gasp": int(bool(info.get("had_last_gasp")))})
        if not is_fire:
            self.excluded_nonfire.add(uid)
            return None
        self.confirmed.add(uid)
        self.accepted[uid] = (pos[0], pos[1], death_t_est)
        r = self._residual(uid, pos, death_t_est)
        if r is not None:
            self.residual_log.append(r)
        return {"id": uid, "pos": pos, "death_t_est": death_t_est,
                "last_temp": info.get("last_temp", 0.0)}

    def confirm(self, silence_info: dict, nodes_by_id: dict, t: float) -> list[dict]:
        cfg = self.cfg
        new_events: list[dict] = []

        for uid, info in silence_info.items():
            if uid in self.confirmed or uid in self.excluded_nonfire:
                continue
            node = nodes_by_id[uid]

            # rule1 다수결(성긴 노드는 가진 이웃 전원)
            if len(info["observers"]) < min(cfg.K_confirm, info["n_neighbors"]):
                continue
            # rule3 지속성은 observers 산정(>silence_timeout)에 포함됨.

            death_t_est = info.get("best_heard", t - cfg.silence_timeout)
            pos = node.pos
            neighbor_hot = info["neighbor_max_temp"] >= cfg.warn_temp

            # --- 규칙2: 화재 vs 비화재 판정 ---
            # [P1] 판정은 `_classify` 한 곳으로 모았다 — 실물(게이트웨이)이 **같은 규칙**을 쓰게 하려고.
            #   분기 순서·비교연산은 이전과 동일하므로 기본 조건에서 비트 동일하다(회귀로 확인).
            is_fire, _branch = self._classify(uid, pos, death_t_est, info, neighbor_hot)

            if not is_fire:
                self.excluded_nonfire.add(uid)                # 사망이나 화선 추정 제외
                continue

            # --- 화재사망 확정 ---
            self.confirmed.add(uid)
            self.accepted[uid] = (pos[0], pos[1], death_t_est)
            r = self._residual(uid, pos, death_t_est)
            if r is not None:
                self.residual_log.append(r)

            new_events.append({
                "id": uid, "pos": pos,
                "death_t_est": death_t_est, "last_temp": info["last_temp"],
            })

            true_dead = (node.state == NodeState.DEAD) or (node.death_t is not None)
            if not true_dead:
                self.false_positives += 1
            self.confirm_log.append({
                "id": uid, "t_confirm": t, "death_t_est": death_t_est,
                "true_death_t": node.death_t, "true_dead": true_dead,
            })

        return new_events
