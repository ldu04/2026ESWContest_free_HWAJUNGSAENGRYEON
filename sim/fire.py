"""fire.py — 화재 확산 ground-truth 모델 (지시서 #1 §3, #2 스트레스, #2b 에러바 수선).

1차 모델: 직선 전선. 옵션: 방사형(radial), 바람(θ 요동), 돌풍(속도 변동), 방사-바람 결합(비등방).

시변(방향·속도)이면 `front = start + n·s·t`(상수 가정)가 부정확하므로 전선 궤적을
**틱 그리드 중점적분**으로 미리 계산한다. [D-012]

[#2b] 바람 섭동(θ 요동·속도 변동)은 **시드 의존 랜덤 실현**(랜덤 위상·성분의 소수 푸리에 합)으로
생성한다. 세기 knob은 그대로, 실현만 시드별로 다르다 → 에러바가 진짜 통계. [D-016]
세기 0이면 섭동항 0 → S1 baseline과 정확히 동일(회귀 안전).

[#2b] 방사형은 바람과 결합해 비등방 확산: 참 국소 속도 = base·(1 + wind_bias·cos(φ−wind_dir)). [D-017]

참 도착시각 T_true(p): 명목(θ0·s0, 방사형은 비등방 국소속도) 기준선. 추정기가 '평균 전선'을
얼마나 복원하는지가 평가 대상.
"""
from __future__ import annotations

import math
import numpy as np


class Fire:
    _N_COMP = 4                                   # 바람 섭동 푸리에 성분 수
    _FREQS = np.linspace(0.08, 0.55, _N_COMP)     # 저주파 대역(고정), 위상·진폭만 랜덤
    _RNG_OFFSET = 424242                          # dropout·배치 스트림과 독립 [D-016]

    def __init__(self, cfg, nodes=None):
        self.cfg = cfg
        self.speed = cfg.speed_true                       # 명목 속도 s0
        self.n0 = np.array(cfg.direction(), dtype=float)  # 명목 진행 단위벡터
        self.wind_dir = cfg.theta_rad()                   # 바람 방향(방사 비등방 기준)
        self.start = np.array(self._resolve_start(cfg, nodes), dtype=float)
        self.radial = cfg.radial_fire
        self._dt = cfg.dt
        self._t = 0.0

        # ── [2.L §4] 타원 전선 (Alexander 1985 형상 모델) ────────────────────────
        # 발화점을 **뒤쪽 초점**에 둔 타원이 자기닮음으로 자란다. 단위시간 타원을
        #   a=1, b=1/k, c=√(1−1/k²)   (k = L/B)
        # 로 두면, 발화점 기준 좌표 (x=풍하 성분, r=거리)에서 도착시각이 **닫힌 형태**로 나온다:
        #       T(p) = (a·r − c·x) / b²        ← 아래 _ellipse_T가 이 식(+속도 스케일)
        # 유도: 시각 t의 경계는 중심 (c·t,0)·반축 (a·t, b·t) 타원이므로
        #   (x−ct)²/a² + y²/b² = t²  를 t에 대해 풀면 위 식이 나온다(c²+b²=a² 사용).
        # 검산: 풍하축 x=r → 속도 a+c(선단), 풍상축 → a−c(후미), 측면 x=0 → b²/a.
        #       ⇒ 선단/후미 = (a+c)/(a−c), 장단축비 = a/b = k. k=1이면 원(=방사형)과 동일.
        # speed_true 는 **선단 확산속도**로 해석한다.
        self.shape = getattr(cfg, "fire_shape", "line")
        if self.shape == "ellipse":
            k = cfg.lb_ratio()
            self._k = k
            self._ea = 1.0
            self._eb = 1.0 / k
            self._ec = math.sqrt(max(0.0, 1.0 - 1.0 / (k * k)))
            # 단위시간 선단속도 = a+c → 실제 선단속도가 speed_true가 되도록 시간 스케일
            self._escale = (self._ea + self._ec) / self.speed

        # 시드 의존 바람 실현(θ 요동·속도 변동 각각 독립 프로세스) [D-016]
        rng = np.random.default_rng(cfg.seed + self._RNG_OFFSET)
        self._theta_proc = self._make_process(rng)
        self._speed_proc = self._make_process(rng)

        # 비화(spot fire): 진행 중 앞쪽에 생기는 새 발화점 [지시서 #2c A-5]
        self._spots = self._make_spots(cfg, nodes)

        # 타원은 도착시각이 **닫힌 형태**라 틱 그리드 궤적이 필요 없다.
        # (t_max를 크게 잡으면 _build_trajectory가 t_max/dt 개의 위치를 만들어 그대로 멈춘다 —
        #  실제로 t_max=1e6에서 천만 개를 만들다 걸렸다.)
        if self.shape == "ellipse":
            self._positions = np.array([self.start])
            self._radii = np.array([0.0])
        else:
            self._build_trajectory()

    # --- 비화 발화점 생성(별도 rng → 세기 0이면 무영향) ---
    def _make_spots(self, cfg, nodes):
        if cfg.n_spot_fires <= 0:
            return []
        if nodes:
            pts = np.array([nd.pos for nd in nodes], dtype=float)
        else:
            pts = np.array([(c * cfg.spacing_m, r * cfg.spacing_m)
                            for r in range(cfg.grid_rows) for c in range(cfg.grid_cols)],
                           dtype=float)
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        srng = np.random.default_rng(cfg.seed + 24680)
        spots = []
        for _ in range(cfg.n_spot_fires):
            t_ig = float(srng.uniform(2.0, max(3.0, cfg.t_max * 0.6)))
            px = float(srng.uniform(lo[0], hi[0]))
            py = float(srng.uniform(lo[1], hi[1]))
            spots.append((t_ig, np.array([px, py])))
        return spots

    def _temp_from_d(self, d: float) -> float:
        """전선까지의 부호 거리 d(+ = 전선 앞/미연소)로부터 온도.

        [#2e-3 2.I-a] `burn_scale_m > 0` 이면 전선 **뒤쪽(d ≤ 0)**에서도 지수로 식는다
        → 온도가 산 모양 **펄스**가 되고, 느린 센서의 감쇠→검출 실패를 시험할 수 있다.
        `burn_scale_m == 0` 이면 기존과 동일하게 통과 후 peak을 영구 유지한다(비트 동일).
        """
        cfg = self.cfg
        if d > 0:
            return cfg.ambient + (cfg.peak - cfg.ambient) * math.exp(-d / cfg.warm_scale)
        if cfg.burn_scale_m > 0:
            return cfg.ambient + (cfg.peak - cfg.ambient) * math.exp(d / cfg.burn_scale_m)
        return cfg.peak

    # --- 시작점(점화원/전선 진입) 결정 ---
    def _resolve_start(self, cfg, nodes):
        if cfg.fire_start is not None:
            return cfg.fire_start
        if nodes:
            pts = np.array([nd.pos for nd in nodes], dtype=float)
        else:
            pts = np.array(
                [(c * cfg.spacing_m, r * cfg.spacing_m)
                 for r in range(cfg.grid_rows) for c in range(cfg.grid_cols)],
                dtype=float,
            )
        proj = pts @ np.array(cfg.direction())
        i_min = int(np.argmin(proj))
        margin = cfg.spacing_m * 0.5
        return tuple(pts[i_min] - np.array(cfg.direction()) * margin)

    # --- 시드 의존 랜덤 섭동 프로세스 ---
    def _make_process(self, rng):
        """랜덤 위상·성분 진폭의 푸리에 합. 프로세스 분산=1로 정규화(세기 knob이 std를 정함)."""
        phases = rng.uniform(0.0, 2.0 * math.pi, self._N_COMP)
        amps = np.abs(rng.normal(size=self._N_COMP))
        # 랜덤 위상 사인 합의 분산 = 0.5·Σamps² → 분산 1이 되게 정규화
        denom = math.sqrt(0.5 * float(np.sum(amps ** 2))) or 1.0
        amps = amps / denom
        return (self._FREQS, phases, amps)

    def _proc_value(self, proc, t: float) -> float:
        freqs, phases, amps = proc
        return float(np.sum(amps * np.sin(freqs * t + phases)))

    # --- 시변 방향·속도 ---
    def _dir_at(self, t: float) -> np.ndarray:
        if self.cfg.wind_noise_deg <= 0.0:
            return self.n0
        wobble = math.radians(self.cfg.wind_noise_deg) * self._proc_value(self._theta_proc, t)
        base = self.cfg.theta_rad() + wobble
        return np.array([math.cos(base), math.sin(base)])

    def _speed_at(self, t: float) -> float:
        if self.cfg.wind_speed_var_pct <= 0.0:
            return self.speed
        factor = 1.0 + self.cfg.wind_speed_var_pct * self._proc_value(self._speed_proc, t)
        # 음/역행 속도 방지(전선이 뒤로 가지 않도록 하한 클립)
        return self.speed * max(0.1, factor)

    # --- 방사 비등방 방향계수 (다운윈드 신장) [D-017] ---
    def _dir_factor(self, phi: float) -> float:
        return 1.0 + self.cfg.wind_bias * math.cos(phi - self.wind_dir)

    def _angle_of(self, p) -> float:
        v = np.array(p, dtype=float) - self.start
        return math.atan2(v[1], v[0])

    # --- 전선 궤적 중점적분 ---
    def _build_trajectory(self) -> None:
        steps = int(round(self.cfg.t_max / self._dt)) + 2
        pos = self.start.copy()
        r = 0.0
        positions = [pos.copy()]
        radii = [0.0]
        for k in range(1, steps):
            t_mid = (k - 0.5) * self._dt
            s = self._speed_at(t_mid)
            if self.radial:
                r += s * self._dt               # 등방 기저 반경(방향계수는 조회 시 곱함)
            else:
                pos = pos + self._dir_at(t_mid) * s * self._dt
            positions.append(pos.copy())
            radii.append(r)
        self._positions = np.array(positions)
        self._radii = np.array(radii)

    def _idx(self, t: float) -> int:
        k = int(round(t / self._dt))
        if k < 0:
            return 0
        if k >= len(self._radii):
            return len(self._radii) - 1
        return k

    def update(self, t: float) -> None:
        self._t = t

    def front_pos(self, t: float) -> tuple[float, float]:
        if self.shape == "ellipse":
            # 시각화·HUD용 대표점 = 선단(head)
            return tuple(self.start + self.n0 * (self.speed * t))
        i = self._idx(t)
        if self.radial:
            # 대표 위치(시각화용): 바람 방향으로 신장된 반경
            r = self._radii[i] * self._dir_factor(self.wind_dir)
            return tuple(self.start + self.n0 * r)
        return tuple(self._positions[i])

    # ── [2.L §4] 타원: 도착시각·기울기 (둘 다 해석적. 수치 탐색 없음) ──
    def _ellipse_T(self, p) -> float:
        """발화점(뒤쪽 초점) 기준 도착시각. T = scale·(a·r − c·x)/b²"""
        v = np.asarray(p, dtype=float) - self.start
        x = float(v @ self.n0)                     # 풍하 성분
        r = float(np.linalg.norm(v))
        return self._escale * (self._ea * r - self._ec * x) / (self._eb ** 2)

    def _ellipse_gradT(self, p) -> np.ndarray:
        """∇T (해석적). |∇T| = 1/(국소 법선 확산속도) — 추정기가 재구성하려는 바로 그 양."""
        v = np.asarray(p, dtype=float) - self.start
        r = float(np.linalg.norm(v))
        if r < 1e-9:
            return np.array([0.0, 0.0])
        # x = v·n0 이므로 ∂x/∂p = n0, ∂r/∂p = v/r
        g = self._escale * (self._ea * (v / r) - self._ec * self.n0) / (self._eb ** 2)
        return g

    def ellipse_normal_speed(self, p) -> float:
        """점 p에서의 참 국소 법선 확산속도 = 1/|∇T|."""
        g = float(np.linalg.norm(self._ellipse_gradT(p)))
        return float("inf") if g < 1e-12 else 1.0 / g

    # --- 참 도착시각(명목 기준선) ---
    def T_true(self, p) -> float:
        p = np.array(p, dtype=float)
        if self.shape == "ellipse":
            return self._ellipse_T(p)              # 타원은 이 식이 **정확한** 도착시각이다
        if self.radial:
            r = float(np.linalg.norm(p - self.start))
            phi = self._angle_of(p)
            return r / (self.speed * self._dir_factor(phi))
        return float((p - self.start) @ self.n0 / self.speed)

    # --- S3 평가용: 참 국소 확산속도(방사 비등방) [D-017] ---
    def true_local_speed(self, p) -> float:
        if self.radial:
            return self.speed * self._dir_factor(self._angle_of(p))
        return self.speed

    # --- 온도장 (주 전선 + 비화 발화점들의 최대) ---
    def temp_at(self, p, t: float) -> float:
        p = np.array(p, dtype=float)
        if self.shape == "ellipse":
            # 전선까지의 **법선 방향 부호거리**: d = (T(p) − t)/|∇T(p)|
            #   (|∇T| = 1/법선속도 이므로 '남은 시간 × 속도' = 거리. 직선 모델의 d와 같은 뜻.)
            g = float(np.linalg.norm(self._ellipse_gradT(p)))
            d = (self._ellipse_T(p) - t) / g if g > 1e-12 else float("inf")
            temp = self._temp_from_d(d)
            for (t_ig, ps) in self._spots:
                if t < t_ig:
                    continue
                ts = self._temp_from_d(float(np.linalg.norm(p - ps)) - self.speed * (t - t_ig))
                if ts > temp:
                    temp = ts
            return temp
        i = self._idx(t)
        if self.radial:
            phi = self._angle_of(p)
            front_r = float(self._radii[i]) * self._dir_factor(phi)   # 방향별 신장 반경
            d = float(np.linalg.norm(p - self.start)) - front_r
        else:
            n = self._dir_at(t)
            front = self._positions[i]
            d = float((p - front) @ n)
        temp = self._temp_from_d(d)

        # 비화: 각 발화점의 방사 전선(t_ig 이후 속도 s0로 확산)
        for (t_ig, ps) in self._spots:
            if t < t_ig:
                continue
            d_spot = float(np.linalg.norm(p - ps)) - self.speed * (t - t_ig)
            ts = self._temp_from_d(d_spot)
            if ts > temp:
                temp = ts
        return temp

    # --- S3 평가용: 점 p의 참 방사 방향(점화원→p) ---
    def radial_dir(self, p) -> tuple[float, float] | None:
        p = np.array(p, dtype=float)
        v = p - self.start
        nv = float(np.linalg.norm(v))
        if nv < 1e-9:
            return None
        return (float(v[0] / nv), float(v[1] / nv))
