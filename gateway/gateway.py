"""gateway.py — 라즈베리파이 게이트웨이: 시리얼(JSON) → ★시뮬 estimator 재사용 → Snapshot → 대시보드.

핵심(지시서 #4 §2, [D-024]): 루트 ESP32가 보낸 JSON 라인만 소비하고, 시뮬 `sim.estimator.Estimator`를
**그대로 인스턴스화**해 방향·속도·ETA·경보를 산출한다. 출력은 engine과 **동일한 Snapshot(dict)** 이라
지시서 #3 플레이어(dashboard/index.html)가 무수정으로 재생한다.

end-to-end(HW 없이): mock_serial → gateway → dashboard.
  python gateway/mock_serial.py                        # 스트림 생성
  python gateway/gateway.py --in results/dashboard/mock_stream.jsonl --emit-dashboard
실물(Phase B~): python gateway/gateway.py --port COM5 --emit-dashboard
"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ★ 표준출력/표준오류 고정 — cp949 콘솔에서 문자 하나로 죽지 않게, 튕겨도 줄이 남게.
#   근거: docs/n07_사망시험_판정_20260901.md §7
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from sim.config import Config
from sim.estimator import Estimator          # ★ 재사용
from sim.network import Network              # 이웃 그래프 계산에 재사용
from sim.verification import Verifier        # ★ [2.M P1] 검증된 비화재사망 방어를 그대로 재사용
from sim.node import Node, NodeState
from sim.metrics import angle_deg
from serial_source import iter_lines


class Gateway:
    def __init__(self):
        self.cfg = None
        self.meta_nodes = {}          # id -> {pos, is_sink}
        self.sink_id = 0
        self.estimator = None
        self.links = []               # 정적 링크(좌표+radio_range)
        # 런타임 상태
        self.state = {}               # id -> "ALIVE|DYING|DEAD"
        self.temp = {}                # id -> temp
        self.route_edges = []
        self.gt = None                # {front, dir}
        self.stats = {"delivery_rate": 1.0, "n_dead": 0}
        self.pending_deaths = []      # 이번 틱 새 사망(estimator 투입 대기)
        self.frames = []
        # ── [2.K §2 제약④] 합성데이터 안전장치를 **로그 끝까지** 살려 보낸다 ──
        # estimator는 (x,y,t)만 받으므로 fake는 그 경로에서 반드시 소실된다.
        # 그래서 게이트웨이가 **별도 사망 대장**에 컬럼으로 남긴다. 이게 없으면
        # 펌웨어에 박은 fake=1이 대시보드·CSV까지 오지 못한다. [D-046]
        self.death_log = []           # [{id,x,y,death_t_est,last_temp,fake,t_source,...}]
        # ── [2.M P1] 실물 경로의 화재/비화재 선별 ──
        # [D-053] 조사에서 드러난 것: 펌웨어는 #2d 이전 OR 게이트고, 게이트웨이는 Verifier를
        #   아예 안 써서 DC가 estimator로 **무선별 직행**했다. 즉 실물에 선별이 0이었다.
        # 여기서 시뮬과 **같은 Verifier**를 돌린다(새 방어를 만들지 않는다 — 이식이 목적).
        self.verifier = None
        self.rep_peak = {}            # id -> 보고 온도 최고값(어댑터가 실어준 값으로 갱신)
        self.n_excluded = 0
        self.session_fake = 0         # 하나라도 합성이면 1 (안전측: 내려가지 않는다)
        # ── [D-069] 이 세션이 Ctrl-C 로 잘렸는가 ──
        #   실보드(--port auto)는 스트림이 끝나지 않아 Ctrl-C 가 유일한 종료 수단이다.
        #   그렇게 끝난 회차는 **런의 뒷부분이 통째로 없다** — 사망 16건 중 9건까지만 담긴
        #   대장을 나중에 보면 "9건만 죽었다"로 읽힌다. 그래서 fake/coord_source 와 같은 원칙으로
        #   **세션 표시 + 행 단위 컬럼** 둘 다에 박는다(안전측: 한번 1이면 안 내려간다).
        self.interrupted = 0
        self.time_source = None       # 노드 각인 시각의 출처(어댑터가 알려준다)
        # ── [D-068] 좌표의 출처. '실측'인지 '명목 격자값'인지 끝까지 달고 다닌다 ──
        #   좌표를 자로 재지 않고 명목값으로 돌려도 게이트웨이는 조용히 값을 낸다.
        #   그 결과를 실측이라고 보고하면 수치 무결성이 깨진다. 그래서 표시를 만든다.
        self.coord_source = "미상"    # 실측 | 명목(미실측) | 미상
        # ★ [2026-08-31] 어댑터가 본 시각 이상을 사망 대장까지 나른다.
        self.nt_wraps = 0                  # 랩어라운드 보정 발동 횟수
        self.suspect_time_regressions = 0  # 랩으로 설명되지 않는 시각 역행 횟수
        self.coord_warn = []
        # 런 중 대본 대조 (--schedule). 없으면 대조하지 않는다(기존 동작 그대로).
        self.schedule = None
        self._sched_anchor = None          # (첫 사망 시각, 노드id)
        self.schedule_violations = []      # [(S2|S3, id, delta)]

    # ---- [D-3] 규모 의존 상수를 물리에서 유도한다 ----
    #
    # 배경 — `docs/보고서_소재_20260827.md` (c) 규모 의존 상수 감사에서 4건이 나왔다.
    #   시뮬은 10 m 간격 / 1.5 m/s 전선(이웃 통과 6.67 s)에서 상수를 골랐는데,
    #   벤치는 0.20 m / 0.0011 m/s(이웃 통과 181.8 s)다. **시간 규모 배율 R = 27.3×**.
    #   그 배율만큼 어긋난 상수를 그대로 들고 오면 조용히 전건 실패한다
    #   (dt_window=8 s 는 벤치에서 국소 적합 16/16 전멸이었다 — 확인된 실패).
    #
    # 그래서 값을 **고르지 않고 유도한다.** 하나의 물리량 `v_front_expected` 에서 나온다.
    #   dt_window       = radio_range_m / v_front_expected    (이웃 반경을 전선이 지나는 시간)
    #   alert_horizon   = spacing_m     / v_front_expected    (한 칸 앞에서 경보)
    #   speed_true      = v_front_expected                    (별도 상수를 두지 않는다)
    #   residual_gate_s = 국소 적합 잔차의 median + 3σ         (드라이런에서 뽑아 설정에 적는다)
    #
    # ★ 하위호환: `v_front_expected` 가 없는 설정(시뮬 규모 mock 경로)은 예전 그대로
    #   dt_window/alert_horizon/speed_true 를 명시값으로 읽는다 — 회귀 비트 동일.
    def _derive_scale(self, c):
        v = c.get("v_front_expected")
        if v is None:
            return {"dt_window": c["dt_window"], "alert_horizon": c["alert_horizon"],
                    "speed_true": c["speed_true"], "residual_gate_s": None, "derived": False}
        v = float(v)
        if v <= 0:
            raise ValueError(f"v_front_expected 는 양수여야 한다(받은 값 {v}). "
                             "0 이면 dt_window/alert_horizon 이 무한이 된다.")
        d = {"dt_window": c["radio_range_m"] / v,
             "alert_horizon": c["spacing_m"] / v,
             "speed_true": v,
             "residual_gate_s": c.get("residual_gate_s"),
             "derived": True}
        print("[gateway] 규모 상수 유도 (v_front_expected = %.6g m/s):" % v)
        print("           dt_window     = radio_range_m / v = %.4g / %.6g = %.1f s"
              % (c["radio_range_m"], v, d["dt_window"]))
        print("           alert_horizon = spacing_m     / v = %.4g / %.6g = %.1f s"
              % (c["spacing_m"], v, d["alert_horizon"]))
        print("           speed_true    = v_front_expected  = %.6g m/s  (별도 상수 삭제)" % v)
        if d["residual_gate_s"] is not None:
            print("           residual_gate_s = %.1f s  (드라이런 국소적합 잔차 median+3σ, 설정에 기록)"
                  % float(d["residual_gate_s"]))
        else:
            print("           residual_gate_s = 미설정 → sim 기본값 %.1f s 를 그대로 쓴다. "
                  "★ 벤치 규모에서는 분기③이 전건 기각될 수 있다 "
                  "(scripts/derive_scale_constants.py 로 뽑아 설정에 적을 것)"
                  % Config().residual_gate_s)
        return d

    # ---- META 처리: cfg·이웃·estimator 구성 ----
    def on_meta(self, m):
        c = m["config"]
        d = self._derive_scale(c)
        self.cfg = Config(mode="ours", radio_range_m=c["radio_range_m"], dt=c["dt"],
                          alert_horizon=d["alert_horizon"], dt_window=d["dt_window"],
                          speed_true=d["speed_true"], spacing_m=c["spacing_m"])
        if d["residual_gate_s"] is not None:
            self.cfg.residual_gate_s = float(d["residual_gate_s"])
        self.sink_id = m.get("sink_id", 0)
        self.meta_nodes = {n["id"]: {"pos": (n["x"], n["y"]), "is_sink": n["is_sink"]}
                           for n in m["nodes"]}
        # 좌표+radio_range로 이웃 그래프 구성(시뮬 Network 재사용)
        nodes = [Node(id=n["id"], pos=(n["x"], n["y"]), is_sink=n["is_sink"])
                 for n in m["nodes"]]
        net = Network(nodes, self.cfg)
        self.links = net.topology()["links"]
        self.estimator = Estimator(self.cfg, neighbors=net.neighbors)
        # ★ [P1] 시뮬과 동일한 이웃 그래프 위에서 동일한 Verifier를 구성한다.
        #   [P2] 실물에는 LG 정보가 실제로 존재하므로 **여기서만** lastgasp_evidence를 켠다
        #   (시뮬 기본값은 False — 켜면 #2d~#2e-2 baseline이 바뀌므로. 의도된 분기, D-056 표 참조).
        self.cfg.lastgasp_evidence = True
        self.verifier = Verifier(self.cfg, neighbors=net.neighbors)
        self._check_measured(m.get("deployment", {}))
        self._print_deployment_check(net)
        for nid in self.meta_nodes:
            self.state[nid] = "ALIVE"
            self.temp[nid] = self.cfg.ambient
        # [2.K §2] 어댑터가 실어 보낸 세션 표시를 흡수(④ fake / ③ 시각 출처)
        if int(m.get("fake", 0) or 0):
            self.session_fake = 1
        self.time_source = m.get("time_source", self.time_source)

    # ---- [D-068] 좌표가 실측인가, 명목 격자값인가 ----
    #
    # 왜 필요한가: `deployment.measured` 는 파일에 있었지만 **아무도 읽지 않았다.**
    #   명목 격자로 돌려도 경고가 없고, 실측했다고 true 로 바꿔도 시스템은 모른다.
    #   즉 이 플래그는 지금까지 장식이었다. 읽고, 어긋나면 시끄럽게 만든다.
    def _check_measured(self, dep):
        import math as _m
        flag = dep.get("measured", None)
        rows = dep.get("grid_rows"); cols = dep.get("grid_cols"); sp = dep.get("spacing_m")
        nominal = None
        if rows and cols and sp:
            nominal = {r * cols + c: (round(c * sp, 6), round(r * sp, 6))
                       for r in range(rows) for c in range(cols)}
        same = None
        if nominal:
            same = all(nid in nominal
                       and _m.isclose(pos["pos"][0], nominal[nid][0], abs_tol=1e-6)
                       and _m.isclose(pos["pos"][1], nominal[nid][1], abs_tol=1e-6)
                       for nid, pos in self.meta_nodes.items())
        if flag is True:
            self.coord_source = "실측"
            if same:
                # 실측했다면서 좌표가 명목값과 한 자리도 안 다르다 — 둘 중 하나는 거짓이다.
                self.coord_source = "실측(의심)"
                self.coord_warn.append(
                    "measured=true 인데 좌표 16개가 명목 격자값과 **전부 일치**한다. "
                    "실측값을 옮겨 적지 않았거나 플래그를 잘못 켠 것이다.")
        elif flag is False:
            self.coord_source = "명목(미실측)"
            self.coord_warn.append(
                "좌표 미실측 — 명목 격자값 사용 중. 추정 결과를 실측으로 보고하지 말 것.")
        else:
            self.coord_source = "미상"
            self.coord_warn.append("deployment.measured 가 없다. 좌표 출처를 알 수 없다.")
        for w in self.coord_warn:
            print("[gateway] ***** 좌표 경고: %s *****" % w)
        print("[gateway] 좌표 출처 = %s" % self.coord_source)

    # ---- [침묵실패 사전점검] 배치 검산 3줄 ----
    #
    # 왜 시작 로그인가: 좌표를 잘못 적어도 게이트웨이는 **아무 소리 없이** 돈다.
    #   방향만 조용히 틀린다. 한 칸만 어긋나도 ∇T 가 통째로 돌아가는데, 그때 화면에
    #   나오는 것은 "그럴듯한 각도" 하나뿐이라 사람이 못 잡는다.
    #   그래서 추정을 시작하기 전에 **우리가 무엇을 배치했다고 믿는지**를 먼저 찍는다.
    def _print_deployment_check(self, net):
        import math as _m
        from collections import Counter as _C
        pos = {nid: v["pos"] for nid, v in self.meta_nodes.items()}
        ids = sorted(pos)
        # ① 최근접 이웃 거리의 중앙값 — 설정의 spacing_m 과 어긋나면 좌표표가 틀린 것이다
        nn = []
        for i in ids:
            ds = [_m.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]) for j in ids if j != i]
            if ds:
                nn.append(min(ds))
        nn.sort()
        med = nn[len(nn) // 2] if nn else float("nan")
        flag = "" if (not nn or abs(med - self.cfg.spacing_m) <= 0.02 * max(self.cfg.spacing_m, 1e-9))                else "  ★ 설정 spacing_m=%.3f 과 어긋난다 — 좌표표를 의심할 것" % self.cfg.spacing_m
        print("[gateway] 배치검산 ① 최근접거리 중앙값 %.3f m (노드 %d개)%s" % (med, len(ids), flag))
        # ② 이웃수 분포 — 4x4 정격자라면 {3:4(모서리), 5:8(변), 8:4(내부)} 여야 한다
        dist = dict(sorted(_C(len(net.neighbors.get(i, [])) for i in ids).items()))
        print("[gateway] 배치검산 ② 이웃수 분포 %s  (4x4 정격자 기대값 {3: 4, 5: 8, 8: 4})" % dist)
        # ③ 라벨 규약 — 대본은 nXX, 코드는 id. 한 칸 밀리면 좌표가 통째로 뒤바뀐다
        print("[gateway] 배치검산 ③ 라벨 규약  nXX -> id = XX-1  (n01->id0 … n16->id15)")

    def on_nodes(self, m):
        for nd in m["nodes"]:
            if int(nd.get("fake", 0) or 0):        # [제약④] 노드별 표시도 흘리지 않는다
                self.session_fake = 1
            self.temp[nd["id"]] = nd["temp"]
            if nd.get("rep_peak") is not None:     # [P1] 판정 재료
                self.rep_peak[nd["id"]] = max(self.rep_peak.get(nd["id"], -1e9),
                                              float(nd["rep_peak"]))
            # DEAD는 DC로만 확정. 여기선 DYING까지만 반영.
            if self.state.get(nd["id"]) != "DEAD":
                self.state[nd["id"]] = nd["state"]

    def _neighbor_max_temp(self, uid):
        """suspect의 이웃들이 보고한 온도 최고값 — 시뮬 detect_silence의 neighbor_max_temp와 같은 뜻.

        ★ 단일 노드는 이걸 계산할 수 없다(자기 온도밖에 모른다). 그래서 이 항목은
          **게이트웨이에서만** 적용된다 — 어디서 무엇을 거르는지 표는 D-056 참조.
        """
        nbrs = self.verifier.neighbors.get(uid, []) if self.verifier else []
        vals = [self.rep_peak.get(v, self.temp.get(v, self.cfg.ambient)) for v in nbrs]
        return max(vals) if vals else self.cfg.ambient

    def on_dc(self, m):
        uid = m["id"]
        self.state[uid] = "DEAD"
        # [P1] ★ estimator로 보내기 **전에** 시뮬과 같은 3분기 선별을 통과시킨다.
        if m.get("rep_peak") is not None:
            self.rep_peak[uid] = max(self.rep_peak.get(uid, -1e9), float(m["rep_peak"]))
        info = {
            "last_temp": m.get("last_temp") or 0.0,
            "rep_peak": self.rep_peak.get(uid, m.get("last_temp") or self.cfg.ambient),
            "neighbor_max_temp": self._neighbor_max_temp(uid),
            "had_last_gasp": bool(m.get("had_last_gasp")),   # [P2] 비대칭 증거
            "rep_slope": None,                                # Fix B는 비활성(배포판 기본값)
        }
        ev = self.verifier.confirm_external(uid, (m["x"], m["y"]),
                                            m["death_t_est"], info, m["death_t_est"])
        branch = self.verifier.decision_log[-1]["branch"] if self.verifier.decision_log else "?"
        if ev is not None:
            self.pending_deaths.append(ev)
        else:
            self.n_excluded += 1
        # [2.K §2 제약④] estimator로 가는 dict에는 fake가 실릴 자리가 없다(그 쪽은 불변).
        # 대장에 따로 남겨 로그·CSV까지 살려 보낸다.
        fake = int(m.get("fake", 0) or 0)
        if fake:
            self.session_fake = 1
        self.death_log.append({
            "id": uid, "x": m["x"], "y": m["y"],
            "death_t_est": m["death_t_est"], "last_temp": m.get("last_temp") or 0.0,
            "fake": fake, "t_source": m.get("t_source", "unknown"),
            # [P1/P2] 왜 채택/제외됐는지를 로그에 남긴다(사후 감사용)
            "accepted": int(ev is not None), "branch": branch,
            "rep_peak": round(float(info["rep_peak"]), 2),
            "neighbor_max_temp": round(float(info["neighbor_max_temp"]), 2),
            "had_last_gasp": int(info["had_last_gasp"]),
        })
        self._check_schedule(uid, m["death_t_est"])

    # ── [2026-09-01] 런 **도중** 대본 대조 — 중단기준 S2/S3 를 그 자리에서 잡는다 ──
    #  왜: 지금까지 게이트웨이는 대본을 몰라서 「대본보다 20초 이른 사망」을 **런이 끝난 뒤에야**
    #    알 수 있었다. 5분째에 회차가 망가진 걸 알면 남은 18분을 낭비하지 않는다.
    #  기준시각: **첫 사망 = 0**. 절대시계를 맞출 필요가 없다(대본도 같은 기준으로 만든다).
    #  문턱 20초는 절차서 §2 의 S2 정의 그대로다 — 여기에 새 숫자를 만들지 않는다.
    def _check_schedule(self, uid, t_death):
        if not self.schedule:
            return
        sched = self.schedule["death_s"]
        if str(uid) not in sched:
            print("[gateway] ***** S3: 대본에 없는 노드 n%02d 가 죽었다 — "
                  "열원이 경로 밖 노드를 스쳤다. 이 회차는 버린다 *****"
                  % (uid + 1), file=sys.stderr)
            sys.stderr.flush()
            self.schedule_violations.append(("S3", uid, None))
            return
        if self._sched_anchor is None:
            self._sched_anchor = (t_death, uid)
            first = self.schedule["order"][0]
            if uid != first:
                print("[gateway] ***** S3: 첫 사망이 n%02d 다 — 대본은 n%02d 부터다 *****"
                      % (uid + 1, first + 1), file=sys.stderr)
                sys.stderr.flush()
                self.schedule_violations.append(("S3", uid, None))
            return
        expect = self._sched_anchor[0] + float(sched[str(uid)])
        delta = t_death - expect
        if delta < -20.0:
            print("[gateway] ***** S2: n%02d 가 대본보다 %.0f초 **이르게** 죽었다 "
                  "(대본 %+.0fs). 열원이 다른 노드를 스쳤다 — 이 회차는 버린다 *****"
                  % (uid + 1, -delta, sched[str(uid)]), file=sys.stderr)
            sys.stderr.flush()
            self.schedule_violations.append(("S2", uid, round(delta, 1)))
        elif delta > 20.0:
            # 늦는 것은 S2 가 아니다(S4 후보). 버리지 않고 알리기만 한다.
            print("[gateway] 경고: n%02d 가 대본보다 %.0f초 늦게 죽었다 — 시각표가 밀리고 있다"
                  % (uid + 1, delta), file=sys.stderr)
            sys.stderr.flush()
        else:
            print("[gateway] 대본 대조 n%02d  실측 %+.0fs (대본 %+.0fs, 차 %+.1fs)"
                  % (uid + 1, t_death - self._sched_anchor[0], sched[str(uid)], delta),
                  file=sys.stderr)

    def on_route(self, m):
        self.route_edges = [tuple(e) for e in m["edges"]]

    def on_gt(self, m):
        self.gt = {"front": m["front"], "dir": m["dir"]}

    def on_stats(self, m):
        self.stats = {"delivery_rate": m["delivery_rate"], "n_dead": m["n_dead"]}
        if int(m.get("fake", 0) or 0):             # [제약④]
            self.session_fake = 1

    # ---- [2.K §2 제약④] 사망 대장 CSV — fake가 **컬럼으로** 남는 최종 지점 ----
    def write_death_log(self, path):
        import csv
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fields = ["id", "x", "y", "coord_source", "death_t_est", "last_temp", "fake", "interrupted",
                  "t_source", "accepted", "branch", "rep_peak", "neighbor_max_temp", "had_last_gasp",
                  # ★ [2026-08-31] 시각 오염을 **행마다** 남긴다. 요약에만 두면 CSV 를 잘라
                  #   붙이는 순간 사라지고, 오염된 사망 시각이 깨끗한 것처럼 유통된다.
                  "nt_wraps", "suspect_time_regressions"]
        for row in self.death_log:            # 좌표 출처를 **행마다** 박는다(헤더만 있으면 잘려 나간다)
            row.setdefault("coord_source", self.coord_source)
            # 중단도 같은 원칙 — 요약 헤더에만 두면 CSV 를 잘라 붙이는 순간 사라진다.
            row["interrupted"] = self.interrupted
            row["nt_wraps"] = self.nt_wraps
            row["suspect_time_regressions"] = self.suspect_time_regressions
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(self.death_log)
        return path

    # ---- TICK: estimator 재사용 → Snapshot 조립 ----
    def on_tick(self, t):
        survivors = [(nid, self.meta_nodes[nid]["pos"])
                     for nid in self.meta_nodes
                     if not self.meta_nodes[nid]["is_sink"] and self.state.get(nid) != "DEAD"]
        est = self.estimator.update(self.pending_deaths, t, survivors)
        self.pending_deaths = []
        est_view = {k: v for k, v in est.items() if not k.startswith("_")}

        # HUD: ground-truth가 있으면(모의) 오차도 계산, 없으면(실물) None
        dir_err = speed_err = None
        if self.gt and est.get("dir") is not None:
            dir_err = round(angle_deg(est["dir"], self.gt["dir"]), 3)
            speed_err = round(abs(est["speed"] - self.cfg.speed_true) /
                              self.cfg.speed_true * 100.0, 3)
        n_alerts = len(est["alerts"]) if est else 0

        nodes_out = []
        for nid, meta in self.meta_nodes.items():
            nodes_out.append({
                "id": nid, "pos": list(meta["pos"]), "is_sink": meta["is_sink"],
                "state": self.state.get(nid, "ALIVE"),
                "temp": round(self.temp.get(nid, 25.0), 2),
                "last_temp": round(self.temp.get(nid, 25.0), 2),
                "death_t": None,
            })

        hud = {"t": round(t, 3), "n_dead": self.stats["n_dead"],
               "delivery_rate": self.stats["delivery_rate"],
               "dir_err_deg": dir_err, "speed_err_pct": speed_err,
               "arrival_err_s": None, "n_alerts": n_alerts}

        self.frames.append({
            "t": round(t, 3), "nodes": nodes_out,
            "topology": {"links": self.links, "route_edges": [list(e) for e in self.route_edges]},
            "est": est_view,
            "fire_front": self.gt["front"] if self.gt else None,
            "fire_dir": self.gt["dir"] if self.gt else None,
            "relay": {"generated": 0, "delivered": 0},
            "hud": hud,
        })

    # ---- 라인 디스패치 ----
    def feed(self, line):
        try:
            m = json.loads(line)
        except Exception:
            return
        t = m.get("type")
        if   t == "META":  self.on_meta(m)
        elif t == "NODES": self.on_nodes(m)
        elif t == "DC":    self.on_dc(m)
        elif t == "ROUTE": self.on_route(m)
        elif t == "GT":    self.on_gt(m)
        elif t == "STATS": self.on_stats(m)
        elif t == "TICK":  self.on_tick(m["t"])

    # ---- 대시보드 페이로드(engine export와 동일 스키마) ----
    def dashboard_payload(self):
        pts = [n["pos"] for n in self.meta_nodes.values()]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        # ★ [2026-08-31] 여백은 **격자 간격에 비례**한다. 절대 미터가 아니다.
        #   예전 값 pad = 8.0 은 간격 10 m 시뮬 시절의 상수였다(= 0.8 x 간격).
        #   실물 배치는 간격 0.20 m 라 판 전체가 0.60 m 인데 여백만 8 m 라,
        #   뷰포트가 16.6 m 가 되어 노드 16개가 화면 폭의 3.6% 짜리 점으로 찍혔다.
        #   0.8 x spacing 으로 두면 10 m 격자에서 8.0 이 그대로 나와 예전 그림과 같고,
        #   0.2 m 격자에서는 0.16 m 가 되어 판이 화면을 채운다. 값을 고른 게 아니라
        #   옛 상수를 간격으로 나눠 되찾은 비율이다.
        pad = 0.8 * self.cfg.spacing_m
        ours = self.frames
        # stock 뷰: 같은 노드/경로에 추정만 제거(대시보드 토글 대비용)
        stock = [{**f, "est": None, "fire_front": None, "fire_dir": None,
                  "hud": {**f["hud"], "dir_err_deg": None, "speed_err_pct": None, "n_alerts": 0}}
                 for f in ours]
        last = ours[-1]["hud"] if ours else {}
        return {
            "meta": {
                "note": "gateway 재구성(estimator 재사용). 실물이면 ground-truth 없음.",
                "config": {"seed": "-", "grid_rows": "-", "grid_cols": "-",
                           "spacing_m": self.cfg.spacing_m, "radio_range_m": self.cfg.radio_range_m,
                           "speed_true": self.cfg.speed_true, "theta_deg": "-",
                           "alert_horizon": self.cfg.alert_horizon, "dt": self.cfg.dt},
                "nodes": [{"id": nid, "pos": list(m["pos"]), "is_sink": m["is_sink"]}
                          for nid, m in self.meta_nodes.items()],
                "fire_dir": ours[0]["fire_dir"] if ours else None,
                "bounds": {"xmin": min(xs) - pad, "xmax": max(xs) + pad,
                           "ymin": min(ys) - pad, "ymax": max(ys) + pad},
                "summary": {"ours": {"false_positives": 0,
                                     "final_dir_err_deg": last.get("dir_err_deg"),
                                     "final_speed_err_pct": last.get("speed_err_pct")},
                            "stock": {"false_positives": 0}},
            },
            "frames": {"ours": ours, "stock": stock},
        }



# ─────────────────────────────────────────────────────────────────────
# ★ [2026-08-27] 의존성 사전 점검 — 라즈베리파이 당일 사고 방지
#
# pyserial 이 없어서 실물 경로가 한 번도 안 돌았던 일이 있었다(개발 노트북).
# 파이에는 아무것도 안 깔려 있으므로 **같은 일이 데모 당일에 그대로 재현된다.**
# 그래서 시작하자마자 점검하고, 없으면 **명시적으로 죽는다.**
# 조용히 ImportError 스택트레이스를 뱉으면 현장에서 원인을 못 읽는다.
def require_deps(need_serial: bool):
    missing = []
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    if need_serial:
        try:
            import serial  # noqa: F401
        except ImportError:
            missing.append("pyserial")
    if missing:
        print("!! 필요한 패키지가 없다: " + ", ".join(missing), file=sys.stderr)
        print("   pip install -r gateway/requirements.txt", file=sys.stderr)
        print("   (라즈베리파이 Bookworm 이면 --break-system-packages 또는 venv 필요.", file=sys.stderr)
        print("    시리얼 권한: sudo usermod -a -G dialout $USER 후 재로그인)", file=sys.stderr)
        sys.exit(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src",
                    default=os.path.join("results", "dashboard", "mock_stream.jsonl"),
                    help="라인 소스: 파일경로 | 'mock' | '-'(stdin) | COMx//dev/tty* | 'auto'")
    ap.add_argument("--port", dest="port", default=None,
                    help="실보드 시리얼 포트. 'auto'(권장)면 포트를 순회하며 "
                         "role=ROOT(bridge) 인 보드를 찾는다. --in 보다 우선한다.")
    ap.add_argument("--no-port-reset", dest="port_reset", action="store_false",
                    help="시리얼 포트를 열 때 보드를 리셋하지 않는다. 기본은 리셋한다 — "
                         "리셋하면 브리지(루트)가 재부팅돼 **메시 시각이 0 으로 되돌아간다**. "
                         "이미 안정된 판을 흔들지 않고 붙고 싶을 때 쓴다.")
    ap.add_argument("--seed", type=int, default=42, help="'mock' 소스용")
    # ★ [2026-09-01] 런 도중 대본 대조. 사망이 대본과 어긋나면 **그 자리에서** 경고한다.
    #   대본은 scripts/route_table.py --emit-schedule 로 만든다(손으로 쓰지 않는다).
    #   주지 않으면 대조를 건너뛴다 — 기존 동작이 그대로 유지된다.
    ap.add_argument("--schedule", metavar="경로",
                    help="사망 대본 JSON. 주면 런 중 S2/S3 를 실시간으로 잡는다")
    ap.add_argument("--emit-dashboard", action="store_true",
                    help="dashboard용 data.js/json 산출")
    ap.add_argument("--out-js", default=os.path.join("results", "dashboard", "gateway_data.js"))
    ap.add_argument("--out-json", default=os.path.join("results", "dashboard", "gateway_snapshots.json"))
    # ---- [2.K §2] 실보드(펌웨어 방언) 입력 ----
    ap.add_argument("--fw", action="store_true",
                    help="입력이 node.ino 방언(HB/LG/ST/DV/DC/MODE)이면 어댑터를 거친다")
    ap.add_argument("--deploy", default=None,
                    help="노드 좌표 정본 deploy_config.json (--fw 전용, 기본 gateway/deploy_config.json)")
    ap.add_argument("--tick", type=float, default=1.0, help="--fw 틱 주기(초, 노드 각인 시각 기준)")
    ap.add_argument("--out-deaths", default=os.path.join("results", "dashboard", "gateway_deaths.csv"),
                    help="사망 대장 CSV(★ fake 컬럼이 남는 곳)")
    ap.add_argument("--stop-flag", default=None,
                    help="이 경로에 파일이 생기면 Ctrl-C 와 똑같이 안전 종료한다(사망대장 저장). "
                         "★ [2026-09-01] Ctrl-C 가 안 먹히는 실행 환경이 있다는 것을 실측으로 확인했다"
                         "(Git Bash 의 pty 는 Win32 콘솔이 아니라 GenerateConsoleCtrlEvent 가 무력하다). "
                         "터미널 신호에 기대지 않는 종료 경로를 하나 더 둔다.")
    args = ap.parse_args()

    if args.stop_flag:
        import threading

        def _watch_stop_flag(path, interval=0.5):
            while not os.path.exists(path):
                time.sleep(interval)
            # KeyboardInterrupt 를 메인 스레드에 주입한다 — 아래 `except KeyboardInterrupt:` 가
            # Ctrl-C 때와 완전히 같은 경로(사망대장·요약 저장)를 그대로 탄다.
            import _thread
            _thread.interrupt_main()

        threading.Thread(target=_watch_stop_flag, args=(args.stop_flag,), daemon=True).start()

    # ★ [2026-08-27] --port 가 있으면 그쪽이 소스다. 'auto' 는 COM 번호를 고정하지 않는다.
    #   시리얼을 보고하지 않는 CP210x 는 USB **경로**로 식별되므로, 다른 구멍에 꽂으면
    #   COM 번호가 바뀐다. 데모 당일 --port COM3 을 박아두면 엉뚱한 보드를 열거나 아무것도 못 읽는다.
    #   그래서 번호가 아니라 **역할(role)** 로 찾는다.
    if args.port:
        args.src = args.port

    # 소스가 시리얼이면 pyserial 이 필요하다. 파일/mock 이면 numpy 만 있으면 된다.
    need_serial = bool(args.port) or args.src == "auto"         or args.src.upper().startswith("COM") or args.src.startswith("/dev/")
    require_deps(need_serial)

    gw = Gateway()
    if args.schedule:
        with open(args.schedule, encoding="utf-8") as _f:
            gw.schedule = json.load(_f)
        _sv = gw.schedule.get("v_front_expected")
        print("[gateway] 대본 대조 켬 — %s (노드 %d개, v=%.6g)"
              % (args.schedule, len(gw.schedule["death_s"]), _sv or 0))
        # ★ 대본이 지금 설정과 다른 v 로 만들어졌으면 **대조 자체가 거짓말이 된다.**
        #   오늘 우리를 여러 번 문 「옛 값이 남아 있는」 사고를 여기서 막는다.
        if gw.cfg is None and _sv is not None:
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "deploy_config.json"), encoding="utf-8") as _g:
                    _now_v = float(json.load(_g)["config"]["v_front_expected"])
                if abs(_now_v - float(_sv)) > 1e-12:
                    print("[gateway] ***** 경고: 대본은 v=%.6g 로 만들어졌는데 설정은 %.6g 다. "
                          "대본을 다시 뽑을 것 (route_table.py --emit-schedule) *****"
                          % (_sv, _now_v), file=sys.stderr)
            except Exception:
                pass
    n = 0
    try:
        src_lines = iter_lines(args.src, seed=args.seed, port_reset=args.port_reset)
    except Exception as e:
        from serial_source import BridgeNotFound
        if isinstance(e, BridgeNotFound):
            # 조용히 빈 입력으로 도는 것이 제일 나쁘다. 시끄럽게 죽는다.
            print("!! " + str(e), file=sys.stderr)
            sys.exit(2)
        raise
    # ────────────────────────────────────────────────────────────────────
    # ★★ [2026-09-01 수정] 감시견은 **어댑터보다 앞에** 있어야 한다.
    #
    #   어젯밤 감시견 두 종을 넣었지만 **--fw 모드에서는 한 번도 울릴 수 없었다.**
    #   촬영·리허설은 전부 --fw 모드다. 즉 리허설 1회차를 날린 「23분간 무경고 침묵」이
    #   그대로 다시 일어날 수 있었다.
    #
    #   왜 그랬나: 감시견 코드가 `adapt_stream()` **뒤에** 있었다. 어댑터의 feed() 는
    #     · `line = (line or "").strip()` → 침묵 신호 None 을 빈 문자열로 만들어 버리고
    #     · JSON 파싱 실패한 쓰레기 줄을 `return []` 로 조용히 버린다
    #   그래서 감시 대상인 **침묵과 쓰레기가 감시견에 도달하기 전에 사라졌다.**
    #
    #   증거: tools/test_watchdogs.py — 같은 합성 스트림으로
    #     --fw 없음 → 침묵·폭주 둘 다 경고 발생 / --fw 있음 → 둘 다 무반응.
    #
    #   고침: 원시 라인을 감시하는 제너레이터로 **먼저** 감싸고, 그 출력을 어댑터에 넣는다.
    #   None 은 그대로 통과시킨다 — 어댑터가 알아서 무시한다(feed(None) → []).
    # ────────────────────────────────────────────────────────────────────
    # ★★ [2026-09-01] 20.0 → 40.0. HEARTBEAT_MS 가 1000 → 10000 이 되면서 따라 움직인 값이다.
    #
    #   이 감시견은 「브리지에서 프레임이 **하나도** 안 온다」를 잡는다. 문턱을 하트비트
    #   주기의 몇 배로 잡느냐의 문제다. 20초는 **2주기뿐**이라 여유가 없다 —
    #   런 끝으로 갈수록 살아 있는 노드가 줄어 프레임원이 브리지 자기 하트비트 하나만
    #   남는데, 그때 20초 창에 기대 프레임이 **1.96개**다. 두 번 밀리면 바로 울린다.
    #   울려서는 안 될 때 울리는 경보는 진짜 경보를 묻는다.
    #
    #   40초 = **4주기**. 펌웨어의 SILENCE_TIMEOUT_MS 가 3주기인 것과 같은 규약이고,
    #   호스트 경로(시리얼)가 한 겹 더 있으므로 한 주기를 더 뒀다.
    #   대가: 브리지가 진짜 죽었을 때 아는 데 최대 40초. 런 25:48 의 2.6%다.
    HEARTBEAT_S_EXPECTED = 10.0        # firmware/node/config.h HEARTBEAT_MS 와 맞출 것
    silence_warn_s = 4 * HEARTBEAT_S_EXPECTED
    junk_win_s = 10.0

    # ── 힙 조기경보 문턱 — **여기가 유일한 정의 지점이다** ─────────────────
    #  출처(전부 실측): docs/실측값_대장.md:90-91 · docs/n07_사망시험_판정_20260901.md §3
    #    · 부팅 직후 max_alloc = 110,580 B
    #    · 크래시 **두 번 다** 직전 max_alloc = 40,948 B (관측 최저)
    #    · 크래시 uptime 24.5분 · 42.8분 — 단 **구 펌웨어(1 Hz · 15 msg/s)** 기준이다
    #  ★ 브리지는 HEAP 줄을 5초마다 보내고 있었는데 게이트웨이가 버리고 있었다
    #    (fw_adapter 의 dropped_types 로 셈만 됐다). **예고 신호가 오는데 아무도 안 봤다.**
    #  ★ 이 숫자들을 다른 곳에 복제하지 않는다. 바꿀 일이 생기면 여기만 고친다.
    HEAP_WARN_B = 60000        # 정상(110k)과 크래시선(41k) 사이 — 여유 있는 경고선
    HEAP_CRIT_B = 45000        # 관측된 크래시 직전값(40,948) 바로 위 — 임박

    def watch_raw(src):
        """원시 시리얼 라인을 세면서 그대로 흘려보낸다. 침묵·폭주·힙고갈을 여기서 잡는다."""
        last_data = time.time()
        warned_at = 0.0
        win_t0 = time.time()
        win_ok = win_bad = 0
        junk_warned_at = 0.0
        # ★ 경고와 위험은 **타이머를 따로 둔다.** 하나로 두면 먼저 울린 경고가
        #   그다음 위험 경보를 간격제한으로 막아버린다 — 합성 시험에서 실제로 그랬다.
        #   가장 중요한 경보가 덜 중요한 경보에 가려지면 안 된다.
        heap_warn_at = heap_crit_at = 0.0
        for line in src:
            now = time.time()
            # ── 힙 조기경보 ── 브리지 크래시는 갑자기 오지 않는다. max_alloc 이 먼저 주저앉는다.
            if line and '"HEAP"' in line:
                try:
                    _ma = json.loads(line).get("max_alloc")
                    if isinstance(_ma, (int, float)):
                        if _ma < HEAP_CRIT_B and now - heap_crit_at >= 20.0:
                            heap_crit_at = now
                            print("[gateway] ***** 위험: 브리지 max_alloc %d B — 크래시 임박 "
                                  "(실측 크래시 직전값 40,948). 런을 마치는 것을 우선하라 *****"
                                  % _ma, file=sys.stderr)
                            sys.stderr.flush()
                        elif _ma < HEAP_WARN_B and now - heap_warn_at >= 60.0:
                            heap_warn_at = now
                            print("[gateway] ***** 경고: 브리지 max_alloc %d B "
                                  "(부팅 직후 110,580) — 힙이 줄고 있다 *****"
                                  % _ma, file=sys.stderr)
                            sys.stderr.flush()
                except Exception:
                    pass          # 계측이 런을 방해하지 않는다
            if now - win_t0 >= junk_win_s:
                tot = win_ok + win_bad
                if tot >= 50 and win_bad > 3 * win_ok and now - junk_warned_at >= 30.0:
                    junk_warned_at = now
                    print("[gateway] ***** 경고: 최근 %.0f초에 깨진 줄 %d / 정상 %d —"
                          " 시리얼이 물렸다. USB 재삽입 또는 드라이버 재바인딩이 필요하다 *****"
                          % (junk_win_s, win_bad, win_ok), file=sys.stderr)
                    sys.stderr.flush()
                win_t0, win_ok, win_bad = now, 0, 0
            if line is None:
                quiet = now - last_data
                if quiet >= silence_warn_s and now - warned_at >= silence_warn_s:
                    warned_at = now
                    print("[gateway] ***** 경고: %.0f초째 브리지에서 프레임이 없다 —"
                          " 브리지 재부팅/메시 이탈 의심 *****" % quiet, file=sys.stderr)
                    sys.stderr.flush()
                yield None
                continue
            last_data = now
            if line.startswith("{") and line.endswith("}"):
                win_ok += 1
            else:
                win_bad += 1
            yield line

    src_lines = watch_raw(src_lines)

    adapter = None
    if args.fw:
        from fw_adapter import adapt_stream
        src_lines, adapter = adapt_stream(src_lines, args.deploy, tick_period_s=args.tick)
    # ★ Ctrl-C 를 받아도 **읽은 데까지로** 산출물을 쓴다.
    #   왜: --port auto 는 스트림이 끝나지 않으므로 Ctrl-C 가 유일한 종료 수단인데,
    #   예전에는 그 자리에서 KeyboardInterrupt 가 그대로 터져 아래의 요약·사망대장 CSV·
    #   대시보드가 **하나도** 안 나왔다. 20분짜리 런의 산출물이 통째로 사라진다.
    try:
        for line in src_lines:
            if line is None:                 # 침묵 신호는 감시견이 이미 처리했다
                continue
            gw.feed(line); n += 1
    except KeyboardInterrupt:
        gw.interrupted = 1
        print("", file=sys.stderr)          # Ctrl-C 가 찍은 ^C 와 줄을 나눈다
        print("[gateway] ***** 중단(Ctrl-C) — 읽은 데까지로 산출물을 쓴다 *****",
              file=sys.stderr)

    print(f"[gateway] 처리 라인 {n}, 재구성 프레임 {len(gw.frames)}")
    if adapter:
        rep = adapter.report()
        # META 는 **첫 유효 라인에서 1회** 나가므로, 그 시점엔 DC 를 아직 못 봐서 시각 출처가 비어 있다.
        # 세션 전체를 본 어댑터의 최종 판정으로 채운다(종료 요약이 "미상"으로 나오는 것을 막는다).
        gw.time_source = gw.time_source or rep["time_source"]
        print(f"[adapter] 펌웨어 라인 {rep['lines_in']} · 시각출처={rep['time_source']} · "
              f"확정사망 {len(rep['confirmed'])} · 미등록ID {rep['unknown_ids'] or '없음'}")
        for w in rep["warnings"]:
            print(f"[adapter] ⚠ {w}")
        # ★ [2026-08-31] 시각 이상은 조용히 넘기지 않는다 — 산출물과 화면 양쪽에 남긴다.
        gw.nt_wraps = rep.get("nt_wraps", 0)
        gw.suspect_time_regressions = rep.get("suspect_regressions", 0)
        for r in rep.get("time_regressions", []):
            print(f"[adapter] ⏱ 시각 역행 #{r['n']} · {r['prev_raw_s']}s → {r['new_raw_s']}s "
                  f"(감소 {r['drop_s']}s · 랩주기와 {r['mismatch_s']}s 차) → {r['classified']}"
                  + (f" · 주입 오차 약 {r['injected_error_s']:+.1f}s"
                     if r["classified"] != "WRAP" else ""))
        if gw.suspect_time_regressions:
            print("[gateway] ***** 랩어라운드로 설명되지 않는 시각 역행 "
                  f"{gw.suspect_time_regressions}건. 이 회차의 사망 시각은 오염됐을 수 있다 — "
                  "그대로 결과로 쓰지 말 것. *****")
        if rep.get("uptime_over_warn"):
            print("[gateway] ***** uptime 40분 초과 노드: "
                  f"{rep['uptime_over_warn']} — 런 전 전원 재인가 규칙을 지키지 않았다. *****")
    # ★ [제약④] 합성/실측 표시를 사람이 놓칠 수 없게 최종 출력에 박는다
    if gw.session_fake:
        print("[gateway] *** WARNING: fake=1 — 이 세션의 데이터는 합성(SYNTHETIC)이다. "
              "실측 탐지 근거로 쓰지 말 것. [D-046] ***")
    else:
        print("[gateway] fake=0 (실센서 경로)")
    if gw.verifier is not None:
        n_acc = sum(d["accepted"] for d in gw.death_log)
        print(f"[gateway] 비화재 선별: 후보 {len(gw.death_log)} → 채택 {n_acc} / 제외 {gw.n_excluded}")
        from collections import Counter
        for br, c in Counter(d["branch"] for d in gw.death_log).most_common():
            print(f"           {br:24s} {c}건")
    if gw.death_log:
        p = gw.write_death_log(args.out_deaths)
        nf = sum(d["fake"] for d in gw.death_log)
        print(f"[gateway] 사망 대장 → {p}  (총 {len(gw.death_log)}건, fake=1 {nf}건)")
    # ---- [침묵실패 사전점검] 종료 요약 2줄 ----
    #
    # 왜 종료 로그인가: 위의 줄들은 정상일 때도 늘 나와서 눈이 미끄러진다.
    #   **끝에 딱 두 줄**로, 이 세션이 무엇을 근거로 판단했는지 요약한다.
    #   특히 t_source 가 `root_confirm_time_UNRELIABLE` 이면 그 사망의 시각은
    #   죽은 노드 자신이 찍은 것이 아니라 루트의 확정 시각이다 — 제약③ 위반이고,
    #   침묵 감지(3 s) + 투표 집계 지연이 통째로 섞여 ∇T 를 오염시킨다.
    #   한 건이라도 있으면 **그 회차는 방향 근거로 쓰면 안 된다.**
    from collections import Counter as _C2
    _n_acc = sum(d["accepted"] for d in gw.death_log) if gw.death_log else 0
    _n_rej = len(gw.death_log) - _n_acc if gw.death_log else 0
    _ts = _C2(d.get("t_source", "?") for d in gw.death_log) if gw.death_log else _C2()
    _unrel = sum(v for k, v in _ts.items() if "UNRELIABLE" in str(k))
    print("[요약] 사망 %d건 → 채택 %d / 기각 %d · 세션시각출처=%s · fake=%d · 좌표출처=%s · 중단=%d"
          % (len(gw.death_log), _n_acc, _n_rej, gw.time_source or "미상", gw.session_fake,
             gw.coord_source, gw.interrupted))
    if gw.interrupted:
        print("[요약] ***** 중단된 회차 — 이 산출물은 런의 앞부분뿐이다. "
              "사망 건수를 '전부'로 읽지 말 것 *****")
    for _w in gw.coord_warn:
        print("[요약] ***** 좌표 경고: %s *****" % _w)
    print("[요약] t_source %s · UNRELIABLE %d건%s"
          % (dict(_ts) or "없음", _unrel,
             "  ★ 제약③ 위반 — 이 회차는 방향 근거로 쓰지 말 것" if _unrel else ""))

    if gw.frames:
        last = gw.frames[-1]
        e = last["est"]
        if e and e.get("dir"):
            print(f"[gateway] estimator 재사용 결과(최종): "
                  f"방향오차={last['hud']['dir_err_deg']}°, 속도오차={last['hud']['speed_err_pct']}%, "
                  f"사망={last['hud']['n_dead']}, 경보={last['hud']['n_alerts']}")

    if args.emit_dashboard and gw.cfg is None:
        # META 전에 끊기면 cfg 가 없어 dashboard_payload() 가 AttributeError 로 터진다.
        # 여기까지 와서 죽으면 위에서 애써 쓴 CSV 가 있어도 "실패한 실행"으로 보인다.
        print("[gateway] ⚠ META 를 한 번도 못 받아 대시보드 데이터를 만들 수 없다 "
              "(중단이 너무 일렀거나 --fw 를 빠뜨렸다). 대시보드만 건너뛴다.", file=sys.stderr)
    elif args.emit_dashboard:
        payload = gw.dashboard_payload()
        os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        with open(args.out_js, "w", encoding="utf-8") as f:
            f.write("window.SNAPSHOTS = ")
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            f.write(";\n")
        print(f"[gateway] 대시보드 데이터 → {args.out_js}")


if __name__ == "__main__":
    main()
