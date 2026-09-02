"""analyze_2k_c_verdict.py — 2.K §3 판정표 **정정** 재산출.

왜 필요한가(정직 기록): `run_2k_c.py`가 런 중에 찍은 '추정불능도 ≤80℃대조군' 열은
**대조군 자신이 100 % 불능일 때 무조건 통과**하는 퇴화 비교였다. 예: warn_fixed·τ=78.5·peak300
에서 thr40의 불능률 100 %가 "대조군(100 %) 이하"라 통과로 찍혔다. 아무것도 채택되지 않았으므로
오탐도 0 %가 되어, **세 조건이 전부 '통과'로 보이는데 실제로는 시스템이 아무 출력도 못 낸다.**

⇒ 불능률만은 **절대 기준**으로 다시 잰다. 구조적 바닥(K_confirm=3 탓에 baseline도 ~13 %)을
   근거로 **≤20 %**를 쓴다. 이 값은 테스트 점수를 보고 고른 게 아니라 baseline 13 %에
   여유 7 %p를 준 것이며, 아래 표에 baseline 실측값을 같이 찍어 근거를 남긴다.
원자료는 손대지 않는다 — 판정 규칙만 정정한다.
"""
import csv, os, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
BLIND_LIMIT = 20.0
D = os.path.join("results", "stress")
rows = list(csv.DictReader(open(os.path.join(D, "summary_2k_c_verdict.csv"), encoding="utf-8")))
for r in rows:
    for k in ("threshold_C","tau_s","peak_C","miss_rate","blind_rate","blind_baseline_80C",
              "fp_pollution","fp_baseline_80C"):
        r[k] = float(r[k])

print("="*104)
print("★★ 2.K §3 정정 판정표 — 세 조건 동시 충족 임계 구간")
print(f"   ① 미탐지 ≤5 %   ② 2.D 오탐 ≤ 80℃대조군 실측   ③ 추정불능 ≤{BLIND_LIMIT:.0f} % (절대, baseline~13 %)")
print("="*104)
out=[]
for arm in ("warn_fixed","warn_coupled"):
    print(f"\n  ── {arm} ──")
    for tau in (11.0, 78.5):
        base_fp = next(r["fp_baseline_80C"] for r in rows if r["arm"]==arm and r["tau_s"]==tau)
        print(f"    τ={tau:.1f}s  (오탐 기준 {base_fp:.2f} %)")
        print(f"      {'피크℃':>6s} {'①미탐지≤5':>26s} {'②+오탐OK':>22s} {'③+추정가능':>22s}")
        for pk in (150.,200.,300.,500.):
            s = sorted([r for r in rows if r["arm"]==arm and r["tau_s"]==tau and r["peak_C"]==pk],
                       key=lambda r: r["threshold_C"])
            a=[r["threshold_C"] for r in s if r["miss_rate"]<=5]
            b=[r["threshold_C"] for r in s if r["miss_rate"]<=5 and r["fp_pollution"]<=base_fp+1e-9]
            c=[r["threshold_C"] for r in s if r["miss_rate"]<=5 and r["fp_pollution"]<=base_fp+1e-9
               and r["blind_rate"]<=BLIND_LIMIT]
            f=lambda L:("없음" if not L else f"{min(L):.0f}~{max(L):.0f}℃({len(L)})")
            print(f"      {pk:6.0f} {f(a):>26s} {f(b):>22s} {f(c):>22s}")
            for r in s:
                r2=dict(r); r2["pass_final"]=int(r["threshold_C"] in c); out.append(r2)
print("\n" + "="*104)
print("★ 퇴화 통과 사례 — 오탐 0 %인데 실은 '아무것도 채택 안 됨'이라 0 %인 셀")
print("="*104)
print(f"  {'arm':13s} {'τ':>6s} {'peak':>6s} {'thr':>5s} {'미탐지':>8s} {'오탐':>8s} {'추정불능':>9s}")
n=0
for r in rows:
    if r["miss_rate"]<=5 and r["fp_pollution"]<=r["fp_baseline_80C"]+1e-9 and r["blind_rate"]>BLIND_LIMIT:
        n+=1
        print(f"  {r['arm']:13s} {r['tau_s']:6.1f} {r['peak_C']:6.0f} {r['threshold_C']:5.0f} "
              f"{r['miss_rate']:8.1f} {r['fp_pollution']:8.2f} {r['blind_rate']:9.1f}")
print(f"\n  → 퇴화 통과 {n} 셀. 이들을 '통과'로 세면 임계 하향이 실제보다 유리해 보인다.")
with open(os.path.join(D,"summary_2k_c_verdict_corrected.csv"),"w",newline="",encoding="utf-8") as fh:
    w=csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
print(f"\n  [csv] {os.path.join(D,'summary_2k_c_verdict_corrected.csv')} ({len(out)} rows)")
