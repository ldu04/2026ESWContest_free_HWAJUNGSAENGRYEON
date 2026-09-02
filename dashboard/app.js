/* app.js — failsafe-mesh 관제 대시보드 재생 플레이어 (지시서 #3)
 * 코어 불변: export된 Snapshot(dict) 스트림만 소비한다. [D-019]
 * 렌더는 순수 Canvas 2D(외부 라이브러리 없음).
 */
(function () {
  "use strict";

  var COL = {
    ALIVE: "#2ca02c", DYING: "#ff9021", DEAD: "#3a3f45", SINK: "#1f77b4",
    alert: "#ff4d4f", route: "#4aa3ff", link: "#26303c",
    gt: "#ff5c5c", est: "#2fd36b", txt: "#e6edf3", muted: "#9aa7b4"
  };

  // ---- 데이터 로딩: window.SNAPSHOTS(data.js) 우선, 없으면 JSON fetch ----
  function load(cb) {
    if (window.SNAPSHOTS) { cb(window.SNAPSHOTS); return; }
    fetch("../results/dashboard/snapshots.json")
      .then(function (r) { return r.json(); })
      .then(cb)
      .catch(function (e) {
        document.getElementById("scenBadge").textContent =
          "데이터 로드 실패 — export_snapshots.py 를 먼저 실행하세요";
        console.error(e);
      });
  }

  load(function (DATA) {
    var meta = DATA.meta, FR = DATA.frames;
    var cv = document.getElementById("cv"), ctx = cv.getContext("2d");

    // 딥링크: ?mode=ours|stock & ?f=<frame> (발표 캡처·검증용)
    var qs = new URLSearchParams(location.search);
    var qMode = qs.get("mode") === "stock" ? "stock" : "ours";
    var state = { mode: qMode, i: 0, playing: false, speed: 1 };
    var frames = FR[state.mode];
    var nFrames = frames.length;
    var qf = parseInt(qs.get("f"), 10);
    if (!isNaN(qf)) state.i = Math.max(0, Math.min(nFrames - 1, qf));

    // 시나리오 배지
    var c = meta.config;
    document.getElementById("scenBadge").textContent =
      "시드 " + c.seed + " · " + c.grid_rows + "×" + c.grid_cols + " 노드 · θ" +
      c.theta_deg + "° · 참속도 " + c.speed_true + " m/s";

    // ---- 좌표 변환(월드 m → 캔버스 px, y 뒤집기) ----
    var tf;
    function resize() {
      var r = cv.parentElement.getBoundingClientRect();
      var dpr = window.devicePixelRatio || 1;
      cv.width = Math.max(320, r.width * dpr);
      cv.height = Math.max(240, r.height * dpr);
      var W = cv.width, H = cv.height, b = meta.bounds, pad = 34 * dpr;
      var bw = b.xmax - b.xmin, bh = b.ymax - b.ymin;
      var s = Math.min((W - 2 * pad) / bw, (H - 2 * pad) / bh);
      var ox = pad + (W - 2 * pad - s * bw) / 2;
      var oy = pad + (H - 2 * pad - s * bh) / 2;
      tf = {
        s: s, dpr: dpr,
        x: function (wx) { return ox + s * (wx - b.xmin); },
        y: function (wy) { return H - (oy + s * (wy - b.ymin)); }
      };
      draw();
    }
    window.addEventListener("resize", resize);

    // ---- 렌더 ----
    function draw() {
      var f = frames[state.i], W = cv.width, H = cv.height;
      ctx.clearRect(0, 0, W, H);

      // 전체 링크(옅게)
      var pos = {}, i;
      for (i = 0; i < f.nodes.length; i++) pos[f.nodes[i].id] = f.nodes[i].pos;
      var links = f.topology.links;
      ctx.lineWidth = 1 * tf.dpr; ctx.strokeStyle = COL.link;
      for (i = 0; i < links.length; i++) seg(pos[links[i][0]], pos[links[i][1]]);

      // 자가치유 라우팅 트리(강조)
      var re = f.topology.route_edges;
      ctx.lineWidth = 2.4 * tf.dpr; ctx.strokeStyle = COL.route;
      ctx.globalAlpha = 0.85;
      for (i = 0; i < re.length; i++) seg(pos[re[i][0]], pos[re[i][1]]);
      ctx.globalAlpha = 1;

      // 참 전선(점선): fire_front 지나고 fire_dir에 수직 (실물 HW엔 ground-truth 없음 → 생략)
      if (f.fire_front && f.fire_dir) drawFront(f);

      // 추정 방향 화살표(ours만)
      if (f.est && f.est.dir && f.est.front_point) drawArrow(f.est.front_point, f.est.dir);

      // 대피경보 id 집합
      var alerts = {};
      if (f.est) for (i = 0; i < f.est.alerts.length; i++) alerts[f.est.alerts[i].id] = f.est.alerts[i];

      // 노드
      for (i = 0; i < f.nodes.length; i++) node(f.nodes[i], alerts[f.nodes[i].id]);

      hud(f, alerts);
    }

    function seg(a, b) {
      ctx.beginPath(); ctx.moveTo(tf.x(a[0]), tf.y(a[1])); ctx.lineTo(tf.x(b[0]), tf.y(b[1])); ctx.stroke();
    }

    function drawFront(f) {
      var fp = f.fire_front, n = f.fire_dir;
      var px = -n[1], py = n[0];               // 수직 방향
      var L = (meta.bounds.xmax - meta.bounds.ymin) + 60;
      var a = [fp[0] - px * L, fp[1] - py * L], b = [fp[0] + px * L, fp[1] + py * L];
      ctx.save();
      ctx.setLineDash([9 * tf.dpr, 7 * tf.dpr]);
      ctx.lineWidth = 2 * tf.dpr; ctx.strokeStyle = COL.gt; ctx.globalAlpha = 0.8;
      seg(a, b);
      ctx.restore();
    }

    function drawArrow(p0, d) {
      var len = 12, tip = [p0[0] + d[0] * len, p0[1] + d[1] * len];
      var x0 = tf.x(p0[0]), y0 = tf.y(p0[1]), x1 = tf.x(tip[0]), y1 = tf.y(tip[1]);
      ctx.strokeStyle = COL.est; ctx.fillStyle = COL.est; ctx.lineWidth = 3 * tf.dpr;
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
      var ang = Math.atan2(y1 - y0, x1 - x0), hs = 10 * tf.dpr;
      ctx.beginPath(); ctx.moveTo(x1, y1);
      ctx.lineTo(x1 - hs * Math.cos(ang - 0.4), y1 - hs * Math.sin(ang - 0.4));
      ctx.lineTo(x1 - hs * Math.cos(ang + 0.4), y1 - hs * Math.sin(ang + 0.4));
      ctx.closePath(); ctx.fill();
    }

    function node(nd, alert) {
      var x = tf.x(nd.pos[0]), y = tf.y(nd.pos[1]), R = 8 * tf.dpr;
      if (nd.is_sink) {
        ctx.fillStyle = COL.SINK; ctx.strokeStyle = "#cfe6ff"; ctx.lineWidth = 2 * tf.dpr;
        ctx.beginPath(); ctx.rect(x - R, y - R, 2 * R, 2 * R); ctx.fill(); ctx.stroke();
        label("SINK", x, y - R - 6 * tf.dpr, COL.muted); return;
      }
      if (alert) {                                   // 대피경보 링
        ctx.strokeStyle = COL.alert; ctx.lineWidth = 3 * tf.dpr;
        ctx.beginPath(); ctx.arc(x, y, R + 5 * tf.dpr, 0, 6.283); ctx.stroke();
        label("▲ " + Math.max(0, Math.round(alert.eta)) + "s", x, y - R - 8 * tf.dpr, COL.alert);
      }
      ctx.fillStyle = COL[nd.state] || "#888";
      ctx.strokeStyle = "rgba(0,0,0,.5)"; ctx.lineWidth = 1 * tf.dpr;
      ctx.beginPath(); ctx.arc(x, y, R, 0, 6.283); ctx.fill(); ctx.stroke();
      if (nd.state === "DEAD") {                      // 색약 배려: X 마커
        ctx.strokeStyle = "#8b939b"; ctx.lineWidth = 1.6 * tf.dpr;
        ctx.beginPath();
        ctx.moveTo(x - R * .5, y - R * .5); ctx.lineTo(x + R * .5, y + R * .5);
        ctx.moveTo(x + R * .5, y - R * .5); ctx.lineTo(x - R * .5, y + R * .5); ctx.stroke();
      }
    }

    function label(t, x, y, color) {
      ctx.fillStyle = color; ctx.font = (11.5 * tf.dpr) + "px 'Malgun Gothic',sans-serif";
      ctx.textAlign = "center"; ctx.fillText(t, x, y);
    }

    // ---- HUD ----
    function fmtPct(v) { return v == null ? "–" : (v * 100).toFixed(0) + "%"; }
    function dirDeg(d) { var a = Math.atan2(d[1], d[0]) * 180 / Math.PI; return (a + 360) % 360; }

    function speedBand(est) {
      // 국소 추정치 분산(IQR/2)을 보수적 오차밴드로. per_node speeds.
      var ss = [], k; for (k in est.per_node) ss.push(est.per_node[k].speed);
      if (ss.length < 2) return null;
      ss.sort(function (a, b) { return a - b; });
      var q = function (p) { var idx = (ss.length - 1) * p; var lo = Math.floor(idx);
        return ss[lo] + (ss[idx - lo] || 0) * ((ss[lo + 1] || ss[lo]) - ss[lo]); };
      return (q(0.75) - q(0.25)) / 2;
    }

    function hud(f, alerts) {
      var h = f.hud || {};
      set("mT", f.t.toFixed(1) + "s");
      set("mDeliv", fmtPct(h.delivery_rate));
      set("mDead", h.n_dead != null ? h.n_dead : "–");
      set("mAlert", (h.n_alerts || 0));
      set("mFp", meta.summary[state.mode].false_positives + "  <small>정상조건 0%</small>");

      if (state.mode === "stock" || !f.est || !f.est.dir) {
        set("mDir", "<small>추정 없음</small>");
        set("mSpeed", "<small>추정 없음</small>");
      } else {
        var e = f.est, deg = dirDeg(e.dir).toFixed(0);
        var derr = h.dir_err_deg != null ? " <small>±" + h.dir_err_deg.toFixed(1) + "°</small>" : "";
        set("mDir", deg + "°" + derr);
        var band = speedBand(e);
        var bandTxt = band != null ? " <small>± " + band.toFixed(2) + " (보수)</small>" : " <small>±—</small>";
        set("mSpeed", (e.speed != null ? e.speed.toFixed(2) : "–") + " m/s" + bandTxt);
      }
    }
    function set(id, html) { document.getElementById(id).innerHTML = html; }

    // ---- 컨트롤 ----
    var seek = document.getElementById("seek"), tlabel = document.getElementById("tlabel");
    var playBtn = document.getElementById("playBtn");
    seek.max = nFrames - 1;

    function updateSeek() {
      seek.value = state.i;
      tlabel.textContent = frames[state.i].t.toFixed(1) + "s / " + frames[nFrames - 1].t.toFixed(1) + "s";
    }
    function render() { draw(); updateSeek(); }

    seek.addEventListener("input", function () { state.i = +seek.value; render(); });
    playBtn.addEventListener("click", function () { state.playing ? pause() : play(); });
    function play() { state.playing = true; playBtn.textContent = "⏸ 일시정지"; last = null; requestAnimationFrame(tick); }
    function pause() { state.playing = false; playBtn.textContent = "▶︎ 재생"; }

    var last = null, acc = 0;
    function tick(ts) {
      if (!state.playing) return;
      if (last == null) last = ts;
      acc += (ts - last) / 1000; last = ts;
      var step = meta.config.dt / state.speed;      // dt=0.1 → 1× 실시간(10fps)
      while (acc >= step) {
        acc -= step;
        state.i++;
        if (state.i >= nFrames) { state.i = nFrames - 1; pause(); render(); return; }
      }
      render();
      requestAnimationFrame(tick);
    }

    // 속도 세그먼트
    Array.prototype.forEach.call(document.querySelectorAll("#speedSeg button"), function (btn) {
      btn.addEventListener("click", function () {
        state.speed = +btn.dataset.sp;
        seg_active("#speedSeg", btn);
      });
    });
    // 모드 세그먼트(ours/stock)
    Array.prototype.forEach.call(document.querySelectorAll("#modeSeg button"), function (btn) {
      btn.addEventListener("click", function () { applyMode(btn.dataset.mode); render(); });
    });
    function applyMode(mode) {
      state.mode = mode; frames = FR[mode]; nFrames = frames.length;
      seek.max = nFrames - 1; if (state.i >= nFrames) state.i = nFrames - 1;
      var badge = document.getElementById("modeBadge");
      badge.textContent = mode.toUpperCase();
      badge.className = "mode-badge " + (mode === "ours" ? "mode-ours" : "mode-stock");
      document.getElementById("modeNote").innerHTML = mode === "ours"
        ? "<b>ours</b>: 죽음을 1급 이벤트로 승격 → 화선 방향·속도·ETA·대피경보를 추가 산출."
        : "<b>stock</b>: 자가치유 라우팅만. 죽음은 단순 손실 — 추정·경보 없음(연결성만).";
      var sel = "#modeSeg button[data-mode='" + mode + "']";
      seg_active("#modeSeg", document.querySelector(sel));
    }
    function seg_active(sel, btn) {
      Array.prototype.forEach.call(document.querySelectorAll(sel + " button"),
        function (b) { b.classList.remove("active"); });
      if (btn) btn.classList.add("active");
    }

    applyMode(state.mode);   // 초기 모드 UI 동기화(딥링크 ?mode= 반영)
    resize();
    render();
  });
})();
