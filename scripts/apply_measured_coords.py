"""apply_measured_coords.py — 실측 좌표 16개를 deploy_config.json 에 넣는다.

    python scripts/apply_measured_coords.py coords.txt
    type coords.txt | python scripts/apply_measured_coords.py -      (붙여넣기)

입력 형식 — 16줄, 순서는 상관없다:

    n01 x=5.0 y=5.0 h=3.45
    n02 x=25.1 y=4.9 h=3.44
    ...

  · 단위는 **cm** 로 받는다(자로 재서 적기 편한 단위). 파일에는 m 로 저장한다.
    `--unit m` 을 주면 m 로 읽는다.
  · `h` (높이)는 받아만 두고 좌표에는 쓰지 않는다 — 추정은 2차원 평면이다.
    격자가 평평하지 않으면 그 자체가 오차원인이므로 편차만 보고한다.
  · 라벨 규약은 **nXX -> id = XX-1** 이다(n01→id0). 한 칸만 밀려도 방향이 통째로 돌아간다.

하는 일
  1) 16개를 다 받았는지, 중복·누락이 없는지 확인
  2) **명목 격자값과 전부 같으면 거부한다** — 실측이라면서 안 옮겨 적은 경우다
  3) nodes[].x/y 갱신 + deployment.measured = true
  4) 배치검산 즉시 출력 (최근접거리 중앙값 vs spacing_m / 이웃수 분포 / 라벨 규약)

`--dry-run` 이면 파일을 쓰지 않고 검산만 한다.
"""
from __future__ import annotations
import argparse, io, json, math, os, re, sys
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(ROOT, "gateway", "deploy_config.json")
LINE = re.compile(r"^\s*n(\d{1,2})\s+x\s*=\s*(-?[\d.]+)\s+y\s*=\s*(-?[\d.]+)"
                  r"(?:\s+h\s*=\s*(-?[\d.]+))?\s*$", re.I)

def parse(text, unit):
    k = 0.01 if unit == "cm" else 1.0
    out, bad = {}, []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = LINE.match(raw)
        if not m:
            bad.append(raw.rstrip()); continue
        label = int(m.group(1))
        nid = label - 1                       # ★ nXX -> id = XX-1
        if nid in out:
            bad.append("중복: " + raw.rstrip()); continue
        out[nid] = (round(float(m.group(2)) * k, 6),
                    round(float(m.group(3)) * k, 6),
                    (float(m.group(4)) * k) if m.group(4) else None)
    return out, bad

def check(dep, pos):
    """배치검산 — 게이트웨이 시작 로그와 같은 세 줄을 여기서 미리 낸다."""
    sp = float(dep["deployment"]["spacing_m"])
    rr = float(dep["config"]["radio_range_m"])
    ids = sorted(pos)
    nn = []
    for i in ids:
        ds = [math.hypot(pos[i][0]-pos[j][0], pos[i][1]-pos[j][1]) for j in ids if j != i]
        if ds: nn.append(min(ds))
    nn.sort()
    med = nn[len(nn)//2] if nn else float("nan")
    off = abs(med - sp) / sp * 100 if sp else float("nan")
    print("  검산 ① 최근접거리 중앙값 %.4f m (설정 spacing_m %.3f, 차이 %.1f%%)%s"
          % (med, sp, off, "" if off <= 2 else "   ★ 2% 초과 — 좌표표를 의심할 것"))
    deg = Counter(sum(1 for j in ids if j != i and
                      math.hypot(pos[i][0]-pos[j][0], pos[i][1]-pos[j][1]) <= rr + 1e-12)
                  for i in ids)
    exp = {3: 4, 5: 8, 8: 4}
    print("  검산 ② 이웃수 분포 %s  (4x4 정격자 기대 %s)%s"
          % (dict(sorted(deg.items())), exp,
             "" if dict(sorted(deg.items())) == exp else "   ★ 기대와 다름"))
    print("  검산 ③ 라벨 규약  nXX -> id = XX-1  (n01->id0 … n16->id15)")
    hs = [v[2] for v in pos.values() if v[2] is not None]
    if hs:
        print("  참고   높이 h  min %.4f / max %.4f / 편차 %.4f m (좌표에는 쓰지 않음)"
              % (min(hs), max(hs), max(hs)-min(hs)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="좌표 파일 경로, 또는 '-' 로 표준입력")
    ap.add_argument("--deploy", default=DEPLOY)
    ap.add_argument("--unit", choices=["cm", "m"], default="cm")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = sys.stdin.read() if a.src == "-" else io.open(a.src, encoding="utf-8").read()
    pos, bad = parse(text, a.unit)
    if bad:
        print("★ 형식이 맞지 않는 줄 %d개 — 하나라도 있으면 진행하지 않는다:" % len(bad))
        for b in bad[:8]: print("    %s" % b)
        sys.exit(2)

    dep = json.load(io.open(a.deploy, encoding="utf-8"))
    need = {int(n["id"]) for n in dep["nodes"]}
    miss, extra = sorted(need - set(pos)), sorted(set(pos) - need)
    if miss or extra:
        print("★ 노드 수가 맞지 않는다 — 받은 %d개 / 필요 %d개" % (len(pos), len(need)))
        if miss:  print("    빠진 id: %s  (라벨로는 %s)" % (miss, ["n%02d" % (i+1) for i in miss]))
        if extra: print("    모르는 id: %s" % extra)
        sys.exit(2)

    nominal = {int(n["id"]): (float(n["x"]), float(n["y"])) for n in dep["nodes"]}
    same = all(math.isclose(pos[i][0], nominal[i][0], abs_tol=1e-6) and
               math.isclose(pos[i][1], nominal[i][1], abs_tol=1e-6) for i in need)
    if same:
        # D-068 과 같은 규율: '실측했다'와 '좌표가 안 바뀌었다'가 동시에 참일 수 없다.
        print("★ 거부 — 받은 16개가 명목 격자값과 **전부 일치**한다.")
        print("   실측값을 옮겨 적지 않았거나, 명목표를 그대로 붙여넣은 것이다.")
        print("   measured=true 로 바꾸지 않는다.")
        sys.exit(3)

    d = [math.hypot(pos[i][0]-nominal[i][0], pos[i][1]-nominal[i][1]) for i in need]
    print("명목값 대비 이동량: 최대 %.4f m / 중앙 %.4f m / 0 인 노드 %d개"
          % (max(d), sorted(d)[len(d)//2], sum(1 for x in d if x < 1e-9)))
    print()
    check(dep, pos)

    if a.dry_run:
        print("\n--dry-run — 파일을 쓰지 않았다."); return
    for n in dep["nodes"]:
        i = int(n["id"]); n["x"], n["y"] = pos[i][0], pos[i][1]
    dep["deployment"]["measured"] = True
    dep["deployment"]["name"] = dep["deployment"].get("name", "") + "_measured" \
        if not str(dep["deployment"].get("name", "")).endswith("_measured") \
        else dep["deployment"]["name"]
    io.open(a.deploy, "w", encoding="utf-8", newline="").write(
        json.dumps(dep, ensure_ascii=False, indent=2) + "\n")
    print("\n갱신 완료 → %s   (deployment.measured = true)" % a.deploy)
    print("다음: python gateway/gateway.py --fw --port auto  로 시작 로그의 검산 3줄을 다시 확인할 것.")

if __name__ == "__main__":
    main()
