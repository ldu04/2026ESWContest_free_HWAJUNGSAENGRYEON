// 불사 / 화중생련 — 표지 스타일 4방향 비교 (한자 不死 제거, 색감 유지·구도만 변형)
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: "맑은 고딕", bodyFontFace: "맑은 고딕" };
const C = { INK:"1F2421", FOREST:"2C5F2D", MOSS:"97BC62", EMBER:"D35400", EMBER2:"E8A15C",
  ASH:"6B6E6A", PAPER:"FBF9F4", LINE:"E2DCD0", WHITE:"FFFFFF", DEEP:"16211A" };
const F = "맑은 고딕";

function meshMotif(slide, ox, oy, scale, onDark) {
  const nodes = [[0,0.15,0],[0.9,0,0],[1.7,0.35,0],[2.5,0.1,0],[0.4,1,1],[1.3,0.85,1],[2.1,1.15,1],
    [0.1,1.8,0],[1,1.75,0],[1.9,2,0],[2.6,1.7,0]];
  const edges = [[0,1],[1,2],[2,3],[0,4],[1,5],[2,6],[4,5],[5,6],[4,7],[5,8],[6,9],[9,10],[3,10]];
  const px=v=>ox+v*scale, py=v=>oy+v*scale;
  edges.forEach(([a,b])=>{const na=nodes[a],nb=nodes[b];slide.addShape(pres.ShapeType.line,{x:px(na[0]),y:py(na[1]),w:px(nb[0])-px(na[0]),h:py(nb[1])-py(na[1]),line:{color:onDark?"3A4A3A":C.LINE,width:0.75}});});
  nodes.forEach(([x,y,dead])=>{const d=0.11*scale;slide.addShape(pres.ShapeType.ellipse,{x:px(x)-d/2,y:py(y)-d/2,w:d,h:d,fill:{color:dead?C.EMBER:(onDark?C.MOSS:C.FOREST)},line:{type:"none"}});});
}
// 도착시각 필드(격자 노드, 대각 그라데이션) — C안 전용
function arrivalField(slide, x, y, w, h, cols, rows, dim) {
  const grad = [C.EMBER, C.EMBER, C.EMBER2, C.MOSS, C.FOREST];
  for (let r=0;r<rows;r++) for(let cX=0;cX<cols;cX++){
    const nx=x+(w*(cX+0.5))/cols, ny=y+(h*(r+0.5))/rows;
    const t=(cX/(cols-1)*0.7 + r/(rows-1)*0.3); // 대각 진행
    const col=grad[Math.min(grad.length-1, Math.floor(t*grad.length))];
    const d=0.14;
    slide.addShape(pres.ShapeType.ellipse,{x:nx-d/2,y:ny-d/2,w:d,h:d,fill:{color:col,transparency:dim||0},line:{type:"none"}});
  }
}

// ============ A안 · 앰버 온 차콜 (다크 에디토리얼) ============
let s = pres.addSlide(); s.background={color:C.INK};
s.addText("A안 · 앰버 온 차콜",{x:0.4,y:0.15,w:5,h:0.3,fontFace:F,fontSize:10,color:"5A655C"});
meshMotif(s,9.1,1.1,0.62,true);
s.addText("제24회 임베디드SW경진대회  ·  자유공모 부문",{x:0.85,y:1.9,w:8,h:0.35,fontFace:F,fontSize:14,color:C.MOSS,bold:true});
s.addText("불사",{x:0.8,y:2.3,w:9,h:1.4,fontFace:F,fontSize:76,bold:true,color:C.WHITE});
s.addText([{text:"화중생련  ",options:{}},{text:"火中生蓮",options:{}}],{x:0.85,y:3.85,w:9,h:0.5,fontFace:F,fontSize:22,bold:true,color:C.MOSS});
s.addText("고장(노드 파괴)을 데이터로 바꾸는 자가치유 산불 감시 메시",{x:0.85,y:4.55,w:9.5,h:0.5,fontFace:F,fontSize:16,color:"CFD6CB"});
s.addShape(pres.ShapeType.line,{x:0.85,y:6.35,w:11.6,h:0,line:{color:"3A4A3A",width:1}});
s.addText([{text:"이동욱",options:{bold:true,color:C.WHITE}},{text:"  전자공학전공 · 숭실대학교",options:{color:"AEB5AC"}}],{x:0.85,y:6.5,w:8,h:0.4,fontFace:F,fontSize:13});

// ============ B안 · 라이트 에디토리얼 (밝고 여백 큰 타이포) ============
s = pres.addSlide(); s.background={color:C.PAPER};
s.addText("B안 · 라이트 에디토리얼",{x:0.4,y:0.15,w:5,h:0.3,fontFace:F,fontSize:10,color:C.LINE});
meshMotif(s,10.4,0.7,0.42,false);
s.addText("제24회 임베디드SW경진대회 · 자유공모 부문",{x:0.9,y:1.7,w:9,h:0.35,fontFace:F,fontSize:13,bold:true,color:C.EMBER,charSpacing:1});
s.addText("불사",{x:0.85,y:2.15,w:9,h:1.6,fontFace:F,fontSize:88,bold:true,color:C.INK});
s.addShape(pres.ShapeType.line,{x:0.95,y:3.95,w:2.1,h:0,line:{color:C.EMBER,width:3}});
s.addText([{text:"화중생련  ",options:{color:C.FOREST}},{text:"火中生蓮",options:{color:C.ASH}}],{x:0.9,y:4.15,w:9,h:0.5,fontFace:F,fontSize:20,bold:true});
s.addText("고장(노드 파괴)을 데이터로 바꾸는 자가치유 산불 감시 메시",{x:0.9,y:4.85,w:10,h:0.5,fontFace:F,fontSize:16,color:"50544B"});
s.addShape(pres.ShapeType.line,{x:0.9,y:6.35,w:11.5,h:0,line:{color:C.LINE,width:1}});
s.addText([{text:"이동욱",options:{bold:true,color:C.INK}},{text:"  전자공학전공 · 숭실대학교",options:{color:C.ASH}}],{x:0.9,y:6.5,w:8,h:0.4,fontFace:F,fontSize:13});

// ============ C안 · 필드맵 (도착시각 지도가 곧 표지) ============
s = pres.addSlide(); s.background={color:C.DEEP};
s.addText("C안 · 필드맵",{x:0.4,y:0.15,w:5,h:0.3,fontFace:F,fontSize:10,color:"3A4A3A"});
arrivalField(s, 4.4, 0.6, 8.6, 6.3, 9, 6, 12); // 우측 대각 필드
s.addShape(pres.ShapeType.line,{x:5.0,y:6.1,w:6.4,h:0,line:{color:"E8E2D0",width:2,endArrowType:"triangle",transparency:20}});
s.addText("불 진행 방향",{x:5.0,y:6.18,w:3,h:0.3,fontFace:F,fontSize:11,bold:true,color:"C9CFC2",transparency:10});
// 좌측 스크림 + 타이틀
s.addShape(pres.ShapeType.rect,{x:0,y:0,w:5.2,h:7.5,fill:{color:C.DEEP,transparency:15},line:{type:"none"}});
s.addText("제24회 임베디드SW경진대회",{x:0.7,y:2.0,w:5,h:0.35,fontFace:F,fontSize:13,color:C.MOSS,bold:true});
s.addText("불사",{x:0.65,y:2.4,w:5,h:1.4,fontFace:F,fontSize:80,bold:true,color:C.WHITE});
s.addText([{text:"화중생련 ",options:{color:C.MOSS}},{text:"火中生蓮",options:{color:C.MOSS}}],{x:0.7,y:3.95,w:5,h:0.5,fontFace:F,fontSize:19,bold:true});
s.addText("죽은 노드가 그리는 불의 지도",{x:0.7,y:4.6,w:4.6,h:0.7,fontFace:F,fontSize:15,color:"CFD6CB",lineSpacingMultiple:1.2});
s.addText([{text:"이동욱",options:{bold:true,color:C.WHITE}},{text:" · 전자공학전공 · 숭실대",options:{color:"9EA69C"}}],{x:0.7,y:6.4,w:5,h:0.4,fontFace:F,fontSize:12});

// ============ D안 · 볼드 스플릿 (좌 다크 패널 / 우 라이트) ============
s = pres.addSlide(); s.background={color:C.PAPER};
s.addText("D안 · 볼드 스플릿",{x:0.4,y:0.13,w:5,h:0.3,fontFace:F,fontSize:10,color:C.LINE});
s.addShape(pres.ShapeType.rect,{x:0,y:0,w:5.4,h:7.5,fill:{color:C.FOREST},line:{type:"none"}});
meshMotif(s,1.2,4.7,0.5,true);
s.addText("불사",{x:0.55,y:2.3,w:4.6,h:1.4,fontFace:F,fontSize:78,bold:true,color:C.WHITE});
s.addShape(pres.ShapeType.line,{x:0.7,y:3.95,w:1.7,h:0,line:{color:C.EMBER,width:3}});
s.addText([{text:"화중생련 ",options:{color:"D9E4CB"}},{text:"火中生蓮",options:{color:"AEC08F"}}],{x:0.6,y:4.15,w:4.6,h:0.5,fontFace:F,fontSize:18,bold:true});
// 우측
s.addText("제24회 임베디드SW경진대회 · 자유공모 부문",{x:5.9,y:2.3,w:6.8,h:0.35,fontFace:F,fontSize:13,bold:true,color:C.EMBER});
s.addText("고장을 데이터로 바꾸는\n자가치유 산불 감시 메시",{x:5.88,y:2.75,w:6.9,h:1.3,fontFace:F,fontSize:27,bold:true,color:C.INK,lineSpacingMultiple:1.1});
s.addText("사라진 노드들이 오히려 불의 방향·속도를 그린다.",{x:5.9,y:4.25,w:6.8,h:0.5,fontFace:F,fontSize:14,color:"50544B"});
s.addShape(pres.ShapeType.line,{x:5.9,y:6.35,w:6.6,h:0,line:{color:C.LINE,width:1}});
s.addText([{text:"이동욱",options:{bold:true,color:C.INK}},{text:"  전자공학전공 · 숭실대학교",options:{color:C.ASH}}],{x:5.9,y:6.5,w:6.6,h:0.4,fontFace:F,fontSize:13});

pres.writeFile({fileName:"불사_표지_4방향.pptx"}).then(fn=>console.log("SAVED",fn));
