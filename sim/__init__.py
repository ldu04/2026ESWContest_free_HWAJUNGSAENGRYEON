"""failsafe-mesh 시뮬레이터 코어 (sim).

지시서 #1 §1 구조. 코어는 스냅샷(dict) 스트림을 산출하고, viz/metrics는 그 스트림만 소비한다.
"""
from .config import Config
from .node import Node, NodeState
from .fire import Fire
from .network import Network, build_grid
from .verification import Verifier
from .estimator import Estimator
from .metrics import Metrics
from .engine import run, Snapshot

__all__ = [
    "Config", "Node", "NodeState", "Fire", "Network", "build_grid",
    "Verifier", "Estimator", "Metrics", "run", "Snapshot",
]
