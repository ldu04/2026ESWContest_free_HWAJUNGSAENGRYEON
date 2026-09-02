"""network.py — 이웃 그래프·링크·패킷 릴레이·자가치유 라우팅 (지시서 #1 §4).

- 링크: 두 노드가 radio_range_m 이내면 무향 링크(기하적, 정적).
- 라우팅: sink(id=0)에서 BFS로 최단 홉 트리 → 각 노드의 next-hop. DEAD 노드는 그래프에서
  제외. DEAD 확정이 생기면 재계산(=자가치유), 그 지연을 기록. [D-004, D-005]
- 릴레이: DYING/ALIVE 노드가 만든 패킷을 next-hop 체인으로 sink까지. 경로 단절 시 실패(전달률 반영).
- 일시 두절(dropout): 매 틱 각 링크가 p_dropout 확률로 잠깐 끊김 → 오탐 유발원(§5 테스트용).
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from .node import Node, NodeState


def build_grid(cfg) -> list[Node]:
    """격자(또는 custom_positions)로 노드 생성. id=0 = sink(불이 마지막에 닿는 모서리)."""
    positions: list[tuple[float, float]]
    if cfg.custom_positions is not None:
        positions = list(cfg.custom_positions)
    else:
        positions = [
            (c * cfg.spacing_m, r * cfg.spacing_m)
            for r in range(cfg.grid_rows)
            for c in range(cfg.grid_cols)
        ]

    # 배치 흔들림(S4): 각 노드를 spacing×jitter 만큼 결정론적으로 이동.
    # dropout rng와 독립되도록 파생 시드 사용(재현성 유지). [지시서#2 S4]
    if cfg.placement_jitter > 0.0 and cfg.custom_positions is None:
        jrng = np.random.default_rng(cfg.seed + 987654321)
        amp = cfg.spacing_m * cfg.placement_jitter
        positions = [
            (x + float(jrng.uniform(-amp, amp)), y + float(jrng.uniform(-amp, amp)))
            for (x, y) in positions
        ]

    # sink는 전선 진행 방향 n 투영이 '가장 큰' 노드(마지막에 불이 닿는 쪽)로 잡는다.
    n = np.array(cfg.direction())
    proj = [np.array(p) @ n for p in positions]
    sink_idx = int(np.argmax(proj))

    # sink를 id=0으로: 해당 위치를 리스트 맨 앞으로 스왑
    positions[0], positions[sink_idx] = positions[sink_idx], positions[0]

    nodes = []
    for i, p in enumerate(positions):
        nd = Node(id=i, pos=p, is_sink=(i == 0))
        nd.temp = cfg.ambient
        nd.last_temp = cfg.ambient
        nodes.append(nd)
    return nodes


class Network:
    _HIST_MAX = 8              # 보고 온도 계열 보관 길이(창 3s·heartbeat 1s면 넉넉) [#2e-2]

    def __init__(self, nodes: list[Node], cfg):
        self.cfg = cfg
        self.nodes = nodes
        self.by_id = {nd.id: nd for nd in nodes}
        self.sink_id = 0

        # 기하적 이웃(정적)
        self.neighbors: dict[int, list[int]] = self._build_links()

        # 링크별 활성 상태(이번 틱). True=정상, False=일시 두절.
        self._active: dict[frozenset, bool] = {}

        # 수신 최근성: last_heard[v][u] = v가 u의 신호를 마지막으로 들은 시각
        self.last_heard: dict[int, dict[int, float]] = {
            v.id: {u.id: 0.0 for u in nodes if u.id != v.id and u.id in self.neighbors.get(v.id, [])}
            for v in nodes
        }
        # 메시가 실제 '수신'한 노드별 보고 온도(#2d 선별용, 실물 정합): 최고·최신
        self.rep_peak: dict[int, float] = {nd.id: cfg.ambient for nd in nodes}
        self.rep_time: dict[int, float] = {nd.id: 0.0 for nd in nodes}
        # 보고 온도 '계열'(#2e-2 dT/dt용): 수신에 성공한 (t, temp) 샘플만. god-view 아님. [D-033]
        self.rep_hist: dict[int, list[tuple[float, float]]] = {nd.id: [] for nd in nodes}
        # [#2e-3 2.H, D-043] 측정 잡음·양자화는 **이 계열에만** 주입한다.
        #   목적이 'dT/dt 미분의 잡음 증폭'을 격리 측정하는 것이므로, #2d 방어 게이트가 쓰는
        #   rep_peak/last_temp 경로는 건드리지 않는다(방어 동작 변화와 뒤섞이지 않게).
        #   rng 생성만으로는 난수를 뽑지 않아 기본값에서 **비트 동일**.
        self._srng = np.random.default_rng(cfg.seed + 271828)

        self.next_hop: dict[int, int | None] = {}
        self._dead_set: frozenset = frozenset()
        self.reroute_delays_ms: list[float] = []   # 사망확정→경로복구 지연 기록

        self.rebuild_routes(force=True)

    # --- 그래프 구성 ---
    def _build_links(self) -> dict[int, list[int]]:
        adj: dict[int, list[int]] = {nd.id: [] for nd in self.nodes}
        R = self.cfg.radio_range_m
        for i, a in enumerate(self.nodes):
            for b in self.nodes[i + 1:]:
                d = math.dist(a.pos, b.pos)
                if d <= R:
                    adj[a.id].append(b.id)
                    adj[b.id].append(a.id)
        return adj

    def link_key(self, u: int, v: int) -> frozenset:
        return frozenset((u, v))

    # --- 일시 두절(오탐원) ---
    def apply_dropouts(self, rng) -> None:
        """매 틱 각 링크를 p_dropout 확률로 일시 두절. 결정론적(rng 시드 고정)."""
        self._active = {}
        p = self.cfg.p_dropout
        for u, nbrs in self.neighbors.items():
            for v in nbrs:
                if u < v:
                    self._active[self.link_key(u, v)] = (rng.random() >= p)

    def link_active(self, u: int, v: int) -> bool:
        return self._active.get(self.link_key(u, v), True)

    # --- 라우팅(자가치유) ---
    def _alive_ids(self) -> set[int]:
        return {nd.id for nd in self.nodes if nd.state != NodeState.DEAD}

    def rebuild_routes(self, force: bool = False) -> None:
        """sink 기준 BFS로 next-hop 트리 재계산. DEAD 노드는 제외."""
        alive = self._alive_ids()
        # 파서: BFS는 dropout 무시(토폴로지 레벨). dropout은 릴레이 시점에만 반영.
        parent: dict[int, int | None] = {self.sink_id: None}
        visited = {self.sink_id}
        q = deque([self.sink_id])
        while q:
            cur = q.popleft()
            for nb in self.neighbors[cur]:
                if nb in alive and nb not in visited:
                    visited.add(nb)
                    parent[nb] = cur          # sink 방향 부모 = next-hop
                    q.append(nb)
        # 도달 못한 alive 노드는 next_hop None(고립)
        self.next_hop = {nid: parent.get(nid, None) for nid in alive}
        self._dead_set = frozenset(self.by_id.keys()) - alive

    def rebuild_routes_if_changed(self, deaths: list[dict], t: float) -> None:
        """토폴로지 변화(신규 DEAD)가 있으면 경로 재계산 = 자가치유. 지연(ms) 기록.

        재라우팅 지연은 '실제 노드 소실 → 경로 복구'로 측정한다. verifier 확정 시점과
        노드 DEAD 전환 시점이 다를 수 있으므로, 확정 이벤트 수가 아니라 신규 DEAD 수로 센다.
        """
        cur_dead = frozenset(self.by_id.keys()) - self._alive_ids()
        newly_dead = cur_dead - self._dead_set
        if newly_dead:
            self.rebuild_routes()
            # 본 시뮬레이터는 같은 틱에 즉시 복구 → 알고리즘 지연 = 1틱 [D-005]
            for _ in newly_dead:
                self.reroute_delays_ms.append(self.cfg.dt * 1000.0)

    def route_path(self, src: int) -> list[int] | None:
        """src→sink 경로(노드 id 리스트). 경로 없으면 None."""
        path = [src]
        cur = src
        guard = 0
        while cur != self.sink_id:
            nh = self.next_hop.get(cur)
            if nh is None:
                return None
            path.append(nh)
            cur = nh
            guard += 1
            if guard > len(self.nodes):
                return None
        return path

    # --- 릴레이 ---
    def collect_and_relay(self, packets: list[dict], t: float) -> dict:
        """이번 틱 생성 패킷을 next-hop 체인으로 sink까지 전달 시도.

        각 홉 링크가 dropout으로 끊겼거나 경로가 없으면 실패. 전달률 집계.
        수신 성공 시 last_heard 갱신(침묵 감지의 근거).
        """
        generated = len(packets)
        delivered = 0
        delivered_ids: list[int] = []
        used_edges: set[frozenset] = set()

        for pkt in packets:
            src = pkt["id"]
            # 발신자가 인접 이웃에게 브로드캐스트되는 순간 → last_heard 갱신
            heard_by_any = False
            for v in self.neighbors.get(src, []):
                if self.link_active(src, v):
                    self.last_heard.setdefault(v, {})[src] = t
                    heard_by_any = True
            # 최소 1 이웃이 수신 → 메시가 이 노드의 보고 온도를 안다(#2d rep_peak)
            if heard_by_any and "last_temp" in pkt:
                self.rep_peak[src] = max(self.rep_peak.get(src, self.cfg.ambient), pkt["last_temp"])
                self.rep_time[src] = t
                h = self.rep_hist.setdefault(src, [])       # 상승률 계산용 최근 샘플(#2e-2)
                Tv = float(pkt["last_temp"])
                if self.cfg.sensor_noise_c > 0:            # 측정 잡음(#2e-3 2.H)
                    Tv += float(self._srng.normal(0.0, self.cfg.sensor_noise_c))
                if self.cfg.sensor_quant_c > 0:            # 양자화(DS18B20 12bit = 0.0625 ℃)
                    q = self.cfg.sensor_quant_c
                    Tv = round(Tv / q) * q
                h.append((t, Tv))
                if len(h) > self._HIST_MAX:
                    del h[0]

            path = self.route_path(src)
            if path is None:
                continue
            ok = True
            for a, b in zip(path, path[1:]):
                if self.by_id[b].state == NodeState.DEAD or not self.link_active(a, b):
                    ok = False
                    break
                used_edges.add(self.link_key(a, b))
            if ok:
                delivered += 1
                delivered_ids.append(src)

        return {
            "generated": generated,
            "delivered": delivered,
            "delivered_ids": delivered_ids,
            "used_edges": [tuple(sorted(e)) for e in used_edges],
        }

    # --- 보고 온도 상승률 dT/dt (#2e-2 Fix B) ---
    def rep_slope(self, uid: int, window: float | None = None) -> float | None:
        """메시가 수신한 보고 온도 계열의 최소제곱 기울기(℃/s). 표본 <2면 None.

        창은 '현재 시각'이 아니라 **마지막 보고 시각** 기준이다. 침묵 판정은 이미 최소
        silence_timeout(3s)이 지난 뒤라, 현재 시각 기준으로 자르면 표본이 전부 탈락한다.
        노드가 죽으면 보고가 끊겨 계열이 동결되므로, 확정 시점 값 = 사후 조회 값(재현 가능).
        """
        h = self.rep_hist.get(uid, [])
        if len(h) < 2:
            return None
        w = self.cfg.dtdt_window_s if window is None else window
        t_last = h[-1][0]
        pts = [(tt, T) for (tt, T) in h if t_last - tt <= w]
        if len(pts) < 2:
            return None
        ts = np.array([p[0] for p in pts], dtype=float)
        Ts = np.array([p[1] for p in pts], dtype=float)
        var = float(((ts - ts.mean()) ** 2).sum())
        if var <= 1e-12:
            return None
        return float(((ts - ts.mean()) * (Ts - Ts.mean())).sum() / var)

    # --- 침묵 감지 ---
    def detect_silence(self, t: float) -> dict[int, dict]:
        """각 비-sink 노드 u에 대해, u를 '미수신'으로 관측한 이웃 수를 센다.

        반환: {u_id: {observers: [v...], n_neighbors: k, last_temp: float,
                       neighbor_max_temp: float}}
        DEAD 확정 판단은 verifier가 이 정보로 수행(§5).
        """
        info: dict[int, dict] = {}
        for u in self.nodes:
            if u.is_sink:
                continue
            nbrs = self.neighbors.get(u.id, [])
            observers = []
            best_heard = 0.0
            for v in nbrs:
                heard = self.last_heard.get(v, {}).get(u.id, 0.0)
                best_heard = max(best_heard, heard)
                if (t - heard) > self.cfg.silence_timeout:
                    observers.append(v)
            neighbor_max_temp = max(
                (self.by_id[v].last_temp for v in nbrs), default=self.cfg.ambient
            )
            info[u.id] = {
                "observers": observers,
                "n_neighbors": len(nbrs),
                "last_temp": u.last_temp,
                "neighbor_max_temp": neighbor_max_temp,
                "best_heard": best_heard,   # 마지막 성공 신호 시각 ≈ 사망시각 추정 [D-006]
                "rep_peak": self.rep_peak.get(u.id, self.cfg.ambient),   # 수신된 자기 최고온(#2d)
                "rep_time": self.rep_time.get(u.id, 0.0),
                # 자기 온도 상승률(#2e-2). 침묵 후보에만 계산(비용 절감, 의미 동일).
                "rep_slope": (self.rep_slope(u.id) if observers else None),
            }
        return info

    # --- 뷰용 토폴로지 ---
    def topology(self) -> dict:
        """직렬화 가능한 토폴로지 스냅샷: 링크·현재 라우팅 트리(D-003)."""
        links = []
        for u, nbrs in self.neighbors.items():
            for v in nbrs:
                if u < v:
                    links.append((u, v))
        route_edges = [
            (nid, nh) for nid, nh in self.next_hop.items() if nh is not None
        ]
        return {"links": links, "route_edges": route_edges}
