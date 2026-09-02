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
flowBox(s,9.4,1.9,3.3,1.15,"③ 방향·속도·ETA","불의 진행을 역산",C.TINT,C.FOREST);
infoCard(s,0.7,3.4,5.95,2.3,"목표 1 — 고장의 데이터화","교차검증된 '죽음'을 확정 이진 신호로 모아, 흩어진 (좌표·죽은시각)에서 화선의 위치·방향·속도를 추정한다.",C.INK);
infoCard(s,6.78,3.4,5.94,2.3,"목표 2 — 자가치유","노드가 죽어 경로가 끊겨도 남은 노드들이 자동으로 우회로를 다시 짜, 관측 자체가 계속되게 한다.",C.INK);
s.addText("→ 두 목표가 합쳐져: 노드는 죽지만(불에 타도) 시스템의 관측은 '죽지 않는다'. = 불사(不死)의 이중 의미.",{x:0.7,y:5.9,w:12,h:0.35,fontFace:F,fontSize:12.5,italic:true,bold:true,color:C.FOREST});
footer(s);

// =====================================================================
// 2. 개발 환경 (2P)
// =====================================================================
// P4 시스템 구성
s=pres.addSlide(); header(s,"개발 환경 ① 시스템 구성  |  기술성(임베디드SW 적용)","하드웨어 · 소프트웨어 구성");
infoCard(s,0.6,1.65,6.0,4.0,"하드웨어","· 센서 노드: ESP32 × 16 (WiFi 메시)\n· 온도 감지: DS18B20 디지털 온도센서\n· 상태 표시: WS2812 LED (생사·경보 시각화)\n· 게이트웨이: 라즈베리파이 (메시↔대시보드)\n· 전원: 배터리 / 승압 모듈\n\n16노드 실물 재료비 ≈ 45만 원 (저가 소모형 설계).",C.INK);
infoCard(s,6.73,1.65,5.99,4.0,"소프트웨어","· 노드 펌웨어: C/C++ (Arduino-ESP32 + painlessMesh)\n   — 메시 자동 구성·우회 + 메시 시각 동기 제공\n· 게이트웨이: Python — 시뮬 추정기 코드 그대로 재사용\n· 관제: 자체완결 웹 대시보드 (HTML, 서버 불필요)\n· 개발·검증: 네트워크 시뮬레이터(Python), Wokwi(컴파일 확인)",C.FOREST,C.TINT);
footer(s);

// P5 아키텍처
s=pres.addSlide(); header(s,"개발 환경 ② 기능 설계도  |  기술성","데이터 흐름 아키텍처");
const ay=2.5, bh=1.3, bw=2.55;
flowBox(s,0.55,ay,bw,bh,"센서 노드","ESP32 + 온도",C.AMB,C.EMBER); arrow(s,3.15,ay+bh/2,0.5);
flowBox(s,3.7,ay,bw,bh,"메시 네트워크","painlessMesh",C.WHITE); arrow(s,6.3,ay+bh/2,0.5);
flowBox(s,6.85,ay,bw,bh,"게이트웨이","RPi · 추정기(Python)",C.WHITE); arrow(s,9.45,ay+bh/2,0.5);
flowBox(s,10.0,ay,bw,bh,"웹 대시보드","화선·경보 관제",C.TINT,C.FOREST);
s.addText("노드가 임종신호·하트비트를 메시로 흘리면, 게이트웨이가 죽은 노드의 시공간 패턴에서 화선을 추정하고, 대시보드가 생사·자가치유 경로·참/추정 화선·대피경보를 실시간 재생한다.",{x:0.6,y:4.35,w:12.1,h:0.8,fontFace:F,fontSize:13,color:"44483F",lineSpacingMultiple:1.3,align:"center"});
infoCard(s,2.4,5.35,8.5,1.15,"핵심 이식성 증명","게이트웨이가 시뮬레이터의 추정기 코드를 그대로 재사용 → 모의 데이터에서 방향 2.115°·속도 0.096%가 시뮬 직접값과 완전 일치. 검증된 알고리즘을 실물 파이프라인에 그대로 옮길 수 있음을 증명.",C.FOREST,C.TINT);
footer(s);

// =====================================================================
// 3. 개발 프로그램 설명 (핵심)
// =====================================================================
// P6 4대 모듈
s=pres.addSlide(); header(s,"개발 프로그램 설명 ① 4대 모듈  |  기술성·완성도 30","시스템을 이루는 네 개의 핵심 모듈");
const mods=[["①","임종신호 (Last-Gasp)","노드가 임계온도를 넘겨 죽기 직전 쏘는 마지막 패킷 — 죽음의 시각을 확정.",C.INK,C.WHITE],
["②","자가치유 라우팅","노드가 죽어 길이 끊기면 sink 기준 역방향 BFS로 우회로를 자동 재계산.",C.INK,C.WHITE],
["③","오탐 방어 (교차검증) ★","통신두절 vs 진짜 파괴를 다중이웃 + 온도로 구분 — stock 메시가 못 하는 계층.",C.EMBER,C.AMB],
["④","도착시각 추정 ★","죽은 (좌표·시각)에서 최소제곱으로 불의 방향·속도·ETA를 역산.",C.FOREST,C.TINT]];
mods.forEach((m,i)=>{const x=0.6+(i%2)*6.13,y=1.7+Math.floor(i/2)*2.0;
  card(s,x,y,5.98,1.8,m[4]);
  s.addText(m[0],{x:x+0.25,y:y+0.2,w:0.8,h:0.7,fontFace:F,fontSize:30,bold:true,color:C.EMBER});
  s.addText(m[1],{x:x+1.05,y:y+0.28,w:4.75,h:0.4,fontFace:F,fontSize:15,bold:true,color:m[3]});
  s.addText(m[2],{x:x+1.05,y:y+0.72,w:4.75,h:0.9,fontFace:F,fontSize:11.5,color:"44483F",lineSpacingMultiple:1.15});});
footer(s);

// P7 도착시각 추정 알고리즘
s=pres.addSlide(); header(s,"개발 프로그램 설명 ② ★ 핵심 알고리즘  |  기술성·완성도","죽은 노드의 (좌표·시각) → 불의 방향·속도");
const steps=[["1","죽은 시각 수집","각 노드가 임계온도에 타 죽은 시각 = 불이 그 지점에 도착한 시각."],
["2","최소제곱 평면 적합","흩어진 (x, y, 죽은시각) 점들에 가장 잘 맞는 면을 긋는다 (딥러닝 아님)."],
["3","기울기 → 방향·속도","평면의 기울기 방향 = 진행 방향, 1 / 기울기 크기 = 진행 속도."]];
let sy=1.8; steps.forEach(st=>{
  s.addShape(pres.ShapeType.ellipse,{x:0.62,y:sy,w:0.5,h:0.5,fill:{color:C.FOREST},line:{type:"none"}});
  s.addText(st[0],{x:0.62,y:sy,w:0.5,h:0.5,fontFace:F,fontSize:18,bold:true,color:C.WHITE,align:"center",valign:"middle"});
  s.addText(st[1],{x:1.28,y:sy-0.02,w:5.7,h:0.4,fontFace:F,fontSize:15,bold:true,color:C.INK});
  s.addText(st[2],{x:1.28,y:sy+0.36,w:5.7,h:0.6,fontFace:F,fontSize:12,color:"50544B",lineSpacingMultiple:1.15}); sy+=1.28;});
const dx=7.55,dy=1.9,dw=5.05,dh=3.4; card(s,dx,dy,dw,dh,C.WHITE);
s.addText("도착시각 지도 (개념)",{x:dx+0.25,y:dy+0.16,w:dw-0.5,h:0.35,fontFace:F,fontSize:12,bold:true,color:C.ASH});
const grid=[];for(let r=0;r<3;r++)for(let cX=0;cX<4;cX++)grid.push([cX,r]);
grid.forEach(([gx,gy])=>{const nx=dx+0.75+gx*1.05,ny=dy+1.0+gy*0.72,t=gx/3,col=t<0.34?C.EMBER:t<0.67?C.EMBER2:C.MOSS;
  s.addShape(pres.ShapeType.ellipse,{x:nx,y:ny,w:0.26,h:0.26,fill:{color:col},line:{color:C.WHITE,width:1}});});
s.addText("먼저 죽음",{x:dx+0.5,y:dy+0.58,w:1.2,h:0.28,fontFace:F,fontSize:9.5,color:C.EMBER,align:"center"});
s.addText("나중 죽음",{x:dx+3.3,y:dy+0.58,w:1.2,h:0.28,fontFace:F,fontSize:9.5,color:C.FOREST,align:"center"});
s.addShape(pres.ShapeType.line,{x:dx+0.75,y:dy+2.95,w:3.3,h:0,line:{color:C.INK,width:2.5,endArrowType:"triangle"}});
s.addText("불 진행 방향",{x:dx+0.75,y:dy+3.02,w:3.5,h:0.3,fontFace:F,fontSize:11,bold:true,color:C.INK});
s.addText([{text:"가벼운 최소제곱 — 저사양 게이트웨이에서 즉시 계산.  ",options:{color:"50544B"}},{text:"방향 견고(2.1°), 속도는 보수적(안전마진).",options:{bold:true,color:C.FOREST}}],{x:0.62,y:5.75,w:11.9,h:0.4,fontFace:F,fontSize:12.5});
footer(s);

// P8 오탐 방어 (헤드라인)
s=pres.addSlide(); header(s,"개발 프로그램 설명 ③ ★ 오탐 방어 (헤드라인)  |  독창성·기술성","'통신두절'인가, '진짜 파괴'인가");
s.addText("노드가 조용해졌다고 다 죽은 게 아니다. 잠깐 끊긴 것(통신두절)을 죽음으로 오판하면 가짜 화선이 그려진다. 우리는 두 층으로 구분한다.",{x:0.6,y:1.6,w:12.1,h:0.7,fontFace:F,fontSize:14,color:C.INK,lineSpacingMultiple:1.25});
infoCard(s,0.6,2.5,5.95,2.5,"1층 · 다중 이웃 교차검증","한 노드가 침묵해도 즉시 죽음으로 보지 않는다. K개 이웃(K_confirm=3)이 독립적으로 '연결 끊김'을 확인해야 사망 후보로 승격 — 일시적 링크 노이즈를 걸러낸다.",C.INK);
infoCard(s,6.73,2.5,5.99,2.5,"2층 · 온도 교차검증","사망 후보가 직전에 고온을 겪었는가? 화선에 의한 죽음이면 온도 상승이 선행한다. 온도 정황이 뒷받침될 때만 '화선 사망'으로 확정.",C.EMBER,C.AMB);
s.addText([{text:"결과: ",options:{bold:true,color:C.INK}},{text:"측정 전 구간(통신두절 0.30까지) 오탐률 0%",options:{bold:true,color:C.FOREST}},{text:".  초기 설계의 관대판정發 오탐(0.20~)을 원인 특정해 제거.  이 계층이 죽음을 단순 우회하는 stock 메시와의 진짜 차별점이다.",options:{color:C.INK}}],{x:0.6,y:5.3,w:12.1,h:0.6,fontFace:F,fontSize:13,lineSpacingMultiple:1.2});
footer(s);

// P9 자가치유 + 임종신호
s=pres.addSlide(); header(s,"개발 프로그램 설명 ④ 자가치유 라우팅 · 임종신호  |  기술성","길이 끊겨도 관측은 죽지 않는다");
infoCard(s,0.6,1.65,5.95,3.05,"자가치유 라우팅","· sink(id 0) 기준 역방향 BFS로 각 노드의 상행 경로를 구성.\n· 노드가 DEAD로 확정되면 영향 구역만 경로를 즉시 재계산.\n· 연결성이 유지되는 한, 죽은 노드를 우회해 데이터가 계속 sink에 도달.\n\n※ 재라우팅 실지연은 실물에서 첫 실측(Phase C). 시뮬의 100ms는 틱값(성능 아님).",C.INK);
infoCard(s,6.73,1.65,5.99,3.05,"임종신호 (Last-Gasp)","· 노드가 임계온도를 넘어 죽기 직전, 마지막 패킷을 방출.\n· '언제 죽었는가'를 확정 → 도착시각 추정의 입력 시각을 정밀화.\n· 하트비트(주기 신호) 누락과 결합해 침묵을 판정.\n\n죽음의 '시각'이 정확할수록 화선 방향·속도 추정이 정밀해진다.",C.FOREST,C.TINT);
s.addText("자가치유(관측 지속) + 임종신호(죽음의 시각 확정)가 만나, '죽는 노드'가 '살아있는 정보'가 된다.",{x:0.6,y:5.0,w:12.1,h:0.5,fontFace:F,fontSize:13,italic:true,bold:true,color:C.FOREST,align:"center"});
footer(s);

// P10 파일 구성·검증 규율
s=pres.addSlide(); header(s,"개발 프로그램 설명 ⑤ 구성 · 개발 규율  |  기술성·완성도","코드 구성과 'measure-first' 규율");
infoCard(s,0.6,1.65,6.0,3.3,"저장소 구성","· sim/  — 네트워크 시뮬레이터·도착시각 추정기\n· firmware/  — ESP32 노드 펌웨어(C/C++)\n· gateway/  — 라즈베리파이 추정기(Python, sim 재사용)\n· dashboard/  — 자체완결 웹 관제\n· docs/  — 연구노트(PROGRESS·DECISIONS·STRESS_REPORT)\n\n결정 로그(D-001~)·진행 로그를 남겨 '정직한 연구 여정' 자체를 자산화.",C.INK);
infoCard(s,6.73,1.65,5.99,3.3,"measure-first 규율","· 시뮬은 항상 seed 고정 → 결과 재현 가능.\n· 결과가 나빠도 파라미터를 유리하게 고치지 않는다(기록만).\n   → 데모에만 맞춘 overfitting 함정 회피.\n· 새 요인은 '환경'만 어렵게, 추정기·방어 로직은 불변으로 측정.\n\n이 규율 덕에 스트레스·괴리 수치를 심사에서 그대로 방어할 수 있다.",C.FOREST,C.TINT);
s.addText("→ 완성도는 '보기 좋은 숫자'가 아니라 '재현 가능하고 정직하게 측정된 숫자'에서 나온다.",{x:0.6,y:5.25,w:12.1,h:0.4,fontFace:F,fontSize:13,italic:true,bold:true,color:C.FOREST});
footer(s);

// =====================================================================
// 4. 개발 중 장애요인·해결
// =====================================================================
// P11 시뮬 선개발 + 정직화
s=pres.addSlide(); header(s,"장애요인·해결 ①  |  기술성(문제해결·공학 성숙도)","하드웨어 없이 먼저 검증하고, 정직하게 교정");
infoCard(s,0.6,1.65,5.95,2.35,"장애 · 하드웨어 리스크","부품 도착 전 알고리즘을 못 짜면 개발이 지연되고, 실물에서 처음 검증하면 리스크가 크다.",C.EMBER,C.AMB);
infoCard(s,6.73,1.65,5.99,2.35,"해결 · 시뮬 선(先)개발","네트워크 시뮬레이터로 4대 기능을 먼저 구현·검증. 정상 조건에서 방향 2.12°·속도 0.10%·전달률 92.3%·오탐 0% 확보.",C.FOREST,C.TINT);
infoCard(s,0.6,4.2,5.95,2.35,"장애 · 가짜로 좋은 수치","초기엔 바람이 고정 파형이라 시드를 바꿔도 오차가 안 변해 에러바가 가짜로 0에 가까웠다.",C.EMBER,C.AMB);
infoCard(s,6.73,4.2,5.99,2.35,"해결 · 측정 정직화 (#2b)","바람을 시드마다 다른 실현으로 바꿔 진짜 통계로. 재특성화 결과: 방향·위치는 견고, 속도는 취약 → '방향 신뢰, 속도 보수적' 원칙 확립.",C.FOREST,C.TINT);
footer(s,"정직성 서사 = 과대포장 배제");

// P12 하드웨어 괴리 · 시계 동기 (#2c)
s=pres.addSlide(); header(s,"장애요인·해결 ② ★ 하드웨어 괴리 선점  |  공학 성숙도·차별화","가장 무섭던 위험 '시계 동기'를 실물 전에 정량화");
s.addText([{text:"시뮬은 모든 노드가 시계 하나를 공유하지만, 실물 ESP32는 저마다 시계가 어긋난다(드리프트). 우리 추정기는 죽은 '시각 차이'로 방향·속도를 뽑기에, 시계 오차가 곧 추정 오차가 될 수 있다 — ",options:{color:C.INK}},{text:"시뮬에선 안 보이는 실물 전용 위험.",options:{bold:true,color:C.EMBER}}],{x:0.6,y:1.6,w:12.1,h:1.0,fontFace:F,fontSize:13.5,lineSpacingMultiple:1.25});
statBox(s,0.9,2.9,2.6,"2.13°","방향오차","시계지터 300ms에서");
statBox(s,3.75,2.9,2.6,"2.8%","속도오차","300ms에서");
statBox(s,6.6,2.9,2.6,"0%","오탐률","통신두절 0.30까지");
statBox(s,9.45,2.9,2.6,"12+","권장 노드수","저밀도 속도붕괴 근거");
infoCard(s,0.6,4.65,12.13,1.75,"대응 · painlessMesh 메시 시각 동기 + 시뮬 정량화(#2c)","우리가 고른 라이브러리가 마침 메시 전체 공유 시각(getNodeTime())을 제공 → 드리프트를 근본 완화. 시뮬로 잔여 지터를 0~300ms 주입해도 방향은 견고(2.1°). ①라이브러리 대응 ②시뮬로 허용치 확보 ③실제값은 실물에서 확인 — 세 겹으로 선점.",C.FOREST,C.TINT);
footer(s,"#2c · measure-first");

// P13 오탐 방어의 새 시험대 (#2c 발견 + #2d 방어·진단)
s=pres.addSlide(); header(s,"장애요인·해결 ③ ★ 새 한계의 발굴·진단·해결  |  공학 성숙도","'비화재 사망' — 발견부터 해결까지");
s.addText([{text:"#2c에서 ",options:{color:C.INK}},{text:"새 축의 한계를 스스로 발굴",options:{bold:true,color:C.EMBER}},{text:" — 불이 아닌 죽음(배터리·고장)을 화선 사망으로 오분류. '찬 구역은 방어된다'는 우리 가설을 측정으로 반증하고, 원인을 특정해 제거했다.",options:{color:C.INK}}],{x:0.6,y:1.6,w:12.1,h:1.0,fontFace:F,fontSize:13.5,lineSpacingMultiple:1.25});
infoCard(s,0.6,2.85,5.95,2.15,"진단 (#2e-1 · 측정)","'위험한 찬 구역은 방어된다'는 가설을 측정으로 반증 — 찬(COOL) 비화재 누수 86.4%. 원인은 이웃 표본 부족 시 관대 채택(설계 구멍, 물리적 한계 아님)으로 특정.",C.EMBER,C.AMB);
infoCard(s,6.73,2.85,5.99,2.15,"해결 (#2e-2)","관대 채택을 멈춰 COOL 누수 86.4%→0%, 방향 오염 제거(적대적 8개서 15.7°→2.7°). 남은 통과는 참 화선과 일치하는 무해 HOT뿐. 보너스로 기존 오탐 breakpoint(0.20)도 소멸.",C.FOREST,C.TINT);
s.addText("→ 발견→가설→반증→진단→해결의 완결. '한계를 아는' 것을 넘어 '고치는' 성숙도. (estimator 수학 불변, 선별 로직만)",{x:0.6,y:5.25,w:12.1,h:0.4,fontFace:F,fontSize:13,italic:true,bold:true,color:C.FOREST});
footer(s,"#2c 발견 · #2e 진단·해결");

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
statBox(s,0.6,1.6,2.85,"2.12°","방향오차","정상 조건");
statBox(s,3.65,1.6,2.85,"0.10%","속도오차","정상 조건(보수적 해석)");
statBox(s,6.7,1.6,2.85,"92.3%","전달률","자가치유 포함");
statBox(s,9.75,1.6,2.85,"0%","오탐률","통신두절 오판");
s.addText("작동 한계선 (operating envelope) — 어디까지 버티는가",{x:0.6,y:3.4,w:12,h:0.35,fontFace:F,fontSize:13,bold:true,color:C.INK});
const eh=t=>({text:t,options:{fontFace:F,fontSize:11,bold:true,color:C.WHITE,fill:{color:C.FOREST},valign:"middle",align:"left",margin:[3,6,3,6]}});
const ec=(t,o={})=>({text:t,options:{fontFace:F,fontSize:10.5,color:"3A3E37",valign:"middle",align:"left",margin:[3,6,3,6],...o}});
s.addTable([
  [eh("축"),eh("한계선 / 결과"),eh("의미")],
  [ec("노드 밀도",{bold:true}),ec("12노드 이상에서 속도 안정 (9노드서 붕괴)"),ec("'12+ 운용' 근거 → 실물 16 + 시뮬 확장")],
  [ec("시계 지터",{bold:true}),ec("300ms까지 방향 2.1° 견고"),ec("메시 시각 동기로 사실상 해소")],
  [ec("통신두절",{bold:true}),ec("측정 전 구간(0.30)까지 오탐 0%"),ec("관대판정 제거로 초기 breakpoint 소멸")],
  [ec("비화·비화재",{bold:true}),ec("비화 2개+ 취약 · 비화재 COOL 누수 차단"),ec("#2e: COOL 86.4%→0%, 잔여는 무해 HOT")],
],{x:0.6,y:3.8,w:12.13,colW:[2.2,5.0,4.93],rowH:[0.38,0.55,0.55,0.55,0.55],border:{type:"solid",color:C.LINE,pt:1},valign:"middle"});
s.addText("🟡 실물 정량지표(재라우팅 실지연·추정오차·전달률·오탐률)는 부품 도착 후 실측하여 이 자리에 삽입.",{x:0.6,y:6.6,w:12.1,h:0.35,fontFace:F,fontSize:11.5,italic:true,color:C.EMBER});
footer(s,"🟡 실측 자리 확보");

// =====================================================================
// 6. 파급력·기대효과
// =====================================================================
// P16 수요자·활용
s=pres.addSlide(); header(s,"파급력·기대효과 ① 활용  |  활용성 20","누가 쓰고, 어떻게 배포하나");
infoCard(s,0.6,1.65,5.95,2.2,"수요자 1 · 진화 지휘부","지표 화선의 실시간 위치·방향·속도로 '어디에 자원을 먼저 투입할지' 판단. 자원 배치 정확도↑.",C.INK);
infoCard(s,6.73,1.65,5.99,2.2,"수요자 2 · 최전선 대원","'이 구역에 전선 N분 내 도달' 대피 타이밍 제공. 대원 안전과 직결(속도는 안전마진으로 보수적 경보).",C.EMBER,C.AMB);
infoCard(s,0.6,4.05,5.95,2.35,"배포 · 고위험 구역 사전 배치","상습 발화지, 도시·마을 인접 산림(WUI), 주요 시설·문화재·등산로에 핀포인트. 초저가라 촘촘히 깔아도 부담 적음(사전 배치는 상용 선례로 검증).",C.INK);
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
  [tc("① 시뮬·알고리즘",{bold:true}),tc("~완료"),tc("네트워크 시뮬·도착시각 추정·스트레스·괴리 정량화(#2c)"),tc("✅ 완료",{color:C.FOREST,bold:true})],
  [tc("② 실물 포팅",{bold:true}),tc("부품 후 ~1주"),tc("16노드 플래시·메시/임종신호 실제 RF 검증·통합"),tc("진행 예정",{color:C.ASH})],
  [tc("③ 데모·측정",{bold:true}),tc("이후"),tc("열원 트리거 데모 · 재라우팅/추정오차/전달률 실측"),tc("🟡 실측",{color:C.EMBER,bold:true})],
  [tc("④ 문서·영상",{bold:true}),tc("~제출(9/4)"),tc("보고서 PPT 완성 · 시연영상 · GitHub Public"),tc("진행 중",{color:C.ASH})],
],{x:0.6,y:1.6,w:12.13,colW:[2.5,2.0,5.63,2.0],rowH:[0.4,0.62,0.62,0.62,0.62],border:{type:"solid",color:C.LINE,pt:1},valign:"middle"});
infoCard(s,0.6,4.7,12.13,1.75,"1인 업무 분장 (영역별)","펌웨어(ESP32·painlessMesh) · 알고리즘/게이트웨이(Python 추정기) · 하드웨어(16노드 조립·데모) · 문서/발표(보고서·영상)를 단독으로 단계적 수행. 시뮬 선개발로 리스크를 앞당겨 해소하고, measure-first로 범위를 통제 — 1인 개발의 범위 관리·완결 역량을 보인다.",C.FOREST,C.TINT);
footer(s);

pres.writeFile({fileName:"불사_개발완료보고서_초안.pptx"}).then(fn=>console.log("SAVED",fn,"· pages:",PAGE));
