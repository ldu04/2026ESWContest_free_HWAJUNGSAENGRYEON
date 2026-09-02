// 불사 — 확정 스타일 B+ (라이트 에디토리얼 + 도착시각 노드필드 은은하게)
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: "맑은 고딕", bodyFontFace: "맑은 고딕" };
const C = { INK:"1F2421", FOREST:"2C5F2D", MOSS:"97BC62", EMBER:"D35400", EMBER2:"E8A15C",
  ASH:"6B6E6A", PAPER:"FBF9F4", LINE:"E2DCD0", WHITE:"FFFFFF" };
const F = "맑은 고딕";

// 도착시각 노드필드 — 라이트 배경용, 은은한 메시+그라데이션
// dots를 완만한 격자(고정 지터)로, 색은 좌→우 ember→forest (불이 왼쪽에서 옴)
function arrivalMesh(slide, x, y, w, h, cols, rows) {
  const grad = [C.EMBER, C.EMBER2, C.MOSS, C.FOREST];
  const jit = [0.06,-0.05,0.04,-0.03,0.05,-0.06,0.03,-0.04]; // 결정적 미세 흔들림
  const pos = [];
  for (let r=0;r<rows;r++){ pos[r]=[]; for(let cX=0;cX<cols;cX++){
    const nx = x + (w*(cX+0.5))/cols + jit[(r*cols+cX)%jit.length]*0.5;
    const ny = y + (h*(r+0.5))/rows + jit[(r*cols+cX+3)%jit.length]*0.5;
    pos[r][cX] = [nx, ny];
  }}
  // 얇은 메시 선 (가로·세로 이웃, 옅게)
  for (let r=0;r<rows;r++) for(let cX=0;cX<cols;cX++){
    if (cX<cols-1){const a=pos[r][cX],b=pos[r][cX+1];slide.addShape(pres.ShapeType.line,{x:a[0],y:a[1],w:b[0]-a[0],h:b[1]-a[1],line:{color:C.LINE,width:0.75}});}
    if (r<rows-1){const a=pos[r][cX],b=pos[r+1][cX];slide.addShape(pres.ShapeType.line,{x:a[0],y:a[1],w:b[0]-a[0],h:b[1]-a[1],line:{color:C.LINE,width:0.75}});}
  }
  // 노드
  for (let r=0;r<rows;r++) for(let cX=0;cX<cols;cX++){
    const t = cX/(cols-1);
    const col = grad[Math.min(grad.length-1, Math.floor(t*grad.length))];
    const d = 0.17;
    const [nx,ny]=pos[r][cX];
    slide.addShape(pres.ShapeType.ellipse,{x:nx-d/2,y:ny-d/2,w:d,h:d,fill:{color:col},line:{color:C.PAPER,width:1.25}});
  }
}
function header(slide, kicker, title) {
  slide.background={color:C.PAPER};
  slide.addText(kicker.toUpperCase(),{x:0.6,y:0.42,w:12.1,h:0.3,fontFace:F,fontSize:11,bold:true,color:C.EMBER,charSpacing:2});
  slide.addText(title,{x:0.58,y:0.72,w:12.15,h:0.7,fontFace:F,fontSize:26,bold:true,color:C.INK});
  slide.addShape(pres.ShapeType.line,{x:0.6,y:1.5,w:12.13,h:0,line:{color:C.LINE,width:1}});
}
function card(slide,x,y,w,h){slide.addShape(pres.ShapeType.roundRect,{x,y,w,h,rectRadius:0.06,fill:{color:C.WHITE},line:{color:C.LINE,width:1}});}

// ===== 표지 B+ =====
let s = pres.addSlide(); s.background={color:C.PAPER};
arrivalMesh(s, 7.35, 1.05, 5.25, 3.15, 6, 4); // 우상단 필드
// 필드 아래 은은한 진행 방향 (점과 안 겹치게 여백에)
s.addShape(pres.ShapeType.line,{x:7.55,y:4.55,w:4.4,h:0,line:{color:C.ASH,width:1.5,endArrowType:"triangle"}});
s.addText("불 진행 방향",{x:7.55,y:4.62,w:3,h:0.28,fontFace:F,fontSize:10,color:C.ASH});
s.addText("제24회 임베디드SW경진대회 · 자유공모 부문",{x:0.9,y:1.7,w:9,h:0.35,fontFace:F,fontSize:13,bold:true,color:C.EMBER,charSpacing:1});
s.addText("불사",{x:0.85,y:2.15,w:6.4,h:1.6,fontFace:F,fontSize:88,bold:true,color:C.INK});
s.addShape(pres.ShapeType.line,{x:0.95,y:3.95,w:2.1,h:0,line:{color:C.EMBER,width:3}});
s.addText([{text:"화중생련  ",options:{color:C.FOREST}},{text:"火中生蓮",options:{color:C.ASH}}],{x:0.9,y:4.15,w:9,h:0.5,fontFace:F,fontSize:20,bold:true});
s.addText("고장(노드 파괴)을 데이터로 바꾸는 자가치유 산불 감시 메시",{x:0.9,y:4.9,w:10.5,h:0.5,fontFace:F,fontSize:16,color:"50544B"});
s.addShape(pres.ShapeType.line,{x:0.9,y:6.35,w:11.5,h:0,line:{color:C.LINE,width:1}});
s.addText([{text:"이동욱",options:{bold:true,color:C.INK}},{text:"  전자공학전공 · 숭실대학교",options:{color:C.ASH}}],{x:0.9,y:6.5,w:8,h:0.4,fontFace:F,fontSize:13});

// ===== 본문 샘플 1 — 차별성 표 (B+ 톤) =====
s = pres.addSlide();
header(s,"기존·유사제품과의 차별성  |  독창성 30","고장을 '손실'이 아니라 '데이터'로");
const hdr=t=>({text:t,options:{fontFace:F,fontSize:12.5,bold:true,color:C.WHITE,fill:{color:C.FOREST},valign:"middle",align:"left",margin:[4,6,4,6]}});
const cell=(t,o={})=>({text:t,options:{fontFace:F,fontSize:11,color:"3A3E37",valign:"middle",align:"left",margin:[4,6,4,6],...o}});
const ours=t=>cell(t,{color:C.INK,bold:true,fill:{color:"EEF3E6"}});
const rows=[
  [hdr("비교 대상"),hdr("그들의 방식"),hdr("한계"),hdr("우리 (불사)")],
  [cell("온도 스트리밍",{bold:true,color:C.INK}),cell("살아있는 노드가 온도 상시 전송"),cell("초저가 대량 노드엔 상시 전송 부담(전력·대역폭)"),ours("교차검증된 '죽음'을 확정 이진 신호로 → 화선 위치·방향·속도")],
  [cell("Dryad Silvanet",{bold:true,color:C.INK}),cell("불 오기 전 조기 감지(내열, +85℃ 한계)"),cell("불 속에선 못 버팀 — 감지 특화, 전선 추적 아님"),ours("타 죽으며 화선을 그림 — 감지(그들)와 추적(우리)은 상보")],
  [cell("stock ESP-MESH",{bold:true,color:C.INK}),cell("노드 죽으면 경로 우회(연결성만)"),cell("죽음을 손실로만 처리, 정보로 안 씀"),ours("죽음을 1급 이벤트로 승격 + 도착시각 추정 + 오탐 방어")],
  [cell("드론·위성",{bold:true,color:C.INK}),cell("상공·우주 광역 개요"),cell("연기·수목 아래 지표 화선·초 단위 변화 못 봄"),ours("지표 실측 레이어 + 지상 통신 백본 — 대체 아니라 상보")],
];
s.addTable(rows,{x:0.6,y:1.7,w:12.13,colW:[1.9,2.75,3.2,4.28],rowH:[0.4,0.82,0.82,0.82,0.82],border:{type:"solid",color:C.LINE,pt:1},valign:"middle"});
s.addText([{text:"★ 헤드라인 차별점  ",options:{bold:true,color:C.EMBER}},{text:"오탐 방어(통신두절 vs 진짜 파괴 구분) = stock 메시가 못 하는 우리만의 계층.",options:{color:C.INK}}],{x:0.6,y:6.55,w:12.13,h:0.4,fontFace:F,fontSize:13});
// 우하단 미니 필드 마크
arrivalMesh(s, 11.55, 6.75, 1.0, 0.55, 4, 2);

pres.writeFile({fileName:"불사_스타일확정_Bplus.pptx"}).then(fn=>console.log("SAVED",fn));
