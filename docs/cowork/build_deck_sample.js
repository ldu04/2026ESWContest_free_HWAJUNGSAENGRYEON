// 불사(不死) / 화중생련 — 개발완료보고서 PPT 스타일 샘플
// 표지 + 대표 슬라이드 3장 (스타일 검증용)
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.theme = { headFontFace: "맑은 고딕", bodyFontFace: "맑은 고딕" };

// ---- 팔레트 (fire + forest + charcoal) ----
const C = {
  INK:   "1F2421", // 짙은 먹색(거의 검정, 녹빛)
  FOREST:"2C5F2D", // 딥 포레스트 그린 (브랜드 주색)
  MOSS:  "97BC62", // 모스 그린 (보조)
  EMBER: "D35400", // 불씨 주황 (강조 — 아껴 씀)
  EMBER2:"E8A15C", // 옅은 불빛
  ASH:   "6B6E6A", // 뮤트 그레이 (캡션)
  PAPER: "FBF9F4", // 따뜻한 종이색 배경
  LINE:  "E2DCD0", // 헤어라인
  WHITE: "FFFFFF",
};
const F = "맑은 고딕";

// ---- 메시-노드 모티프 (스트라이프 대신, 주제에 맞는 점-네트워크) ----
// dead=true면 불씨색으로 (화선에 타 죽은 노드 암시)
function meshMotif(slide, ox, oy, scale, onDark) {
  const nodes = [
    [0.0,0.15,0],[0.9,0.0,0],[1.7,0.35,0],[2.5,0.1,0],
    [0.4,1.0,1],[1.3,0.85,1],[2.1,1.15,1],
    [0.1,1.8,0],[1.0,1.75,0],[1.9,2.0,0],[2.6,1.7,0],
  ]; // [x,y,dead]
  const edges = [[0,1],[1,2],[2,3],[0,4],[1,5],[2,6],[4,5],[5,6],[4,7],[5,8],[6,9],[9,10],[3,10]];
  const px = (v) => ox + v * scale, py = (v) => oy + v * scale;
  edges.forEach(([a,b]) => {
    const na = nodes[a], nb = nodes[b];
    slide.addShape(pres.ShapeType.line, {
      x: px(na[0]), y: py(na[1]), w: px(nb[0]) - px(na[0]), h: py(nb[1]) - py(na[1]),
      line: { color: onDark ? "3A4A3A" : C.LINE, width: 0.75 },
    });
  });
  nodes.forEach(([x,y,dead]) => {
    const d = 0.11 * scale;
    slide.addShape(pres.ShapeType.ellipse, {
      x: px(x) - d/2, y: py(y) - d/2, w: d, h: d,
      fill: { color: dead ? C.EMBER : (onDark ? C.MOSS : C.FOREST) },
      line: { type: "none" },
    });
  });
}

// ---- 콘텐츠 슬라이드 공통 헤더 (kicker 라벨 + 제목 + 헤어라인) ----
function header(slide, kicker, title) {
  slide.background = { color: C.PAPER };
  slide.addText(kicker.toUpperCase(), {
    x: 0.6, y: 0.42, w: 12.1, h: 0.3, fontFace: F, fontSize: 11, bold: true,
    color: C.EMBER, charSpacing: 2, align: "left",
  });
  slide.addText(title, {
    x: 0.58, y: 0.72, w: 12.15, h: 0.7, fontFace: F, fontSize: 26, bold: true,
    color: C.INK, align: "left",
  });
  slide.addShape(pres.ShapeType.line, {
    x: 0.6, y: 1.5, w: 12.13, h: 0, line: { color: C.LINE, width: 1 },
  });
  // 우하단 작은 모티프 마크
  meshMotif(slide, 12.35, 6.9, 0.16, false);
}

// 카드(옅은 테두리, 채움 최소) — 스트라이프/컬러바 아님
function card(slide, x, y, w, h, tint) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: tint || C.WHITE }, line: { color: C.LINE, width: 1 },
  });
}

// =====================================================================
// 슬라이드 1 — 표지
// =====================================================================
let s = pres.addSlide();
s.background = { color: C.INK };
meshMotif(s, 9.1, 1.0, 0.62, true); // 우측 큰 메시 모티프
s.addText("제24회 임베디드SW경진대회  ·  자유공모 부문", {
  x: 0.85, y: 1.7, w: 8, h: 0.35, fontFace: F, fontSize: 14, color: C.MOSS, bold: true, charSpacing: 1,
});
s.addText(
  [
    { text: "불사 ", options: { color: C.WHITE, bold: true } },
    { text: "不死", options: { color: C.EMBER, bold: true } },
  ],
  { x: 0.8, y: 2.15, w: 9, h: 1.5, fontFace: F, fontSize: 72, align: "left" }
);
s.addText(
  [
    { text: "화중생련  ", options: { color: C.MOSS } },
    { text: "火中生蓮", options: { color: C.MOSS } },
  ],
  { x: 0.85, y: 3.65, w: 9, h: 0.5, fontFace: F, fontSize: 22, bold: true, align: "left" }
);
s.addText("고장(노드 파괴)을 데이터로 바꾸는 자가치유 산불 감시 메시", {
  x: 0.85, y: 4.35, w: 9.5, h: 0.5, fontFace: F, fontSize: 16, color: "CFD6CB",
});
// 하단 정보 바 (텍스트만)
s.addShape(pres.ShapeType.line, { x: 0.85, y: 6.35, w: 11.6, h: 0, line: { color: "3A4A3A", width: 1 } });
s.addText(
  [
    { text: "이동욱", options: { bold: true, color: C.WHITE } },
    { text: "  전자공학전공 · 숭실대학교", options: { color: "AEB5AC" } },
  ],
  { x: 0.85, y: 6.5, w: 7, h: 0.4, fontFace: F, fontSize: 13, align: "left" }
);
s.addText("GitHub · 시연영상 링크는 제출본에 삽입", {
  x: 7.5, y: 6.5, w: 4.95, h: 0.4, fontFace: F, fontSize: 12, color: "8A928A", align: "right",
});

// =====================================================================
// 슬라이드 2 — 개발 개요·동기
// =====================================================================
s = pres.addSlide();
header(s, "개발 동기·배경  |  독창성", "재난에선 노드 파괴가 '필연'이다");
s.addText(
  [
    { text: "산불·지진·붕괴 현장에서 센서 노드는 ", options: {} },
    { text: "반드시 죽는다", options: { bold: true, color: C.EMBER } },
    { text: ". 기존 시스템은 이 죽음을 단순 '손실'로 처리한다.\n우리는 ", options: {} },
    { text: "죽음의 시공간 패턴 자체를 데이터로 승격", options: { bold: true, color: C.FOREST } },
    { text: "해, 사라진 노드들이 오히려 불의 방향·속도를 그리게 한다.", options: {} },
  ],
  { x: 0.6, y: 1.75, w: 12.1, h: 1.0, fontFace: F, fontSize: 15, color: C.INK, lineSpacingMultiple: 1.25 }
);
const cards = [
  ["문제 정의", "위성·드론은 연기·수목 아래 지표 화선을 못 본다. 진화 지휘·대원 안전이 직결된 실시간 공백.", C.ASH],
  ["기존의 공백", "stock 메시는 죽은 노드를 우회만 할 뿐, 그 죽음에 담긴 정보를 버린다.", C.ASH],
  ["우리 목표", "고장 패턴을 데이터로 + 자가치유로, 그 공백을 지상에서 실시간으로 채운다.", C.FOREST],
];
const cw = 3.85, gap = 0.28, cx0 = 0.6, cy = 3.05, ch = 2.55;
cards.forEach((c, i) => {
  const x = cx0 + i * (cw + gap);
  card(s, x, cy, cw, ch, C.WHITE);
  s.addText(c[0], { x: x + 0.28, y: cy + 0.28, w: cw - 0.56, h: 0.4, fontFace: F, fontSize: 15, bold: true, color: c[2] });
  s.addShape(pres.ShapeType.line, { x: x + 0.28, y: cy + 0.78, w: 0.6, h: 0, line: { color: C.EMBER, width: 2 } });
  s.addText(c[1], { x: x + 0.28, y: cy + 0.95, w: cw - 0.56, h: ch - 1.2, fontFace: F, fontSize: 13, color: "44483F", lineSpacingMultiple: 1.22, valign: "top" });
});
s.addText("→ 응용(산불)이 아니라 아키텍처(고장→데이터+자가치유)에 독창성이 있다.", {
  x: 0.6, y: 5.75, w: 12.1, h: 0.4, fontFace: F, fontSize: 13, italic: true, color: C.FOREST, bold: true,
});

// =====================================================================
// 슬라이드 3 — 차별성 4축 표
// =====================================================================
s = pres.addSlide();
header(s, "기존·유사제품과의 차별성  |  독창성 30", "고장을 '손실'이 아니라 '데이터'로");
const hdr = (t) => ({ text: t, options: { fontFace: F, fontSize: 12.5, bold: true, color: C.WHITE, fill: { color: C.FOREST }, valign: "middle", align: "left", margin: [4, 6, 4, 6] } });
const cell = (t, opts = {}) => ({ text: t, options: { fontFace: F, fontSize: 11, color: "3A3E37", valign: "middle", align: "left", margin: [4, 6, 4, 6], ...opts } });
const ours = (t) => cell(t, { color: C.INK, bold: true, fill: { color: "EEF3E6" } });
const rows = [
  [hdr("비교 대상"), hdr("그들의 방식"), hdr("한계"), hdr("우리 (불사)")],
  [cell("온도 스트리밍", { bold: true, color: C.INK }), cell("살아있는 노드가 온도 상시 전송"), cell("초저가 대량 노드엔 상시 전송 부담(전력·대역폭)"), ours("교차검증된 '죽음'을 확정 이진 신호로 → 화선 위치·방향·속도")],
  [cell("Dryad Silvanet", { bold: true, color: C.INK }), cell("불 오기 전 조기 감지(내열, +85℃ 한계)"), cell("불 속에선 못 버팀 — 감지 특화, 전선 추적 아님"), ours("타 죽으며 화선을 그림 — 감지(그들)와 추적(우리)은 상보")],
  [cell("stock ESP-MESH", { bold: true, color: C.INK }), cell("노드 죽으면 경로 우회(연결성만)"), cell("죽음을 손실로만 처리, 정보로 안 씀"), ours("죽음을 1급 이벤트로 승격 + 도착시각 추정 + 오탐 방어")],
  [cell("드론·위성", { bold: true, color: C.INK }), cell("상공·우주 광역 개요"), cell("연기·수목 아래 지표 화선·초 단위 변화 못 봄"), ours("지표 실측 레이어 + 지상 통신 백본 — 대체 아니라 상보")],
];
s.addTable(rows, {
  x: 0.6, y: 1.7, w: 12.13, colW: [1.9, 2.75, 3.2, 4.28], rowH: [0.4, 0.82, 0.82, 0.82, 0.82],
  border: { type: "solid", color: C.LINE, pt: 1 }, valign: "middle",
});
s.addText(
  [
    { text: "★ 헤드라인 차별점  ", options: { bold: true, color: C.EMBER } },
    { text: "오탐 방어(통신두절 vs 진짜 파괴 구분) = stock 메시가 못 하는 우리만의 계층.", options: { color: C.INK } },
  ],
  { x: 0.6, y: 6.55, w: 12.13, h: 0.4, fontFace: F, fontSize: 13, align: "left" }
);

// =====================================================================
// 슬라이드 4 — ★ 도착시각 추정 알고리즘 개념
// =====================================================================
s = pres.addSlide();
header(s, "★ 핵심 알고리즘  |  기술성·완성도 30", "죽은 노드의 (좌표·시각) → 불의 방향·속도");
// 좌: 3-스텝
const steps = [
  ["1", "죽은 시각 수집", "각 노드가 임계온도에 타 죽은 시각 = 불이 그 지점에 도착한 시각."],
  ["2", "최소제곱 평면 적합", "흩어진 (x, y, 죽은시각) 점들에 가장 잘 맞는 면을 긋는다 (딥러닝 아님)."],
  ["3", "기울기 → 방향·속도", "평면의 기울기 방향 = 진행 방향, 1 / 기울기 크기 = 진행 속도."],
];
let sy = 1.85;
steps.forEach((st) => {
  s.addShape(pres.ShapeType.ellipse, { x: 0.62, y: sy, w: 0.5, h: 0.5, fill: { color: C.FOREST }, line: { type: "none" } });
  s.addText(st[0], { x: 0.62, y: sy, w: 0.5, h: 0.5, fontFace: F, fontSize: 18, bold: true, color: C.WHITE, align: "center", valign: "middle" });
  s.addText(st[1], { x: 1.28, y: sy - 0.04, w: 5.7, h: 0.4, fontFace: F, fontSize: 15, bold: true, color: C.INK });
  s.addText(st[2], { x: 1.28, y: sy + 0.35, w: 5.7, h: 0.7, fontFace: F, fontSize: 12.5, color: "50544B", lineSpacingMultiple: 1.15 });
  sy += 1.32;
});
// 우: 개념 다이어그램 (도착시각 그라데이션 + 방향 화살표)
const dx = 7.55, dy = 1.95, dw = 5.05, dh = 3.55;
card(s, dx, dy, dw, dh, C.WHITE);
s.addText("도착시각 지도 (개념)", { x: dx + 0.25, y: dy + 0.18, w: dw - 0.5, h: 0.35, fontFace: F, fontSize: 12, bold: true, color: C.ASH });
// 노드들: 왼→오 갈수록 죽은시각 늦음(불이 왼쪽에서 옴) — 색으로 표현
const grid = [];
for (let r = 0; r < 3; r++) for (let cX = 0; cX < 4; cX++) grid.push([cX, r]);
grid.forEach(([gx, gy]) => {
  const nx = dx + 0.75 + gx * 1.05, ny = dy + 1.05 + gy * 0.8;
  const t = gx / 3; // 0(먼저죽음)~1(나중죽음)
  const col = t < 0.34 ? C.EMBER : t < 0.67 ? C.EMBER2 : C.MOSS;
  s.addShape(pres.ShapeType.ellipse, { x: nx, y: ny, w: 0.26, h: 0.26, fill: { color: col }, line: { color: C.WHITE, width: 1 } });
});
// 방향 화살표
s.addShape(pres.ShapeType.line, { x: dx + 0.75, y: dy + 3.05, w: 3.3, h: 0, line: { color: C.INK, width: 2.5, endArrowType: "triangle" } });
s.addText("불 진행 방향", { x: dx + 0.75, y: dy + 3.12, w: 3.5, h: 0.3, fontFace: F, fontSize: 11, bold: true, color: C.INK });
s.addText("먼저 죽음", { x: dx + 0.55, y: dy + 0.62, w: 1.2, h: 0.28, fontFace: F, fontSize: 9.5, color: C.EMBER, align: "center" });
s.addText("나중 죽음", { x: dx + 3.35, y: dy + 0.62, w: 1.2, h: 0.28, fontFace: F, fontSize: 9.5, color: C.FOREST, align: "center" });
// 하단 노트
s.addText(
  [
    { text: "가벼운 최소제곱 — 저사양 게이트웨이에서 즉시 계산.  ", options: { color: "50544B" } },
    { text: "방향 견고(2.1°), 속도는 보수적(안전마진).", options: { bold: true, color: C.FOREST } },
  ],
  { x: 0.62, y: 6.35, w: 11.9, h: 0.4, fontFace: F, fontSize: 12.5, align: "left" }
);

pres.writeFile({ fileName: "불사_PPT_스타일샘플.pptx" }).then((fn) => console.log("SAVED", fn));
