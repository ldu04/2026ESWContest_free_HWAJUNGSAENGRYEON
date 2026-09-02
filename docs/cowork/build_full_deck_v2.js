// 불사(不死→한글) / 화중생련 — 개발완료보고서 PPT 전체 (B+ 스타일)
// 표지 + 본문 ~18P. 🟢 확정 / 🟡 실측대기(자리만)
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: "맑은 고딕", bodyFontFace: "맑은 고딕" };
const C = { INK:"1F2421", FOREST:"2C5F2D", MOSS:"97BC62", EMBER:"D35400", EMBER2:"E8A15C",
  ASH:"6B6E6A", PAPER:"FBF9F4", LINE:"E2DCD0", WHITE:"FFFFFF", TINT:"EEF3E6", AMB:"FBEFE2" };
const F = "맑은 고딕";
let PAGE = 0;

// ---------- 헬퍼 ----------
function arrivalMesh(slide, x, y, w, h, cols, rows) {
  const grad=[C.EMBER,C.EMBER2,C.MOSS,C.FOREST];
  const jit=[0.06,-0.05,0.04,-0.03,0.05,-0.06,0.03,-0.04];
  const pos=[];
  for(let r=0;r<rows;r++){pos[r]=[];for(let cX=0;cX<cols;cX++){
    const nx=x+(w*(cX+0.5))/cols+jit[(r*cols+cX)%jit.length]*0.5;
    const ny=y+(h*(r+0.5))/rows+jit[(r*cols+cX+3)%jit.length]*0.5;
    pos[r][cX]=[nx,ny];}}
  for(let r=0;r<rows;r++)for(let cX=0;cX<cols;cX++){
    if(cX<cols-1){const a=pos[r][cX],b=pos[r][cX+1];slide.addShape(pres.ShapeType.line,{x:a[0],y:a[1],w:b[0]-a[0],h:b[1]-a[1],line:{color:C.LINE,width:0.75}});}
    if(r<rows-1){const a=pos[r][cX],b=pos[r+1][cX];slide.addShape(pres.ShapeType.line,{x:a[0],y:a[1],w:b[0]-a[0],h:b[1]-a[1],line:{color:C.LINE,width:0.75}});}}
  for(let r=0;r<rows;r++)for(let cX=0;cX<cols;cX++){
    const t=cX/(cols-1),col=grad[Math.min(grad.length-1,Math.floor(t*grad.length))],d=0.17,[nx,ny]=pos[r][cX];
    slide.addShape(pres.ShapeType.ellipse,{x:nx-d/2,y:ny-d/2,w:d,h:d,fill:{color:col},line:{color:C.PAPER,width:1.25}});}
}
function header(slide,kicker,title){
  slide.background={color:C.PAPER};
  slide.addText(kicker.toUpperCase(),{x:0.6,y:0.4,w:12.1,h:0.3,fontFace:F,fontSize:11,bold:true,color:C.EMBER,charSpacing:2});
  slide.addText(title,{x:0.58,y:0.7,w:12.15,h:0.62,fontFace:F,fontSize:25,bold:true,color:C.INK});
  slide.addShape(pres.ShapeType.line,{x:0.6,y:1.42,w:12.13,h:0,line:{color:C.LINE,width:1}});
}
function footer(slide,tag){
  PAGE++;
  slide.addText("불사 · 화중생련",{x:0.6,y:7.05,w:5,h:0.3,fontFace:F,fontSize:9,color:C.ASH});
  slide.addText(String(PAGE),{x:12.4,y:7.05,w:0.35,h:0.3,fontFace:F,fontSize:9,color:C.ASH,align:"right"});
  arrivalMesh(slide,11.35,6.98,0.85,0.42,4,2);
  if(tag){slide.addText(tag,{x:6.0,y:7.05,w:5,h:0.3,fontFace:F,fontSize:8.5,color:"B9B3A6",align:"right"});}
}
function card(slide,x,y,w,h,fill){slide.addShape(pres.ShapeType.roundRect,{x,y,w,h,rectRadius:0.06,fill:{color:fill||C.WHITE},line:{color:C.LINE,width:1}});}
// 제목+본문 카드
function infoCard(slide,x,y,w,h,title,body,titleColor,tint){
  card(slide,x,y,w,h,tint);
  slide.addText(title,{x:x+0.25,y:y+0.22,w:w-0.5,h:0.4,fontFace:F,fontSize:14.5,bold:true,color:titleColor||C.INK});
  slide.addShape(pres.ShapeType.line,{x:x+0.25,y:y+0.7,w:0.55,h:0,line:{color:C.EMBER,width:2}});
  slide.addText(body,{x:x+0.25,y:y+0.85,w:w-0.5,h:h-1.1,fontFace:F,fontSize:12,color:"44483F",lineSpacingMultiple:1.2,valign:"top"});
}
// 통계 박스
function statBox(slide,x,y,w,val,label,sub){
  card(slide,x,y,w,1.5,C.WHITE);
  slide.addText(val,{x:x,y:y+0.2,w:w,h:0.6,fontFace:F,fontSize:28,bold:true,color:C.FOREST,align:"center"});
  slide.addText(label,{x:x,y:y+0.82,w:w,h:0.3,fontFace:F,fontSize:12,bold:true,color:C.INK,align:"center"});
  if(sub)slide.addText(sub,{x:x,y:y+1.12,w:w,h:0.3,fontFace:F,fontSize:9.5,color:C.ASH,align:"center"});
}
// 플로우 박스
function flowBox(slide,x,y,w,h,title,sub,fill,tcol){
  slide.addShape(pres.ShapeType.roundRect,{x,y,w,h,rectRadius:0.08,fill:{color:fill||C.WHITE},line:{color:C.LINE,width:1.25}});
  slide.addText(title,{x:x,y:y+h/2-0.34,w:w,h:0.4,fontFace:F,fontSize:13.5,bold:true,color:tcol||C.INK,align:"center"});
  if(sub)slide.addText(sub,{x:x,y:y+h/2+0.02,w:w,h:0.3,fontFace:F,fontSize:10,color:C.ASH,align:"center"});
}
function arrow(slide,x,y,w){slide.addShape(pres.ShapeType.line,{x,y,w,h:0,line:{color:C.EMBER,width:2,endArrowType:"triangle"}});}

// =====================================================================
// 표지
// =====================================================================
let s=pres.addSlide(); s.background={color:C.PAPER};
arrivalMesh(s,7.35,1.25,5.25,3.35,6,4);
s.addText("제24회 임베디드SW경진대회 · 자유공모 부문",{x:0.9,y:1.7,w:9,h:0.35,fontFace:F,fontSize:13,bold:true,color:C.EMBER,charSpacing:1});
s.addText("불사",{x:0.85,y:2.15,w:6.4,h:1.6,fontFace:F,fontSize:88,bold:true,color:C.INK});
s.addShape(pres.ShapeType.line,{x:0.95,y:3.95,w:2.1,h:0,line:{color:C.EMBER,width:3}});
s.addText([{text:"화중생련  ",options:{color:C.FOREST}},{text:"火中生蓮",options:{color:C.ASH}}],{x:0.9,y:4.15,w:9,h:0.5,fontFace:F,fontSize:20,bold:true});
s.addText("고장(노드 파괴)을 데이터로 바꾸는 자가치유 산불 감시 메시",{x:0.9,y:4.9,w:10.5,h:0.5,fontFace:F,fontSize:16,color:"50544B"});
s.addShape(pres.ShapeType.line,{x:0.9,y:6.35,w:11.5,h:0,line:{color:C.LINE,width:1}});
s.addText([{text:"이동욱",options:{bold:true,color:C.INK}},{text:"  전자공학전공 · 숭실대학교",options:{color:C.ASH}}],{x:0.9,y:6.5,w:8,h:0.4,fontFace:F,fontSize:13});
s.addText("GitHub · 시연영상 링크는 제출본에 삽입",{x:7.4,y:6.5,w:5,h:0.4,fontFace:F,fontSize:11,color:C.ASH,align:"right"});

// =====================================================================
// 1. 개발 개요 (3P)
// =====================================================================
// P1 배경·동기
s=pres.addSlide(); header(s,"개발 개요 ① 개발 배경·동기  |  독창성","재난에선 노드 파괴가 '필연'이다");
s.addText([{text:"산불·지진·붕괴 현장에서 센서 노드는 ",options:{}},{text:"반드시 죽는다",options:{bold:true,color:C.EMBER}},{text:". 기존 시스템은 이 죽음을 단순 '손실'로 처리한다. 우리는 ",options:{}},{text:"죽음의 시공간 패턴 자체를 데이터로 승격",options:{bold:true,color:C.FOREST}},{text:"해, 사라진 노드들이 오히려 불의 방향·속도를 그리게 한다.",options:{}}],{x:0.6,y:1.65,w:12.1,h:0.95,fontFace:F,fontSize:15,color:C.INK,lineSpacingMultiple:1.25});
infoCard(s,0.6,2.95,3.85,2.55,"문제 정의","위성·드론은 연기·수목 아래 지표 화선을 못 본다. 진화 지휘·대원 안전이 직결된 실시간 공백이 남는다.",C.ASH);
infoCard(s,4.73,2.95,3.85,2.55,"기존의 공백","stock 메시는 죽은 노드를 우회만 할 뿐, 그 죽음에 담긴 정보를 버린다.",C.ASH);
infoCard(s,8.86,2.95,3.85,2.55,"우리 목표","고장 패턴을 데이터로 + 자가치유로, 그 공백을 지상에서 실시간으로 채운다.",C.FOREST,C.TINT);
s.addText("→ 응용(산불)이 아니라 아키텍처(고장→데이터 + 자가치유)에 독창성이 있다.",{x:0.6,y:5.75,w:12.1,h:0.4,fontFace:F,fontSize:13,italic:true,bold:true,color:C.FOREST});
footer(s);

// P2 문제 정의
s=pres.addSlide(); header(s,"개발 개요 ② 문제 정의  |  활용성","상공이 못 보는 '지표 화선'의 실시간 공백");
infoCard(s,0.6,1.65,5.95,2.3,"무엇이 안 보이나","연기와 수목 캐노피 아래에서 실제로 번지는 지표 화선(fire front)의 위치·방향·속도. 위성은 광역 개요만, 드론은 상공·간헐적이라 초 단위 국지 변화를 놓친다.",C.INK);
infoCard(s,6.73,1.65,5.99,2.3,"왜 치명적인가","진화 지휘부의 자원 배치와 최전선 대원의 대피 타이밍이 바로 이 정보에 달려 있다. 공백이 곧 인명·재산 피해로 이어진다.",C.EMBER,C.AMB);
s.addText("현장 동기 (2025 의성 산불)",{x:0.6,y:4.25,w:12,h:0.35,fontFace:F,fontSize:13,bold:true,color:C.INK});
s.addShape(pres.ShapeType.line,{x:0.6,y:4.62,w:0.55,h:0,line:{color:C.EMBER,width:2}});
s.addText("대형 산불 대응 현장에서, 지상의 실시간 화선 정보가 없어 판단이 지연되는 국면을 보며 '지상에서 화선을 실측하는 저가 레이어'의 필요를 절감했다. (동기·삽화로만 사용 — 반사실 주장 아님)",{x:0.6,y:4.75,w:12.1,h:0.9,fontFace:F,fontSize:12.5,color:"44483F",lineSpacingMultiple:1.25});
footer(s,"동기는 삽화로만 · 근거는 일반 산불대응 공백");

// P3 목표·핵심 아이디어
s=pres.addSlide(); header(s,"개발 개요 ③ 개발 목표·핵심 아이디어  |  독창성 30","고장을 '손실'이 아니라 '데이터'로");
flowBox(s,0.7,1.9,3.4,1.15,"① 노드 파괴","불에 타 죽는 순간",C.AMB,C.EMBER); arrow(s,4.2,2.47,0.75);
flowBox(s,5.05,1.9,3.4,1.15,"② 죽은 시각·좌표","= 불이 도착한 시각",C.WHITE); arrow(s,8.55,2.47,0.75);
flowBox(s,9.4,1.9,3.3,1.15,"③ 방향·속도·ETA","+ 신뢰도 등급",C.TINT,C.FOREST);
infoCard(s,0.7,3.4,5.95,2.3,"목표 1 — 고장의 데이터화","교차검증된 '죽음'을 확정 이진 신호로 모아, 흩어진 (좌표·죽은시각)에서 화선의 위치·방향·속도를 추정한다.",C.INK);
infoCard(s,6.78,3.4,5.94,2.3,"목표 2 — 자가치유","노드가 죽어 경로가 끊겨도 남은 노드들이 자동으로 우회로를 다시 짜, 관측 자체가 계속되게 한다.",C.INK);
s.addText("→ 두 목표가 합쳐져: 노드는 죽지만(불에 타도) 시스템의 관측은 '죽지 않는다'. = 불사(不死)의 이중 의미.",{x:0.7,y:5.9,w:12,h:0.35,fontFace:F,fontSize:12.5,italic:true,bold:true,color:C.FOREST});
footer(s);

// =====================================================================
// 2. 개발 환경 (2P)
// =====================================================================
// P4 시스템 구성
s=pres.addSlide(); header(s,"개발 환경 ① 시스템 구성  |  기술성(임베디드SW 적용)","하드웨어 · 소프트웨어 구성");
infoCard(s,0.6,1.65,6.0,4.0,"하드웨어","· 센서 노드: ESP32 × 16 (WiFi 메시)\n· 온도 감지: DS18B20 디지털 온도센서 (9비트 고속 모드)\n· 상태 표시: WS2812 LED (생사·경보 시각화)\n· 게이트웨이: 라즈베리파이 (메시↔대시보드)\n· 전원: 배터리 / 승압 모듈\n\n16노드 실물 재료비 ≈ 45만 원 (저가 소모형 설계).\n※ 열풍기·변압기 등은 검증용 계측 장비로 노드 원가와 별개.",C.INK);
infoCard(s,6.73,1.65,5.99,4.0,"소프트웨어","· 노드 펌웨어: C/C++ (Arduino-ESP32 + painlessMesh)\n   — 메시 자동 구성·우회 + 메시 시각 동기 제공\n· 게이트웨이: Python — 시뮬 추정기 코드 그대로 재사용\n· 관제: 자체완결 웹 대시보드 (HTML, 서버 불필요)\n· 개발·검증: 네트워크 시뮬레이터(Python), Wokwi(컴파일 확인)\n· 판정 일원화: 화재/비화재 판별을 단일 함수로 — 시뮬과 실물이\n   같은 코드를 호출한다(시뮬 결과가 실물의 근거가 되도록).",C.FOREST,C.TINT);
footer(s);

// P5 아키텍처
s=pres.addSlide(); header(s,"개발 환경 ② 기능 설계도  |  기술성","데이터 흐름 아키텍처");
const ay=2.5, bh=1.3, bw=2.55;
flowBox(s,0.55,ay,bw,bh,"센서 노드","ESP32 + 온도",C.AMB,C.EMBER); arrow(s,3.15,ay+bh/2,0.5);
flowBox(s,3.7,ay,bw,bh,"메시 네트워크","painlessMesh",C.WHITE); arrow(s,6.3,ay+bh/2,0.5);
flowBox(s,6.85,ay,bw,bh,"게이트웨이","RPi · 추정기(Python)",C.WHITE); arrow(s,9.45,ay+bh/2,0.5);
flowBox(s,10.0,ay,bw,bh,"웹 대시보드","화선·경보 관제",C.TINT,C.FOREST);
s.addText("노드가 임종신호·하트비트를 메시로 흘리면, 게이트웨이가 죽은 노드의 시공간 패턴에서 화선을 추정하고, 대시보드가 생사·자가치유 경로·참/추정 화선·대피경보를 실시간 재생한다.",{x:0.6,y:4.35,w:12.1,h:0.8,fontFace:F,fontSize:13,color:"44483F",lineSpacingMultiple:1.3,align:"center"});
infoCard(s,1.5,5.35,10.3,1.15,"핵심 이식성 증명 · 판정 일원화","게이트웨이가 시뮬레이터의 추정기 코드를 그대로 재사용 → 모의 데이터에서 시뮬 직접값과 완전 일치. 나아가 화재/비화재 판별도 단일 함수로 통합해 시뮬·실물이 같은 판정을 쓴다 — 두 경로가 다른 판정을 쓰면 시뮬 결과가 실물의 근거가 되지 못하기 때문.",C.FOREST,C.TINT);
footer(s);

// =====================================================================
// 3. 개발 프로그램 설명 (핵심)
// =====================================================================
// P6 4대 모듈
s=pres.addSlide(); header(s,"개발 프로그램 설명 ① 4대 모듈  |  기술성·완성도 30","시스템을 이루는 네 개의 핵심 모듈");
const mods=[["①","임종신호 (Last-Gasp)","노드가 임계온도를 넘겨 죽기 직전 쏘는 마지막 패킷 — 죽음의 시각을 확정.",C.INK,C.WHITE],
["②","자가치유 라우팅","노드가 죽어 길이 끊기면 sink 기준 역방향 BFS로 우회로를 자동 재계산.",C.INK,C.WHITE],
["③","오탐 방어 (교차검증) ★","통신두절 vs 진짜 파괴를 다중이웃 + 온도로 구분 — stock 메시가 못 하는 계층.",C.EMBER,C.AMB],
["④","도착시각장(場) 추정 ★","죽은 (좌표·시각)에서 최소제곱으로 방향·속도·ETA와 신뢰도를 역산.",C.FOREST,C.TINT]];
mods.forEach((m,i)=>{const x=0.6+(i%2)*6.13,y=1.7+Math.floor(i/2)*2.0;
  card(s,x,y,5.98,1.8,m[4]);
  s.addText(m[0],{x:x+0.25,y:y+0.2,w:0.8,h:0.7,fontFace:F,fontSize:30,bold:true,color:C.EMBER});
  s.addText(m[1],{x:x+1.05,y:y+0.28,w:4.75,h:0.4,fontFace:F,fontSize:15,bold:true,color:m[3]});
  s.addText(m[2],{x:x+1.05,y:y+0.72,w:4.75,h:0.9,fontFace:F,fontSize:11.5,color:"44483F",lineSpacingMultiple:1.15});});
footer(s);

// P7 도착시각장 추정 알고리즘 — 2단 구조 (v2 전면 개정)
s=pres.addSlide(); header(s,"개발 프로그램 설명 ② ★ 핵심 알고리즘  |  기술성·완성도","죽은 노드의 (좌표·시각) → 불의 방향·속도·ETA");
s.addText([{text:"각 노드가 타 죽은 시각 = 불이 그 지점에 도착한 시각. 흩어진 (x, y, 죽은시각)에 면을 맞추면 그 기울기가 곧 화선이다. 실제 구현은 ",options:{color:C.INK}},{text:"2단 구조",options:{bold:true,color:C.EMBER}},{text:" — 노드마다 국소 적합을 돌리고, 그 결과들을 신뢰도로 가중해 합친다.",options:{color:C.INK}}],{x:0.6,y:1.58,w:12.13,h:0.62,fontFace:F,fontSize:13.5,lineSpacingMultiple:1.2});
const AX=[0.6,4.79,8.98], AW=3.75, AY=2.32, AH=2.55;
infoCard(s,AX[0],AY,AW,AH,"1단 · 국소 평면 적합","노드 j마다 독립적으로:\n\n· 무선 이웃 ∩ 시간창 안의 사망들을 모아\n· 최소제곱으로 평면을 맞추고\n· 기울기 ∇T_j 를 얻는다\n\n→ 노드 수만큼 N개의 추정치",C.INK);
infoCard(s,AX[1],AY,AW,AH,"2단 · 집계","N개를 하나로 합친다:\n\n· 방향 — 신뢰도 가중 벡터합\n   가중치 w = |∇T|²\n· 속도 — 중앙값(강건 통계)\n· 진단 — 유효표본수 n_eff\n→ 두 출력이 다른 집계를 쓴다",C.EMBER,C.AMB);
infoCard(s,AX[2],AY,AW,AH,"출력","· 진행 방향  n̂\n· 진행 속도  s\n· 지점별 도착예상시각 ETA\n· 신뢰도 등급\n\n정보가 부족하면 값을 내지 않고\nINSUFFICIENT를 반환한다.",C.FOREST,C.TINT);
arrow(s,4.42,AY+AH/2,0.32); arrow(s,8.61,AY+AH/2,0.32);
card(s,0.6,5.12,12.13,1.42,C.WHITE);
s.addText([{text:"∇T = n̂ / s     →     방향 n̂ = ∇T/|∇T| ,   속도 s = 1/|∇T|",options:{bold:true,color:C.INK,fontSize:15}}],{x:0.85,y:5.28,w:6.4,h:0.4,fontFace:F});
s.addText([{text:"모든 노드에 똑같이 걸리는 센서 지연은 평면의 절편에만 흡수되어 기울기에서 상쇄된다 — ",options:{color:"44483F"}},{text:"방향·속도가 센서 지연에 원리적으로 면역인 이유(수식 증명).",options:{bold:true,color:C.FOREST}}],{x:0.85,y:5.76,w:11.6,h:0.6,fontFace:F,fontSize:12,lineSpacingMultiple:1.2});
s.addText("가벼운 최소제곱 — 저사양 게이트웨이에서 즉시 계산 (딥러닝 아님)",{x:7.4,y:5.3,w:5.1,h:0.35,fontFace:F,fontSize:11,color:C.ASH,align:"right"});
footer(s,"명세↔코드 1:1 대조 완료");

// P8 오탐 방어 (헤드라인)
s=pres.addSlide(); header(s,"개발 프로그램 설명 ③ ★ 오탐 방어 (헤드라인)  |  독창성·기술성","'통신두절'인가, '진짜 파괴'인가");
s.addText("노드가 조용해졌다고 다 죽은 게 아니다. 잠깐 끊긴 것(통신두절)이나 불이 아닌 죽음(배터리·고장)을 화재로 오판하면 가짜 화선이 그려진다. 세 층으로 막는다.",{x:0.6,y:1.56,w:12.13,h:0.62,fontFace:F,fontSize:13.5,color:C.INK,lineSpacingMultiple:1.2});
const BX=[0.6,4.79,8.98], BW=3.75, BY=2.28, BH=2.45;
infoCard(s,BX[0],BY,BW,BH,"1층 · 다중 이웃 교차검증","한 노드가 침묵해도 즉시 죽음으로 보지 않는다. K개 이웃(K_confirm=3)이 독립적으로 '연결 끊김'을 확인해야 사망 후보로 승격 — 일시적 링크 노이즈를 걸러낸다.",C.INK);
infoCard(s,BX[1],BY,BW,BH,"2층 · 온도 교차검증","사망 후보가 직전에 고온을 겪었는가? 화선에 의한 죽음이면 온도 상승이 선행한다. 온도 정황이 뒷받침될 때만 '화선 사망'으로 확정.",C.INK);
infoCard(s,BX[2],BY,BW,BH,"3층 · 임종신호 (비대칭)","임종신호는 있으면 화재 증거, 없어도 기각 근거가 아니다 — 전소로 신호조차 못 보낸 노드가 바로 진짜 화재이므로. 이 비대칭성은 테스트 2개로 고정.",C.EMBER,C.AMB);
card(s,0.6,4.98,12.13,1.55,C.TINT);
s.addText("설계 원칙 — 판별은 정보가 가장 많은 곳에서",{x:0.85,y:5.12,w:11.6,h:0.35,fontFace:F,fontSize:13.5,bold:true,color:C.FOREST});
s.addText([{text:"말단 노드의 게이트는 ",options:{color:"44483F"}},{text:"의도적으로 느슨하게",options:{bold:true,color:C.INK}},{text:" 두고, 최종 판별은 이웃 정보가 모두 모이는 게이트웨이에서 한다. 말단에서 조이면 게이트웨이가 볼 표본 자체가 굶기 때문. ",options:{color:"44483F"}},{text:"결과: 측정 전 구간(통신두절 0.30까지) 오탐률 0%, 비화재 COOL 누수 86.4% → 0%.",options:{bold:true,color:C.FOREST}}],{x:0.85,y:5.5,w:11.6,h:0.9,fontFace:F,fontSize:12,lineSpacingMultiple:1.25});
footer(s,"stock 메시가 갖지 못한 계층");

// P9 자가치유 + 임종신호
s=pres.addSlide(); header(s,"개발 프로그램 설명 ④ 자가치유 라우팅 · 임종신호  |  기술성","길이 끊겨도 관측은 죽지 않는다");
infoCard(s,0.6,1.65,5.95,3.05,"자가치유 라우팅","· sink(id 0) 기준 역방향 BFS로 각 노드의 상행 경로를 구성.\n· 노드가 DEAD로 확정되면 영향 구역만 경로를 즉시 재계산.\n· 연결성이 유지되는 한, 죽은 노드를 우회해 데이터가 계속 sink에 도달.\n\n※ 재라우팅 실지연은 실물에서 첫 실측(Phase C). 시뮬의 100ms는 틱값(성능 아님).",C.INK);
infoCard(s,6.73,1.65,5.99,3.05,"임종신호 (Last-Gasp)","· 노드가 임계온도를 넘어 죽기 직전, 마지막 패킷을 방출.\n· '언제 죽었는가'를 확정 → 도착시각 추정의 입력 시각을 정밀화.\n· 하트비트(주기 신호) 누락과 결합해 침묵을 판정.\n\n죽음의 '시각'이 정확할수록 화선 방향·속도 추정이 정밀해진다.",C.FOREST,C.TINT);
s.addText("자가치유(관측 지속) + 임종신호(죽음의 시각 확정)가 만나, '죽는 노드'가 '살아있는 정보'가 된다.",{x:0.6,y:5.0,w:12.1,h:0.5,fontFace:F,fontSize:13,italic:true,bold:true,color:C.FOREST,align:"center"});
footer(s);

// P10 파일 구성·검증 규율
s=pres.addSlide(); header(s,"개발 프로그램 설명 ⑤ 구성 · 개발 규율  |  기술성·완성도","코드 구성과 'measure-first' 규율");
infoCard(s,0.6,1.65,6.0,3.5,"저장소 구성","· sim/  — 시뮬레이터 · 추정기(estimator) · 집계(aggregate)\n· firmware/  — ESP32 노드 펌웨어(C/C++)\n· gateway/  — 라즈베리파이 추정기(Python, sim 재사용)\n· dashboard/  — 자체완결 웹 관제\n· docs/  — 연구노트(PROGRESS · DECISIONS · 알고리즘 명세)\n\n결정 로그(D-001~)를 남겨 '왜 그렇게 정했는가'를 전부 추적 가능하게.",C.INK);
infoCard(s,6.73,1.65,5.99,3.5,"추정기 동결 + 버전 분기","· 핵심 추정기 파일을 동결(frozen) — 모든 개선은 버전 분기로만.\n· 그래서 어떤 실험도 과거 결과를 훼손할 수 없다.\n   회귀가 매번 비트 단위 동일함을 확인(최대차 0.000e+00).\n· 자동 테스트 54건 상시 통과.\n· 결과가 나빠도 파라미터를 유리하게 고치지 않는다(기록만).\n   → 데모에만 맞춘 overfitting 함정 회피.",C.FOREST,C.TINT);
s.addText("→ 완성도는 '보기 좋은 숫자'가 아니라 '재현 가능하고 정직하게 측정된 숫자'에서 나온다.",{x:0.6,y:5.45,w:12.1,h:0.4,fontFace:F,fontSize:13,italic:true,bold:true,color:C.FOREST});
footer(s);

// =====================================================================
// 4. 개발 중 장애요인·해결
// =====================================================================
// P11 시뮬 선개발 + 정직화
s=pres.addSlide(); header(s,"장애요인·해결 ①  |  기술성(문제해결·공학 성숙도)","하드웨어 없이 먼저 검증하고, 정직하게 교정");
infoCard(s,0.6,1.65,5.95,2.35,"장애 · 하드웨어 리스크","부품 도착 전 알고리즘을 못 짜면 개발이 지연되고, 실물에서 처음 검증하면 리스크가 크다.",C.EMBER,C.AMB);
infoCard(s,6.73,1.65,5.99,2.35,"해결 · 시뮬 선(先)개발","네트워크 시뮬레이터로 4대 기능을 먼저 구현·검증. 정상 조건에서 방향 2.12°·속도 0.10%·전달률 92.3%·오탐 0% 확보.",C.FOREST,C.TINT);
infoCard(s,0.6,4.2,5.95,2.35,"장애 · 가짜로 좋은 수치","초기엔 바람이 고정 파형이라 시드를 바꿔도 오차가 안 변해 에러바가 가짜로 0에 가까웠다. 좋아 보이는 숫자가 사실은 측정이 아니었다.",C.EMBER,C.AMB);
infoCard(s,6.73,4.2,5.99,2.35,"해결 · 사전등록 제도","바람을 시드마다 다른 실현으로 바꿔 진짜 통계로. 나아가 물리 예측을 미리 등록하고 맞든 틀리든 전부 기록하는 규칙을 세웠다 — 기각된 예측 5건이 문서에 그대로 남아 있다(단조성·취약성·곡률·채점·ETA 게이트).",C.FOREST,C.TINT);
footer(s,"정직성 서사 = 과대포장 배제");

// P12 ★★ 82°의 3중 오진 (v2 신설 — 이 장의 중심)
s=pres.addSlide(); header(s,"장애요인·해결 ② ★ 하나의 증상, 세 번의 오진  |  문제해결 능력","방향오차 82° — 진짜 원인을 찾기까지");
s.addText([{text:"타원 화선의 측면 조건에서 방향오차가 ",options:{color:C.INK}},{text:"82~86°",options:{bold:true,color:C.EMBER}},{text:". 90°가 무작위 추측의 한계이므로 사실상 아무 정보도 못 주는 상태였다. 세 번의 진단이 전부 측정으로 기각된 뒤에야 원인에 닿았다.",options:{color:C.INK}}],{x:0.6,y:1.56,w:12.13,h:0.6,fontFace:F,fontSize:13.5,lineSpacingMultiple:1.2});
const dh2=t=>({text:t,options:{fontFace:F,fontSize:11,bold:true,color:C.WHITE,fill:{color:C.FOREST},valign:"middle",align:"left",margin:[3,6,3,6]}});
const dc2=(t,o={})=>({text:t,options:{fontFace:F,fontSize:10.5,color:"3A3E37",valign:"middle",align:"left",margin:[3,6,3,6],...o}});
s.addTable([
  [dh2(""),dh2("가설"),dh2("검정 방법"),dh2("결과")],
  [dc2("①",{bold:true,color:C.ASH,align:"center"}),dc2("곡률 탓 — 전선이 굽어 평면 근사가 깨짐"),dc2("적합 창을 넓혀 곡률 영향을 분리"),dc2("기각 — 창을 넓히자 81.8° → 5.6°",{color:C.EMBER})],
  [dc2("②",{bold:true,color:C.ASH,align:"center"}),dc2("채점 방식 탓 — 국소 법선 vs 전역 축 혼동"),dc2("채점 코드를 직접 확인"),dc2("기각 — 이미 국소 법선 기준이었다",{color:C.EMBER})],
  [dc2("③",{bold:true,color:C.ASH,align:"center"}),dc2("표본 부족 탓 — 창 안에 이웃이 모자람"),dc2("표본 수·조건수 진단"),dc2("부분 기각 — 13개인데도 실패",{color:C.EMBER})],
  [dc2("④",{bold:true,color:C.INK,align:"center",fill:{color:C.TINT}}),dc2("집계 가중치가 원인",{bold:true,color:C.INK,fill:{color:C.TINT}}),dc2("노드별 개별 오차와 가중치 분포를 분해",{fill:{color:C.TINT}}),dc2("★ 확정",{bold:true,color:C.FOREST,fill:{color:C.TINT}})],
],{x:0.6,y:2.24,w:12.13,colW:[0.55,3.85,3.6,4.13],rowH:[0.34,0.44,0.44,0.44,0.5],border:{type:"solid",color:C.LINE,pt:1},valign:"middle"});
statBox(s,0.6,4.72,3.85,"+0.986","corr(속도, 방향오차)","속도가 큰 노드가 곧 틀린 노드");
statBox(s,4.74,4.72,3.85,"86.4%","한 노드의 가중치 비중","그 노드의 개별 오차 85.21°");
statBox(s,8.88,4.72,3.85,"1.35°","개별 오차의 중앙값","나머지 노드들은 맞히고 있었다");
s.addText([{text:"정답은 표본 안에 있었다 — 집계가 그것을 버리고 최악의 노드 하나를 골랐다.  ",options:{bold:true,color:C.EMBER}},{text:"가중치가 w = 1/|∇T| (불확실할수록 크게)로, 부호가 반대였다. 오차 전파식에서 다시 유도해 w = |∇T|² 로 교정.",options:{color:C.INK}}],{x:0.6,y:6.36,w:12.13,h:0.5,fontFace:F,fontSize:12,lineSpacingMultiple:1.15});
footer(s,"우연한 통제군: 같은 입력에서 강건 집계(속도)는 살고 비강건 집계(방향)만 죽었다");

// P13 ★★ 모르면 모른다고 말하는 시스템 (v2 신설)
s=pres.addSlide(); header(s,"장애요인·해결 ③ ★ 모르면 '모른다'고 말하는 시스템  |  공학 성숙도","가중치를 고쳐도, 정보가 원래 없는 조건은 남는다");
s.addText([{text:"희소한 측면 조건에서는 창 안에 쓸 만한 관측 자체가 없다. 어떤 알고리즘도 못 푼다. ",options:{color:C.INK}},{text:"그때 시스템은 무엇을 해야 하는가?",options:{bold:true,color:C.EMBER}}],{x:0.6,y:1.56,w:12.13,h:0.5,fontFace:F,fontSize:13.5,lineSpacingMultiple:1.2});
s.addTable([
  [dh2("집계 방식"),dh2("출력"),dh2("판정")],
  [dc2("기존(가중 결함)"),dc2("85.05°"),dc2("자신 있게 틀림",{color:C.EMBER})],
  [dc2("균일 가중"),dc2("84.90°"),dc2("자신 있게 틀림",{color:C.EMBER})],
  [dc2("중앙값"),dc2("84.90°"),dc2("자신 있게 틀림",{color:C.EMBER})],
  [dc2("역분산 (채택)",{bold:true,color:C.INK,fill:{color:C.TINT}}),dc2("값 없음 — INSUFFICIENT",{bold:true,color:C.FOREST,fill:{color:C.TINT}}),dc2("★ 판정을 보류한다",{bold:true,color:C.FOREST,fill:{color:C.TINT}})],
],{x:0.6,y:2.16,w:12.13,colW:[3.4,4.4,4.33],rowH:[0.34,0.42,0.42,0.42,0.5],border:{type:"solid",color:C.LINE,pt:1},valign:"middle"});
infoCard(s,0.6,4.42,5.95,2.05,"설계 결정 — 폴백을 넣지 않는다","산불 대응에서 '모른다'와 '정반대를 확신한다'의 비용은 대칭이 아니다. 방향을 모르면 판단을 보류하지만, 90° 틀린 방향을 믿으면 대원을 화선 쪽으로 보낸다.\n\n실제 로그에는 \"냈다면 틀렸을 것: True\"가 함께 남는다.",C.EMBER,C.AMB);
infoCard(s,6.73,4.42,5.99,2.05,"진단량 · 유효표본수 n_eff","표본이 13개여도 하나가 가중치를 독식하면 n_eff는 1.33까지 떨어진다.\n\n· 정상 12.7~13.0  · 가중치 독식 1.33~1.74  · 진짜 표본 굶주림 1.04\n\n원표본 수와 짝지어 표기해야 두 실패가 구분된다.",C.FOREST,C.TINT);
s.addText([{text:"★ 같은 원칙을 우리 계측 도구가 어겼다 — ",options:{bold:true,color:C.EMBER}},{text:"센서를 못 찾은 로거가 오류 한 줄 뒤 영구히 침묵해, 배선을 고쳐도 정상과 구별되지 않았다. 침묵 대신 상태를 계속 출력하도록 고쳤다.",options:{color:C.INK}}],{x:0.6,y:6.58,w:12.13,h:0.4,fontFace:F,fontSize:12});
footer(s,"'자기 한계를 아는 것'은 문서가 아니라 기능이다");

// P14 하드웨어 괴리 선점 (v2 개정 — 시계동기 + τ실측 + 파이프라인 공백)
s=pres.addSlide(); header(s,"장애요인·해결 ④ ★ 하드웨어 괴리 선점  |  공학 성숙도·차별화","시뮬에선 보이지 않는 실물 전용 위험 셋");
const CX=[0.6,4.79,8.98], CW=3.75, CY=1.60, CH=4.02;
infoCard(s,CX[0],CY,CW,CH,"① 시계 동기","서로 다른 노드의 사망 시각을 빼서 기울기를 만드는 알고리즘이므로 시간축이 같아야 한다.\n\n초기 펌웨어는 보드 부팅 기준 시계를 썼다 — 보드마다 원점이 달라 뺄셈 자체가 무의미해지는 원리적 파탄.\n\n→ 메시 동기 시각으로 교체. 사망 시각도 '루트의 확정 시각'에서 '당사자 노드가 각인한 시각'으로 (확정 시각엔 감지·투표 지연이 섞여 있었다).",C.INK);
infoCard(s,CX[1],CY,CW,CH,"② 센서 열관성 τ","센서는 공기 온도를 즉시 따라가지 못한다. 이 지연이 곧 사망 시각의 오차가 된다.\n\n시뮬 시험 범위   0 ~ 10초\n실측 범위        11 ~ 92초\n\n→ 검증했다고 믿은 범위 밖에 실제가 있었다.\n\n★ τ는 온도가 아니라 유속의 함수 — 같은 센서·같은 시행 안에서 제트 21.5초 / 실내 92초로 4.1배 차이. 바뀐 것은 공기가 움직이느냐뿐이었다.\n\n★ 노드별 편차 σ_τ는 '미측정'으로 확정. 한때 5.7%로 보고했으나 센서 번호가 측정 순서와 교란(corr −0.903)된 것을 발견하고 우리 손으로 철회했다.",C.EMBER,C.AMB);
infoCard(s,CX[2],CY,CW,CH,"③ 실물 파이프라인 공백","시뮬에는 화재/비화재 판별이 있는데 실물 경로에는 없었다 — 게이트웨이가 판별기를 아예 호출하지 않고 있었다.\n\n→ 판정 로직을 한 함수로 통합해 시뮬과 실물이 같은 코드를 호출하도록 교정.\n\n이걸 놓쳤으면 시뮬에서 검증한 방어가 실물에서 통째로 빠진 채 데모를 했을 것이다.",C.FOREST,C.TINT);
s.addText([{text:"세 위험 모두 ",options:{color:C.INK}},{text:"실물에서 터지기 전에",options:{bold:true,color:C.EMBER}},{text:" 발견했다. ①은 코드 검토로, ②는 실측으로, ③은 실물 이식 준비 중에 — 각각 다른 방법이 필요했다는 것이 이 문제들의 성격을 보여준다.",options:{color:C.INK}}],{x:0.6,y:5.85,w:12.13,h:0.5,fontFace:F,fontSize:12.5,lineSpacingMultiple:1.2});
footer(s,"세 위험 모두 실물에서 터지기 전에 발견 — 각각 다른 방법이 필요했다");

// =====================================================================
// 5. 결과물 차별성·우수성
// =====================================================================
// P14 차별성 표
s=pres.addSlide(); header(s,"결과물 차별성·우수성 ① 차별성  |  독창성 30","고장을 '손실'이 아니라 '데이터'로");
const hdr=t=>({text:t,options:{fontFace:F,fontSize:12,bold:true,color:C.WHITE,fill:{color:C.FOREST},valign:"middle",align:"left",margin:[4,6,4,6]}});
const cel=(t,o={})=>({text:t,options:{fontFace:F,fontSize:10.5,color:"3A3E37",valign:"middle",align:"left",margin:[4,6,4,6],...o}});
const ours=t=>cel(t,{color:C.INK,bold:true,fill:{color:C.TINT}});
s.addTable([
  [hdr("비교 대상"),hdr("그들의 방식"),hdr("한계"),hdr("우리 (불사)")],
  [cel("온도 스트리밍",{bold:true,color:C.INK}),cel("살아있는 노드가 온도 상시 전송"),cel("초저가 대량 노드엔 상시 전송 부담(전력·대역폭)"),ours("교차검증된 '죽음'을 확정 이진 신호로 → 화선 위치·방향·속도")],
  [cel("Dryad Silvanet",{bold:true,color:C.INK}),cel("불 오기 전 조기 감지(내열, +85℃ 한계)"),cel("불 속에선 못 버팀 — 감지 특화, 전선 추적 아님"),ours("타 죽으며 화선을 그림 — 감지(그들)와 추적(우리)은 상보")],
  [cel("stock ESP-MESH",{bold:true,color:C.INK}),cel("노드 죽으면 경로 우회(연결성만)"),cel("죽음을 손실로만 처리, 정보로 안 씀"),ours("죽음을 1급 이벤트로 승격 + 도착시각 추정 + 오탐 방어")],
  [cel("드론·위성",{bold:true,color:C.INK}),cel("상공·우주 광역 개요"),cel("연기·수목 아래 지표 화선·초 단위 변화 못 봄"),ours("지표 실측 레이어 + 지상 통신 백본 — 대체 아니라 상보")],
],{x:0.6,y:1.6,w:12.13,colW:[1.9,2.75,3.2,4.28],rowH:[0.4,0.8,0.8,0.8,0.8],border:{type:"solid",color:C.LINE,pt:1},valign:"middle"});
s.addText([{text:"★ 헤드라인 차별점  ",options:{bold:true,color:C.EMBER}},{text:"오탐 방어(통신두절 vs 진짜 파괴 구분) = stock 메시가 못 하는 우리만의 계층.",options:{color:C.INK}}],{x:0.6,y:6.4,w:12.13,h:0.4,fontFace:F,fontSize:13});
footer(s);

// P15 강건성·정량
s=pres.addSlide(); header(s,"결과물 차별성·우수성 ② 성능·강건성  |  기술성(정량)","정상 성능과 '작동 한계선'을 함께 밝힌다");
statBox(s,0.6,1.58,2.85,"< 1°","방향오차","직선·정면 조건 (0.03~0.88°)");
statBox(s,3.65,1.58,2.85,"92.3%","전달률","자가치유 포함");
statBox(s,6.70,1.58,2.85,"0%","오탐률","통신두절 오판");
statBox(s,9.75,1.58,2.85,"54","자동 테스트","전건 통과 · 회귀 최대차 0");
s.addText("작동 한계선 (operating envelope) — 어디까지 되고, 어디부터 안 되는가",{x:0.6,y:3.32,w:12,h:0.35,fontFace:F,fontSize:13,bold:true,color:C.INK});
const eh=t=>({text:t,options:{fontFace:F,fontSize:11,bold:true,color:C.WHITE,fill:{color:C.FOREST},valign:"middle",align:"left",margin:[3,6,3,6]}});
const ec=(t,o={})=>({text:t,options:{fontFace:F,fontSize:10.5,color:"3A3E37",valign:"middle",align:"left",margin:[3,6,3,6],...o}});
s.addTable([
  [eh("조건"),eh("결과"),eh("의미")],
  [ec("직선 화선",{bold:true}),ec("방향오차 0.03°"),ec("정상 운용 영역")],
  [ec("타원 화선 · 정면(head)",{bold:true}),ec("방향오차 0.88°"),ec("데모·실전의 주 조건")],
  [ec("강곡률 곡선 화선",{bold:true}),ec("방향오차 7.6~13.4°"),ec("국소 평면 근사의 한계 — 센서 지연과 무관한 별개 한계")],
  [ec("타원 측면 · 노드 희소",{bold:true,color:C.EMBER}),ec("★ 자기 차단 — 값을 내지 않음",{bold:true,color:C.FOREST}),ec("오답 대신 침묵. 정보 부족을 스스로 판정")],
  [ec("ETA",{bold:true}),ec("앵커거리와 상관 0.99~1.00"),ec("배치 밀도가 지배 — 알고리즘이 아니라 간격")],
  [ec("노드별 센서 지연 편차",{bold:true}),ec("미측정 (자체 철회)",{bold:true,color:C.EMBER}),ec("5.7%로 보고했다가 측정 순서와의 교란을 발견하고 철회 — 리허설 잔차로 대체")],
  [ec("데모 열원 조건",{bold:true}),ec("190.5 ℃ (실측)",{bold:true,color:C.FOREST}),ec("예측 190.0 ℃ 적중(0.3%). 설정 400·풍량 10·4 cm·체류 8초")],
],{x:0.6,y:3.66,w:12.13,colW:[3.3,3.7,5.13],rowH:[0.36,0.40,0.40,0.40,0.46,0.40,0.40],border:{type:"solid",color:C.LINE,pt:1},valign:"middle"});
s.addText([{text:"모든 노드에 똑같이 걸리는 센서 지연에는 원리적으로 면역",options:{bold:true,color:C.FOREST}},{text:" (기울기에서 상쇄 — 수식 증명).  실측에서도 같은 성질이 재현됐다 — 센서 위치가 흔들려 도달 온도가 16.5℃ 변하는 동안 τ는 −0.061 s/℃로만 반응했다.",options:{color:C.INK}}],{x:0.6,y:6.5,w:12.13,h:0.4,fontFace:F,fontSize:12.5});
footer(s,"한계선을 함께 밝히는 것이 곧 신뢰의 근거다");

// =====================================================================
// 6. 파급력·기대효과
// =====================================================================
// P16 수요자·활용
s=pres.addSlide(); header(s,"파급력·기대효과 ① 활용  |  활용성 20","누가 쓰고, 어떻게 배포하나");
infoCard(s,0.6,1.65,5.95,2.2,"수요자 1 · 진화 지휘부","지표 화선의 실시간 위치·방향·속도로 '어디에 자원을 먼저 투입할지' 판단. 자원 배치 정확도↑.",C.INK);
infoCard(s,6.73,1.65,5.99,2.2,"수요자 2 · 최전선 대원","'이 구역에 전선 N분 내 도달' 대피 타이밍 제공. 대원 안전과 직결(속도는 안전마진으로 보수적 경보).",C.EMBER,C.AMB);
infoCard(s,0.6,4.05,5.95,2.35,"배포 · 고위험 구역 사전 배치","상습 발화지, 도시·마을 인접 산림(WUI), 주요 시설·문화재·등산로에 핀포인트. 초저가라 촘촘히 깔아도 부담 적음(사전 배치는 상용 선례로 검증).\n\n🟡 배치 간격 설계식 — ETA 정확도는 노드 간격이 지배함이 측정으로 확인됨. 정량 지침은 검증 후 삽입.",C.INK);
infoCard(s,6.73,4.05,5.99,2.35,"기대효과","상공 관측이 놓치는 지표 화선을 지상에서 실시간화 → 자원 배치 정확도와 대원 안전을 동시에 끌어올린다.",C.FOREST,C.TINT);
footer(s);

// P17 비용·발전 가능성
s=pres.addSlide(); header(s,"파급력·기대효과 ② 시장성·발전  |  활용성 · 발전 가능성","저가 소모형의 경제 논리와 확장성");
infoCard(s,0.6,1.65,5.95,3.2,"비용 논리","· 노드 개당 수천 원 → 불 속에 들어가는 역할엔 내구성을 '살' 수 없으니 저가 소모형이 유일하게 합리적.\n· 16노드 실물 ≈ 45만 원.\n· 예방 투자 vs 산불 1회 피해(인명·산림·재산) = 후자가 압도적.\n· 불날 때마다 갈아끼우는 모델이 오히려 경제적.",C.INK);
infoCard(s,6.73,1.65,5.99,3.2,"발전 가능성","· 같은 '고장-패턴-데이터화 + 자가치유' 구조를 실내 화재·가스 누출·구조물 붕괴·홍수로 확장 가능.\n· 온도 상승 궤적·곡선-허용 시공간 정합·다중소스 추정(#2e)이 다음 연구 축.\n· 드론·위성과 대체가 아니라 상보 레이어로 통합.",C.FOREST,C.TINT);
s.addText("→ 독창성은 특정 응용이 아니라 '고장을 데이터로 승격하는 아키텍처'에 있어, 재난 전반으로 이식된다.",{x:0.6,y:5.1,w:12.1,h:0.4,fontFace:F,fontSize:13,italic:true,bold:true,color:C.FOREST});
footer(s);

// =====================================================================
// 7. 개발 일정·업무 분장 (2P)
// =====================================================================
// P18 일정 + 1인 분장
s=pres.addSlide(); header(s,"개발 일정·업무 분장  |  팀 구성·역량 10","1인 개발자로 전 영역을 단계적으로 수행");
const th=t=>({text:t,options:{fontFace:F,fontSize:11,bold:true,color:C.WHITE,fill:{color:C.FOREST},valign:"middle",align:"left",margin:[3,6,3,6]}});
const tc=(t,o={})=>({text:t,options:{fontFace:F,fontSize:10.5,color:"3A3E37",valign:"middle",align:"left",margin:[3,6,3,6],...o}});
s.addTable([
  [th("단계"),th("기간"),th("내용"),th("상태")],
  [tc("① 시뮬·알고리즘",{bold:true}),tc("7월"),tc("시뮬레이터 · 도착시각장 추정 · 스트레스 · 하드웨어 괴리 정량화"),tc("✅ 완료",{color:C.FOREST,bold:true})],
  [tc("② 알고리즘 정밀화",{bold:true}),tc("8월 상순"),tc("집계 결함 발견·교정 · 자기 차단(INSUFFICIENT) 도입 · 명세↔코드 대조"),tc("✅ 완료",{color:C.FOREST,bold:true})],
  [tc("③ 실측·실물 포팅",{bold:true}),tc("8월 중순"),tc("센서 열관성 τ 실측 · 16노드 플래시 · 메시/임종신호 실제 RF 검증"),tc("진행 중",{color:C.EMBER,bold:true})],
  [tc("④ 데모·측정",{bold:true}),tc("8월 하순"),tc("열원 트리거 데모 · 재라우팅/추정오차/전달률 실측 · 시연영상 촬영"),tc("🟡 예정",{color:C.ASH})],
  [tc("⑤ 문서·제출",{bold:true}),tc("~9/3"),tc("보고서 PPT 완성 · 영상 편집 · GitHub Public"),tc("진행 중",{color:C.ASH})],
],{x:0.6,y:1.6,w:12.13,colW:[2.5,1.7,5.93,2.0],rowH:[0.38,0.55,0.55,0.55,0.55,0.55],border:{type:"solid",color:C.LINE,pt:1},valign:"middle"});
infoCard(s,0.6,4.8,12.13,1.75,"1인 업무 분장 (영역별)","펌웨어(ESP32·painlessMesh) · 알고리즘/게이트웨이(Python 추정기) · 하드웨어(16노드 조립·데모·계측) · 문서/발표(보고서·영상)를 단독으로 단계적 수행. 시뮬 선개발로 리스크를 앞당겨 해소하고, 추정기 동결·사전등록 규율로 범위를 통제 — 1인 개발의 범위 관리·완결 역량을 보인다.",C.FOREST,C.TINT);
footer(s);

pres.writeFile({fileName:"불사_개발완료보고서_v2.pptx"}).then(fn=>console.log("SAVED",fn,"· pages:",PAGE));
