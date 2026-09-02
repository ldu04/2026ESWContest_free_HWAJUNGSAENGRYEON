#!/usr/bin/env bash
# pi_check.sh — 파이에서 **하드웨어 없이** 소프트웨어 경로를 통째로 검증한다.
#
# 왜 (2026-09-01)
# ---------------
# 「파이는 테스트 안 해도 괜찮은가?」에 대한 답. 판도 브리지도 필요 없다.
# 노트북에서 만든 16노드 합성 스트림을 파이의 게이트웨이에 그대로 먹여서
# 파이썬 버전 · pyserial · CPU 속도 · 디스크 · 대시보드 생성까지 한 번에 본다.
#
# 노트북에서 먼저:
#     scp results/mockrun/full16.jsonl bulsa@<파이IP>:failsafe-mesh/results/mockrun/
#     scp -r gateway scripts tools docs bulsa@<파이IP>:failsafe-mesh/
#
# 파이에서:
#     bash tools/pi_check.sh
#
# 기대값(노트북 기준):
#     확정사망 16 · 채택 16 / 제외 0 · branch1_last_gasp 16건
#     t_source last_gasp_node_stamp 16 · UNRELIABLE 0건
#     data.js 약 7 MB
set -u
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python3
[ -x "$PY" ] || PY=python3

echo "=============================================================="
echo "  파이 소프트웨어 경로 검증 — 하드웨어 불필요"
echo "=============================================================="
echo "  호스트 : $(hostname)  ·  $(date '+%F %T %Z')"
echo "  파이썬 : $($PY -V 2>&1)"
echo "  pyserial: $($PY -c 'import serial;print(serial.__version__)' 2>&1)"
echo

echo "── 1) 디스크 여유 (SD 카드가 차면 산출물이 통째로 날아간다) ──"
df -h / | awk 'NR==1||NR==2{print "   "$0}'
echo

echo "── 2) 코드 신원 — 노트북과 같은 판인지 ──"
$PY - <<'EOF'
import hashlib, os
files = ["gateway/gateway.py","gateway/fw_adapter.py","gateway/serial_source.py",
         "gateway/deploy_config.json","scripts/rollcall.py","scripts/run_cue.py",
         "firmware/node/config.h"]
d = {}
for f in files:
    if os.path.isfile(f):
        d[f] = hashlib.md5(open(f,"rb").read()).hexdigest()[:8]
        print("   %-34s %s" % (f, d[f]))
    else:
        print("   %-34s ★없음" % f)
c = hashlib.md5("".join("%s:%s"%(k,v) for k,v in sorted(d.items())).encode()).hexdigest()[:12]
print("   %-34s %s   ← 노트북과 같아야 한다" % ("→ 합산 지문", c))
EOF
echo

echo "── 3) 진실성 검사 ──"
$PY tools/check_truth.py 2>&1 | tail -4
echo

echo "── 4) 16노드 전체 루프를 게이트웨이에 통과 (합성, fake=1) ──"
if [ ! -f results/mockrun/full16.jsonl ]; then
  echo "   ★ results/mockrun/full16.jsonl 이 없다. 노트북에서 scp 할 것"
  echo "     (또는: $PY gateway/mock_fw_serial.py --fake 1 --origin '0.02,-0.11' \\"
  echo "              --speed 0.000579 --t-max 1450 --out results/mockrun/full16.jsonl)"
else
  mkdir -p results/pi_check
  START=$(date +%s)
  $PY gateway/gateway.py --port - --fw --emit-dashboard \
      --out-deaths results/pi_check/deaths.csv \
      --out-js     results/pi_check/data.js \
      --out-json   results/pi_check/data.json \
      < results/mockrun/full16.jsonl 2>&1 | grep -E "확정사망|비화재 선별|branch1|요약|대시보드|WARNING" | sed 's/^/   /'
  echo "   소요 $(( $(date +%s) - START ))초"
  ls -lh results/pi_check/data.js 2>/dev/null | awk '{print "   data.js "$5}'
fi
echo

echo "── 5) 대시보드 서버 기동 확인 (5초) ──"
( $PY -m http.server 8000 --directory dashboard >/dev/null 2>&1 & echo $! > /tmp/_ds.pid )
sleep 2
if command -v curl >/dev/null 2>&1; then
  curl -s -o /dev/null -w "   HTTP %{http_code} · %{time_total}s\n" http://127.0.0.1:8000/ || echo "   ★ 응답 없음"
else
  echo "   curl 없음 — 브라우저로 http://<파이IP>:8000/ 확인할 것"
fi
kill "$(cat /tmp/_ds.pid)" 2>/dev/null; rm -f /tmp/_ds.pid
echo
echo "★ 여기까지 전부 정상이면 파이 소프트웨어 경로는 검증된 것이다."
echo "  남은 것은 하드웨어(브리지+16노드)뿐이고, 그건 tools/run_gate.py 가 본다."
