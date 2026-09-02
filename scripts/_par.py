"""_par.py — 2.K 스윕용 **결정론적 병렬 실행** 도우미.

왜 필요한가: 2.K의 세 스윕(임계·속도/ETA·바람결합)은 2.J보다 축이 하나씩 더 많아
단일 프로세스로는 수 시간이 걸린다. 그런데 **각 런은 cfg(=seed 포함) 하나로 완전히 결정**되므로
(sim/config.py 문서 규약) 실행 순서를 바꿔도 결과가 바뀌지 않는다 → 병렬화는 **안전**하다.

★ 규율
  · 워커는 `sim/` 를 **읽기만** 한다. estimator.py 포함 어떤 파일도 수정하지 않는다.
  · 결과 취합은 **입력 인덱스 순서**로 되돌린다(`imap`이 아니라 순서 보존 취합) → 출력 CSV가
    직렬 실행과 **행 순서까지 동일**하다.
  · 워커 수를 바꿔도 수치가 달라지지 않아야 한다(회귀로 확인 가능).
"""
from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def n_workers(reserve: int = 2) -> int:
    return max(1, (os.cpu_count() or 4) - reserve)


def pmap(fn, jobs, workers: int | None = None, label: str = "", chunksize: int | None = None):
    """jobs 를 fn 에 병렬 매핑하고 **입력 순서대로** 결과 리스트를 반환.

    fn 은 모듈 최상위 함수여야 한다(Windows spawn 은 피클링을 요구).
    """
    jobs = list(jobs)
    if not jobs:
        return []
    w = workers or n_workers()
    if w <= 1 or len(jobs) < 4:
        return [fn(j) for j in jobs]

    import multiprocessing as mp

    cs = chunksize or max(1, len(jobs) // (w * 8))
    t0 = time.time()
    done = 0
    out: list = [None] * len(jobs)
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=w) as pool:
        for i, r in pool.imap_unordered(_indexed(fn), list(enumerate(jobs)), chunksize=cs):
            out[i] = r
            done += 1
            if label and (done % max(1, len(jobs) // 20) == 0 or done == len(jobs)):
                el = time.time() - t0
                eta = el / done * (len(jobs) - done)
                print(f"    [{label}] {done}/{len(jobs)}  경과 {el/60:.1f}분  잔여 ~{eta/60:.1f}분",
                      flush=True)
    return out


class _indexed:
    """(i, job) -> (i, fn(job)). 피클 가능한 래퍼(람다 금지)."""

    def __init__(self, fn):
        self.fn = fn

    def __call__(self, ij):
        i, j = ij
        return i, self.fn(j)
