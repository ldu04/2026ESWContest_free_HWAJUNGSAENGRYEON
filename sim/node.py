"""node.py — Node 상태·행동 (지시서 #1 §2.2).

상태 기계: ALIVE → (temp ≥ temp_threshold) → DYING → (last_gasp_delay 후) → DEAD.
DYING 진입 순간 Last-Gasp 패킷을 1회 생성한다. ALIVE는 heartbeat_period마다 하트비트.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeState(str, Enum):
    ALIVE = "ALIVE"
    DYING = "DYING"
    DEAD = "DEAD"


@dataclass
class Node:
    id: int
    pos: tuple[float, float]
    is_sink: bool = False

    state: NodeState = NodeState.ALIVE
    temp: float = 25.0                     # 현재 온도(화재 모델이 매 틱 부여)
    last_temp: float = 25.0                # 마지막으로 유효 관측된 온도(교차검증용)

    last_heartbeat_t: float = 0.0          # 마지막 하트비트 방출 시각
    t_die: float | None = None             # 예약된 DEAD 전환 시각
    death_t: float | None = None           # 실제 DEAD 확정 시각(ground truth)
    dying_t: float | None = None           # DYING 진입 시각
    _last_gasp_emitted: bool = False

    # 실물 괴리 주입용(지시서 #2c) — 기본값이면 무영향
    clock_offset: float = 0.0              # ① 노드별 고정 클럭 오프셋(초) [A-1]
    nonfire: bool = False                  # ④ 비화재(배터리·고장) 사망으로 주입된 노드 [A-6]
    benign_c: float = 0.0                  # [2.K §3] 비화재 열원(햇볕·기기발열) 상승폭(℃). 0=없음
    tau: float = 0.0                       # 센서 열관성 시상수(초) [#2e-3 Step 2.G, D-042]
    tau_order: int = 1                     # 1차/2차 지연 [#2e-3 Step 2.H, D-043]
    _stage1: float | None = None           # 2차 지연의 중간단 상태

    # --- 화재 모델이 호출 ---
    def update_temp(self, fire, t: float, dt: float | None = None) -> None:
        """화재 ground-truth로부터 현재 온도를 부여받는다.

        [#2e-3 2.G] `tau > 0` 이면 **센서 열관성**을 1차 저역통과로 모사한다:
            T_sensor += (T_air − T_sensor)·(dt/τ)
        실물 DS18B20은 공기 온도를 즉시 못 따라가므로 임계(80℃) 도달이 늦어지고,
        그만큼 사망시각이 뒤로 밀린다. **tau=0이면 아래 else가 기존 코드와 완전히 동일**하다.
        """
        if self.state == NodeState.DEAD:
            return
        T_air = fire.temp_at(self.pos, t)
        # [2.K §3] 비화재 열원(햇볕·기기발열): 불과 무관한 바닥온도 상승. 0이면 항등(비트 동일).
        if self.benign_c > 0.0:
            T_air = max(T_air, fire.cfg.ambient + self.benign_c)
        if self.tau > 0.0 and dt:
            if self.tau_order >= 2:
                # 2차: τ/2 두 단 종속 — 실제 센서가 1차가 아닐 때의 모델 미스매치 시험 [D-043]
                a = min(1.0, dt / (self.tau / 2.0))
                if self._stage1 is None:
                    self._stage1 = self.temp
                self._stage1 = self._stage1 + (T_air - self._stage1) * a
                self.temp = self.temp + (self._stage1 - self.temp) * a
            else:
                # dt/τ > 1 이면 수치 불안정 → 1로 클립(그 경우 즉시 추종 = 열관성 없음과 동일)
                self.temp = self.temp + (T_air - self.temp) * min(1.0, dt / self.tau)
        else:
            self.temp = T_air
        # 살아있는 동안의 온도는 '유효 관측'으로 기록(교차검증 근거).
        self.last_temp = self.temp

    # --- 상태 기계 ---
    def step(self, t: float, cfg) -> list[dict]:
        """상태 전이를 진행하고, 이 틱에 발생한 패킷(dict) 리스트를 반환.

        sink는 죽지 않는다(게이트웨이). 반환 패킷은 network가 릴레이한다.
        """
        packets: list[dict] = []
        if self.is_sink or self.state == NodeState.DEAD:
            return packets

        if self.state == NodeState.ALIVE:
            if self.temp >= cfg.temp_threshold:
                # DYING 진입 + Last-Gasp 예약
                self.state = NodeState.DYING
                self.dying_t = t
                self.t_die = t + cfg.last_gasp_delay
                packets.append(self._make_last_gasp(t))
                self._last_gasp_emitted = True
            else:
                # 정상: 주기적 하트비트
                if t - self.last_heartbeat_t >= cfg.heartbeat_period:
                    self.last_heartbeat_t = t
                    packets.append({
                        "type": "HEARTBEAT",
                        "id": self.id,
                        "pos": self.pos,
                        "last_temp": self.last_temp,
                        "t": t,
                    })
        elif self.state == NodeState.DYING:
            if not self._last_gasp_emitted:
                packets.append(self._make_last_gasp(t))
                self._last_gasp_emitted = True
            if self.t_die is not None and t >= self.t_die:
                self.state = NodeState.DEAD
                self.death_t = t
        return packets

    def _make_last_gasp(self, t: float) -> dict:
        return {
            "type": "LAST_GASP",
            "id": self.id,
            "pos": self.pos,
            "last_temp": self.last_temp,
            "t": t,
        }

    @property
    def is_relay_capable(self) -> bool:
        """DEAD가 아니면 릴레이 가능(ALIVE/DYING 모두 아직 송신 가능)."""
        return self.state != NodeState.DEAD

    def snapshot(self) -> dict:
        """직렬화 가능한 값 스냅샷 (코어↔뷰 분리, D-003)."""
        return {
            "id": self.id,
            "pos": self.pos,
            "is_sink": self.is_sink,
            "state": self.state.value,
            "temp": round(self.temp, 2),
            "last_temp": round(self.last_temp, 2),
            "death_t": self.death_t,
        }
