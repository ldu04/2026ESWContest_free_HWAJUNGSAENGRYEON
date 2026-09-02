"""config.py — 모든 시뮬레이션 파라미터 (dataclass).

지시서 #1 §10의 기본값을 그대로 담는다. 모든 실행은 이 Config 하나로 재현된다
(같은 config → 같은 결과, 결정론). 값 변경은 여기 한 곳에서.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass
class Config:
    # --- 결정론·시간 ---
    seed: int = 42
    dt: float = 0.1
    t_max: float = 120.0

    # --- 격자·배치 (§2.1) ---
    grid_rows: int = 4
    grid_cols: int = 4
    spacing_m: float = 10.0          # 노드 간격
    # 임의 좌표 배치를 원하면 [(x, y), ...] 를 준다. 첫 원소가 sink(id=0).
    custom_positions: list[tuple[float, float]] | None = None

    # --- 무선 링크 (§4.1) ---
    radio_range_m: float = 18.0      # 기본 ≈ spacing×1.8

    # --- 온도·화재 임계 (§2.2, §3) ---
    ambient: float = 25.0
    temp_threshold: float = 80.0     # ALIVE→DYING 임계
    warn_temp: float = 60.0          # 사망 교차검증용 경고 온도
    peak: float = 300.0              # 전선 통과 후 온도
    warm_scale: float = 6.0          # 전선 접근 시 온도 상승 스케일(m)
    # [#2e-3 Step 2.I-a, D-044] 연소 후 **냉각 꼬리**. 0이면 통과 후 peak 영구 유지(기존, 비트 동일).
    # >0이면 전선 뒤쪽에서 T = ambient + (peak−ambient)·exp(−|d|/burn_scale_m) 로 식는다
    # → 비로소 '온도 펄스'가 생기고, 느린 센서(큰 τ)의 **감쇠→검출 실패**를 시험할 수 있다.
    # 펄스 폭 ≈ (warm_scale + burn_scale_m)·ln5 / speed  (80 ℃ 이상 구간 기준)
    burn_scale_m: float = 0.0

    # --- [2.K §3] 비화재 '열원'(햇볕·기기발열) — 임계 하향의 오탐 비용을 재기 위한 환경 주입 ---
    # 배경: 기존 모델의 유일한 열원은 **불**이다. 그래서 임계를 낮췄을 때의 가장 중요한 오탐 경로
    #   ("불이 아닌 더운 것이 낮아진 선을 밟는다")를 **원리적으로 생성할 수 없었다**.
    #   2.D의 비화재 '사망'(강제 사망, 저온)은 이 경로와 다른 것을 잰다.
    # 모델: 선택된 노드는 바닥온도가 ambient + benign_heat_c 로 올라간다(불과 무관한 정상상태 가열).
    #   T_air = max(T_fire, ambient + benign_c)
    # ★ benign_heat_c=0 이면 T_air ≥ ambient 이므로 max()가 항등 → **기존과 비트 동일**.
    benign_heat_c: float = 0.0       # 비화재 열원의 상온 대비 상승폭(℃). 0 = 없음(기존)
    benign_heat_frac: float = 0.0    # 그 열원을 받는 비-sink 노드 비율(0~1)

    # --- 하트비트·Last-Gasp (§2.2) ---
    heartbeat_period: float = 1.0
    last_gasp_delay: float = 0.3     # DYING→DEAD 지연(임종 패킷 여유)

    # --- 오탐 방어 (§5) ---
    p_dropout: float = 0.02          # 매 틱 링크 일시두절 확률
    K_confirm: int = 3               # 사망확정에 필요한 독립 관측 이웃 수
    silence_timeout: float = 3.0     # 침묵 지속 임계(초)

    # --- 비화재 사망 방어 (지시서 #2d, 선별 로직만 / estimator 수학 불변) ---
    nonfire_gate: bool = True        # True=3분기 선별(#2d), False=기존 OR게이트(#2c 이전, 비교용)
    # ③분기 residual 임계: baseline 화재사망 잔차 분포 mean0.30+3σ0.58≈2.05s에서 도출(테스트 튜닝 아님) [D-030]
    residual_gate_s: float = 2.0

    # --- COOL 비화재 누수 차단 (지시서 #2e-2, 선별 게이트만 / estimator 수학 불변) ---
    # #2e-1 진단: 분기③에서 accepted 이웃 <min_samples 면 residual을 못 구해 '관대 채택'([D-030]) →
    # 통과 COOL의 98.9%가 이 경로로 샜고, 살아있는 노드가 사망확정되던 오탐 경로이기도 했다.
    # ★ [D-036] Fix A를 **기본값으로 채택**: 시공간 증거를 못 구하면 채택하지 않는다.
    #   레거시(#2d까지의 관대 채택)는 nonfire_strict_gate=False 로 언제든 복원 — 비교용으로 보존한다.
    nonfire_strict_gate: bool = True    # Fix A(기본): 표본 부족이면 '제외'. False=레거시 관대 채택([D-030])
    # Fix B는 끈 채로 보존. 임계가 전선 속도에 비례해 ≥0.8 m/s에서만 유효하므로,
    # #2e-3의 속도 추정으로 임계를 스케일할 수 있게 된 뒤 재검토한다. [D-035, D-036]
    dtdt_gate: bool = False             # Fix B: 표본 부족이면 자기 온도 상승률 dT/dt로 판정(현재 비활성)
    dtdt_window_s: float = 3.0          # 보고 온도 계열에서 기울기를 재는 창(heartbeat 1s → 3~4 표본)
    # 임계(℃/s): baseline 계열(S1·S2a·S2b·S4·S5·S6, 30시드, 정당 화재사망 5992건)의 상승률 분포에서 도출.
    # mean 10.73 − 3σ 1.82 ≈ 5.28 → 5.3 ([D-030]이 residual에 쓴 mean±3σ 선례와 동형).
    # 이 임계 미만인 정당 화재사망은 0.47%뿐. S10/S11(테스트) 점수는 도출에 쓰지 않았다. [D-034]
    # 산출 근거: scripts/derive_dtdt_threshold.py → summary_2e2_dtdt_threshold.csv
    dtdt_min_c_per_s: float = 5.3

    # --- [2.M P2] Last-Gasp 증거 (실물 경로 전용, 기본 꺼짐 → 시뮬 비트 동일) ---
    # LG는 펌웨어가 **임계(80 ℃)를 밟은 순간에만** 내는 자기 보고라, 온도 보고와 **독립인 양성 증거**다.
    # ★ 비대칭으로만 쓴다: 있으면 채택 구제, **없으면 아무 판단도 하지 않는다**(없다고 기각하면 미탐지).
    # ★ 시뮬 기본값을 False로 두는 이유(의도된 분기, 정직 기록):
    #   켜면 #2d~#2e-2에서 확정한 baseline 수치가 전부 바뀐다. 실물에는 LG 정보가 실제로 존재하므로
    #   게이트웨이만 True로 켠다. 이 분기는 D-056 표에 명시한다.
    lastgasp_evidence: bool = False

    # --- [2.N §3] 분기③ residual 적합의 최소 표본 (변수 분리용) ---
    # `min_samples`는 estimator._fit_local 과 Verifier._residual **양쪽**에 쓰인다.
    # 그대로 스윕하면 추정기까지 바뀌어 교란되므로, 분기③만 따로 조일 수 있게 분리했다.
    # None 이면 min_samples 로 폴백.
    # 유도: 평면 3파라미터라 n=3이면 DOF=0 → 잔차 항등 0 → residual 검사가 무조건 통과(공허).
    #   판별력을 가지려면 n≥4(DOF≥1). 상세는 docs/유도_표본적정성_진단기준.md 부록 A.
    # ★ [D-061] 기본값을 3(폴백) → **4**로 채택. 근거:
    #   ① DOF≥1 이라야 잔차가 판별력을 갖는다(유도) ② 2.N §3 스윕에서 3→4는 DOF=0 적합을
    #   **전부 제거**하면서 확정·방향·오염률이 **모든 시나리오에서 +0.00**(중립)이었다.
    #   즉 논리적으로 공허한 검사를 **비용 0으로** 없앤다. n≥5는 교환관계가 있어 채택하지 않았다.
    residual_min_samples: int | None = 4

    # --- 화재 참값 (§3) ---
    speed_true: float = 1.5          # 전선 속도 m/s
    theta_deg: float = 30.0          # 전선 진행 방향(도)
    # 전선 시작점. None이면 build 시 격자 기준 자동 설정(sink 반대쪽에서 진입).
    fire_start: tuple[float, float] | None = None
    # --- [2.L §4] 타원 전선 (문헌 기반 단순 형상 모델) ---
    # 출처: Alexander, M.E. (1985) "Estimating the length-to-breadth ratio of elliptical
    #   forest fire patterns", Proc. 8th Conf. Fire and Forest Meteorology.
    #   · 점화원에서 바람을 타고 번지는 화재는 **타원**으로 근사되고, **발화점은 타원의 뒤쪽 초점**에 온다.
    #   · 장단축비  L/B = 1.0 + 0.00120·W^2.154   (W = 10 m 개활지 풍속, km/h; 적용상한 50 km/h → L/B≈6.5)
    # ★ 이건 **형상 모델**이지 물리 확산 모델(Rothermel 계열)이 아니다. 연료·수분·지형을 안 쓴다.
    #   그 대가로 "연료가 바뀌면?"에는 답하지 못한다 — 범위를 넘겨 쓰지 말 것.
    # fire_shape="line" 이면 기존 경로를 그대로 타 **비트 동일**.
    fire_shape: str = "line"          # "line"(기존 직선/요동) | "ellipse"
    ellipse_lb: float = 1.0           # 장단축비 L/B (1.0 = 원 = 무풍). wind_kmh를 주면 그쪽이 우선
    wind_kmh: float | None = None     # 주면 Alexander(1985)로 L/B 산출. None이면 ellipse_lb 사용

    # 확장 옵션(1차 검증 후): 방사형 전선 / 바람 노이즈
    radial_fire: bool = False
    wind_noise_deg: float = 0.0      # θ에 주는 요동 진폭(도), 0이면 무노이즈
    wind_speed_var_pct: float = 0.0  # 돌풍: 전선 속도 변동 표준편차(비율, 0.2=std 20%)  [지시서#2 S2]
    placement_jitter: float = 0.0    # 배치 흔들림: 노드 위치를 spacing의 이 비율만큼 랜덤 이동 [S4]
    wind_bias: float = 0.0           # 방사형 바람 결합: 확산 비등방 세기(다운윈드 신장) [지시서#2b]

    # --- 센서 열관성 τ (지시서 #2e-3 Step 2.G, 환경 모델만 / 추정기·방어 불변) [D-042] ---
    # 실물 DS18B20은 공기 온도를 즉시 못 따라간다. 1차 저역통과로 모사:
    #   T_sensor += (T_air − T_sensor)·(dt/τ),  사망 판정은 T_sensor 기준.
    # τ 범위 {0,2,5,10}s는 DS18B20의 **물리적 응답 근거**지 테스트 점수를 보고 고른 값이 아니다.
    # ★ 0이면 저역통과 자체를 건너뛰어 기존 동작과 **비트 동일**(세기0 회귀로 증명).
    sensor_tau_s: float = 0.0        # 센서 시상수(초). 0 = 열관성 없음(기존)
    sensor_tau_var_pct: float = 0.0  # 노드별 τ 편차(비율). 제조·피복·기류 편차 모사
    # [2.J-A] 편차 분포 선택. "uniform" = ±var 균등(기존, [D-042] 결과 재현용 기본값)
    #         "gauss"   = τ_i ~ μ·(1 + N(0, var)), 0.5 s 하한 클립 (2.J 스펙)
    sensor_tau_var_dist: str = "uniform"
    # [#2e-3 Step 2.H, D-043] 재구성(역보상)의 **모델 미스매치 시험**용 — 기본값은 기존과 비트 동일
    sensor_order: int = 1            # 1=1차 저역통과(기존) / 2=2차(τ/2 두 단 종속) — 실제 센서가 1차가 아닐 때
    sensor_noise_c: float = 0.0      # 보고 온도 측정 잡음 std(℃). dT/dt 미분이 이걸 증폭한다
    sensor_quant_c: float = 0.0      # 보고 온도 양자화 스텝(℃). DS18B20 12bit = 0.0625

    # --- 실물 괴리 환경 주입 (지시서 #2c-B, 환경만 어렵게 / 추정기·방어 불변) ---
    clock_jitter_ms: float = 0.0     # ① 노드별 고정 클럭 오프셋 std(ms) → death_t_est에 가산 [A-1]
    temp_jitter_s: float = 0.0       # ② 사망 검출 시각 지터 std(s), 사망마다 [A-4]
    n_spot_fires: int = 0            # ③ 비화: 진행 중 새 발화점 수 [A-5]
    n_nonfire_deaths: int = 0        # ④ 비화재 사망: 화선 무관 강제 사망 노드 수 [A-6]

    # --- 추정기 (§6) ---
    dt_window: float = 8.0           # 국소 최소제곱에 묶을 사망시각 창(초)
    eps: float = 1e-6
    alert_horizon: float = 30.0      # ETA ≤ 이 값이면 대피경보
    min_samples: int = 3             # 국소 적합 최소 표본 수

    # --- 모드 (§4.3) ---
    mode: str = "ours"               # "ours" | "stock"

    # --- 산출물 ---
    results_dir: str = "results"

    def theta_rad(self) -> float:
        return math.radians(self.theta_deg)

    def direction(self) -> tuple[float, float]:
        """전선 진행 단위벡터 n = (cosθ, sinθ)."""
        th = self.theta_rad()
        return (math.cos(th), math.sin(th))

    def lb_ratio(self) -> float:
        """장단축비 L/B. wind_kmh가 주어지면 Alexander(1985) 회귀식으로 산출.

        L/B = 1.0 + 0.00120·W^2.154   (W: km/h, 10 m 개활지 풍속)
        ★ 적용 상한 50 km/h(L/B≈6.5). 그 밖은 **외삽**이므로 경고 대상이다.
        """
        if self.wind_kmh is None:
            return max(1.0, self.ellipse_lb)
        return 1.0 + 0.00120 * (max(0.0, self.wind_kmh) ** 2.154)

    def n_nodes(self) -> int:
        if self.custom_positions is not None:
            return len(self.custom_positions)
        return self.grid_rows * self.grid_cols
