#!/bin/sh
# 덱 렌더 + PNG 추출. LibreOffice 의 --convert-to png 는 첫 장만 내보내므로 PDF 를 거친다.
SO="/c/Program Files/LibreOffice/program/soffice.exe"
# 저장소 루트 — 스크립트 위치에서 유도한다(어느 PC 에서도 돈다)
BASE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$1"; TAG="$2"
rm -f "$BASE/results/render/$(basename "$SRC" .pptx).pdf"
"$SO" --headless --norestore --convert-to pdf --outdir "$BASE/results/render" "$SRC" >/dev/null 2>&1
python - "$BASE/results/render/$(basename "$SRC" .pptx).pdf" "$BASE/results/render/$TAG" <<'PY'
import sys, os, fitz
pdf, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
d=fitz.open(pdf)
for i in range(d.page_count):
    d[i].get_pixmap(matrix=fitz.Matrix(2,2)).save(os.path.join(out,"s%02d.png"%(i+1)))
print("렌더 %d쪽 → %s" % (d.page_count, out))
PY
