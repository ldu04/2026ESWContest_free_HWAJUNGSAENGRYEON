"""engine.py — 메인 틱 루프 → 상태 스냅샷 스트림 (지시서 #1 §8).

코어는 매 틱 '직렬화 가능한 dict 스냅샷'을 산출한다(코어↔뷰 분리, [D-003]).
viz/metrics는 스냅샷만 소비한다.

사용:
    eng = Engine(cfg)
    for snap in eng.stream():   # 스트리밍(애니메이션/웹 대시보드 공용)
        ...
    summary = eng.summarize("results/metrics.csv")
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from .config import Config
from .node import NodeState
from .fire import Fire
from .network import Network, build_grid
from .verification import Verifier
from .estimator import Estimator
from .metrics import Metrics


# 스냅샷은 순수 dict. 편의를 위한 얇은 별칭.
Snapshot = dict


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.nodes = build_grid(cfg)
        self.by_id = {nd.id: nd for nd in self.nodes}
        self.fire = Fire(cfg, self.nodes)
        self.net = Network(self.nodes, cfg)
        self.verifier = Verifier(cfg, neighbors=self.net.neighbors)
        self.estimator = Estimator(cfg, neighbors=self.net.neighbors)
        self.metrics = Metrics(cfg, fire=self.fire)

        # --- 실물 괴리 환경 주입 (지시서 #2c) — 별도 rng, 세기 0이면 무영향 [D-026] ---
        self.env_rng = np.random.default_rng(cfg.seed + 13579)
        if cfg.clock_jitter_ms > 0:                       # ① 노드별 고정 클럭 오프셋 [A-1]
            for nd in self.nodes:
                if not nd.is_sink:
                    nd.clock_offset = float(self.env_rng.normal(0.0, cfg.clock_jitter_ms / 1000.0))
        # 센서 열관성 τ [#2e-3 Step 2.G, D-042] — **전용 rng**라 τ=0이면 난수를 뽑지 않아 비트 동일
        if cfg.sensor_tau_s > 0:
            trng = np.random.default_rng(cfg.seed + 31415)
            for nd in self.nodes:
                if cfg.sensor_tau_var_pct > 0:
                    if cfg.sensor_tau_var_dist == "gauss":      # [2.J-A 스펙] N(0,var) + 0.5s 클립
                        f = 1.0 + float(trng.normal(0.0, cfg.sensor_tau_var_pct))
                        nd.tau = max(0.5, cfg.sensor_tau_s * f)
                    else:                                        # 기존(균등) — [D-042] 재현용
                        f = 1.0 + float(trng.uniform(-cfg.sensor_tau_var_pct, cfg.sensor_tau_var_pct))
                        nd.tau = max(0.01, cfg.sensor_tau_s * f)
                else:
                    nd.tau = cfg.sensor_tau_s
                nd.tau_order = cfg.sensor_order
        # [2.K §3] 비화재 열원 — **전용 rng**라 세기 0이면 난수를 뽑지 않아 비트 동일
        self.benign_ids = set()
        if cfg.benign_heat_c > 0 and cfg.benign_heat_frac > 0:
            brng = np.random.default_rng(cfg.seed + 90210)
            cand = [nd.id for nd in self.nodes if not nd.is_sink]
            k = int(round(len(cand) * cfg.benign_heat_frac))
            for cid in brng.choice(cand, size=min(k, len(cand)), replace=False):
                self.by_id[int(cid)].benign_c = cfg.benign_heat_c
                self.benign_ids.add(int(cid))
        self.nonfire_ids = set()                          # ④ 비화재 사망 스케줄 [A-6]
        self.nonfire_schedule = {}
        if cfg.n_nonfire_deaths > 0:
            cand = [nd.id for nd in self.nodes if not nd.is_sink]
            k = min(cfg.n_nonfire_deaths, len(cand))
            # 화재-활성 창에 분산 → 찬 구역(전선 앞)·더운 구역(전선 뒤) 혼합으로 방어 시험
            t_upper = max(3.0, min(cfg.t_max * 0.5, 24.0))
            for cid in self.env_rng.choice(cand, size=k, replace=False):
                cid = int(cid)
                self.nonfire_schedule[cid] = float(self.env_rng.uniform(2.0, t_upper))
                self.nonfire_ids.add(cid)

    # --- 종료 조건 ---
    def _all_dead_or_isolated(self) -> bool:
        for nd in self.nodes:
            if nd.is_sink:
                continue
            if nd.state != NodeState.DEAD:
                return False
        return True

    # --- 한 틱 ---
    def _tick(self, t: float) -> Snapshot:
        cfg = self.cfg

        # ④ 비화재 사망: 예약 시각 도달 시 화선 무관하게 강제 사망(저온·last-gasp 없음) [A-6]
        if self.nonfire_schedule:
            for nid, t_d in self.nonfire_schedule.items():
                nd = self.by_id[nid]
                if nd.state != NodeState.DEAD and t >= t_d:
                    nd.state = NodeState.DEAD
                    nd.death_t = t
                    nd.nonfire = True

        self.fire.update(t)
        for nd in self.nodes:
            nd.update_temp(self.fire, t, cfg.dt)

        packets: list[dict] = []
        for nd in self.nodes:
            packets.extend(nd.step(t, cfg))

        self.net.apply_dropouts(self.rng)
        relay = self.net.collect_and_relay(packets, t)
        silent = self.net.detect_silence(t)
        deaths = self.verifier.confirm(silent, self.by_id, t)

        # ①② 시계·온도 지터: estimator가 쓰는 death_t_est에 노이즈 가산(어댑터, 추정기 불변) [D-027]
        if deaths and (cfg.clock_jitter_ms > 0 or cfg.temp_jitter_s > 0):
            for e in deaths:
                noise = self.by_id[e["id"]].clock_offset
                if cfg.temp_jitter_s > 0:
                    noise += float(self.env_rng.normal(0.0, cfg.temp_jitter_s))
                e["death_t_est"] += noise

        est = None
        if cfg.mode == "ours":
            self.net.rebuild_routes_if_changed(deaths, t)
            survivors = [(nd.id, nd.pos) for nd in self.nodes
                         if not nd.is_sink and nd.state != NodeState.DEAD]
            est = self.estimator.update(deaths, t, survivors)
            est["_predictor"] = self.estimator     # metrics가 도달예측에 사용(뷰엔 미포함)
        else:
            self.net.rebuild_routes_if_changed(deaths, t)

        self.metrics.record(t, self.nodes, relay, deaths, est, self.fire,
                             net=self.net, verifier=self.verifier)

        return self._snapshot(t, relay, est)

    def _snapshot(self, t, relay, est) -> Snapshot:
        est_view = None
        if est is not None:
            est_view = {k: v for k, v in est.items() if not k.startswith("_")}
        hud = self.metrics.rows[-1] if self.metrics.rows else {}
        return {
            "t": round(t, 3),
            "nodes": [nd.snapshot() for nd in self.nodes],
            "topology": self.net.topology(),
            "est": est_view,
            "fire_front": self.fire.front_pos(t),
            "fire_dir": self.cfg.direction(),
            "relay": relay,
            "hud": hud,
        }

    # --- 스트림 ---
    def stream(self):
        cfg = self.cfg
        t = 0.0
        # dt 부동소수 누적 오차 방지용 틱 카운트
        n_steps = int(round(cfg.t_max / cfg.dt))
        for k in range(n_steps):
            t = round(k * cfg.dt, 6)
            if self._all_dead_or_isolated():
                break
            yield self._tick(t)

    # --- 요약 ---
    def summarize(self, csv_path: str | None = None) -> dict:
        return self.metrics.summarize(csv_path, net=self.net, verifier=self.verifier)


def run(cfg: Config):
    """지시서 §8 형태의 제너레이터. 스냅샷 스트림을 yield.

    (metrics 요약이 필요하면 Engine을 직접 쓰라: eng.stream() 후 eng.summarize())
    """
    eng = Engine(cfg)
    yield from eng.stream()
