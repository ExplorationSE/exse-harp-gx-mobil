/* Harp GX Mobil – Web-Client (ohne Build-Schritt, uPlot lokal eingebunden) */
"use strict";
// Kanalfarben: Blau, Amber-Orange, Grün, Rot (kein Pink); 5–8 für größere Geräte
const COLORS = ["#38bdf8", "#f5a623", "#34d399", "#ef4444", "#22d3ee", "#a78bfa", "#d9f99d", "#cbd5e1"];
const K0_COLOR = "#a78bfa";   // T2: Sync-Eingang als Datenkanal K0 (violett)
const chColor = (c) => (c === 0 ? K0_COLOR : COLORS[(c - 1) % COLORS.length]);
// Kanalnummern der Datei: T2 mit Sync-Ereignissen beginnt bei K0
const chanIds = (first, n) => Array.from({ length: n - first + 1 }, (_, i) => first + i);
const Y_FLOOR = 0.5;            // Nullzählungen werden auf diesen Wert geklemmt (log-Achse)
const AXIS = { stroke: "#9fb0c8", font: "11px system-ui,-apple-system,Segoe UI,Roboto,sans-serif",
  labelFont: "600 11px system-ui,-apple-system,Segoe UI,Roboto,sans-serif",
  grid: { stroke: "rgba(148,163,184,0.13)", width: 1 }, ticks: { stroke: "rgba(148,163,184,0.35)", width: 1, size: 4 } };
const SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹";
function pow10Label(v) {
  if (v == null || !(v > 0)) return "";                       // uPlot übergibt ausgefilterte Ticks als null
  const e = Math.round(Math.log10(v));
  if (Math.abs(v - 10 ** e) > 1e-9 * 10 ** e) return "";        // nur Dekaden beschriften
  if (e === 0) return "1"; if (e === 1) return "10";
  return "10" + (e < 0 ? "⁻" : "") + String(Math.abs(e)).split("").map((d) => SUP[d]).join("");
}
function fmtNum(v) { const a = Math.abs(v); return a >= 1e6 ? (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M" : a >= 1e3 ? (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "k" : String(Math.round(v * 100) / 100); }
function fmtCount(v) { return v >= 1e4 ? v.toExponential(2).replace("e+", "e") : String(v); }
const $ = (id) => document.getElementById(id);
const VIEWS = ["hist", "trace", "corr", "g3", "g4"];   // Reihenfolge im Umschalter
const token = new URLSearchParams(location.search).get("token") || "";
const S = { ws: null, status: null, mine: false, hidden: loadHidden(), view: VIEWS.includes(localStorage.getItem("harp.view")) ? localStorage.getItem("harp.view") : "hist",
  lp: {}, hist: null, trace: null, histKey: "",
  traceKey: "", tr: { t: [], r: [] }, lastT: -1, frames: 0, fpsT: performance.now(), fps: 0, rxB: 0, kBps: 0, rtt: null, gxN: 0, gxHz: 0, cmdId: 0,
  lastFrame: null, pendingCtrl: null };

function loadHidden() { try { return new Set(JSON.parse(localStorage.getItem("harp.hidden") || "[]")); } catch (e) { return new Set(); } }
function saveHidden() { try { localStorage.setItem("harp.hidden", JSON.stringify([...S.hidden])); } catch (e) { /* privat */ } }
function toast(msg, err) {
  const t = $("toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toast._h); toast._h = setTimeout(() => (t.className = "toast"), err ? 4000 : 1800);
}
function fmtRate(r) {
  if (r >= 1e6) return [(r / 1e6).toFixed(2), "Mcps"];
  if (r >= 1e3) return [(r / 1e3).toFixed(1), "kcps"];
  return [r.toFixed(0), "cps"];
}
// Binbreite: nur die Breite anzeigen (intern bleibt der Binning-Code der Wert)
function fmtWidth(ps) {
  if (ps >= 1e6) return +(ps / 1e6).toPrecision(4) + " µs";
  if (ps >= 1000) return +(ps / 1000).toPrecision(4) + " ns";
  return +ps.toPrecision(4) + " ps";
}
function fmtSpeed(v) { return Number(v) === 1 ? "Echtzeit" : String(v).replace(".", ",") + "×"; }
// kompakte Zählrate: 40.0M, 13.9k, 850
function fmtCompact(r) {
  if (r >= 1e6) return (r / 1e6).toFixed(r >= 1e8 ? 0 : 1) + "M";
  if (r >= 1e3) return (r / 1e3).toFixed(r >= 1e5 ? 0 : 1) + "k";
  return r.toFixed(0);
}
function fmtBytes(b) { return b > 1e6 ? (b / 1e6).toFixed(2) + " MB" : (b / 1e3).toFixed(1) + " kB"; }

// ------------------------------------------------------------------ WebSocket
// Verbindungsüberwachung: Ping alle 5 s; kommt 10 s lang nichts (auch kein Frame), gilt die Verbindung
// als tot und wird neu aufgebaut. Beim Zurückkehren in den Vordergrund sofort prüfen bzw. neu verbinden.
const PING_MS = 5000, DEAD_MS = 10000;
const C = { lastRx: 0, everOpen: false, hadControl: false, retryT: 0 };
function setConnUI(on) {
  $("conn").className = "dot " + (on ? "on" : "off");
  $("connbar").hidden = on || !C.everOpen;
}
function dropSocket() {
  const ws = S.ws; S.ws = null;
  if (ws) { ws.onopen = ws.onclose = ws.onmessage = ws.onerror = null; try { ws.close(); } catch (e) { /* egal */ } }
}
function lostConnection() {
  if (S.mine) C.hadControl = true;
  S.mine = false;
  if (S.status) S.status.control = { held: false, mine: false };   // unbekannt, bis der Server wieder meldet
  updateCtrl(); setConnUI(false);
}
function reconnect(delay) {
  clearTimeout(C.retryT);
  C.retryT = setTimeout(connect, delay || 0);
}
function connect() {
  clearTimeout(C.retryT);
  dropSocket();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws${token ? "?token=" + encodeURIComponent(token) : ""}`);
  S.ws = ws;
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { C.lastRx = Date.now(); C.everOpen = true; setConnUI(true); sendView(); };
  ws.onclose = (e) => {
    if (S.ws !== ws) return;
    S.ws = null; lostConnection();
    if (e.code === 4401) { location.href = "/login"; return; }   // nicht (mehr) angemeldet
    reconnect(1500);   // automatische Wiederverbindung
  };
  ws.onmessage = (ev) => {
    C.lastRx = Date.now();
    S.rxB += ev.data instanceof ArrayBuffer ? ev.data.byteLength : ev.data.length;   // empfangene Bytes (alle Nachrichten)
    if (ev.data instanceof ArrayBuffer) { onBinary(ev.data).catch((e) => console.warn("GX-Frame", e)); return; }
    const m = JSON.parse(ev.data);
    if (m.type === "frame") onFrame(m, ev.data.length);
    else if (m.type === "status") onStatus(m);
    else if (m.type === "ack") onAck(m);
    else if (m.type === "pong" && m.t) { const r = Date.now() - m.t; S.rtt = S.rtt == null ? r : 0.7 * S.rtt + 0.3 * r; }
    else if (m.type === "trace") { S.tr = { t: m.t.slice(-600), r: m.rates.slice(-600).map((r) => r.map((x) => x / 1000)) };
      S.lastT = m.t.length ? m.t[m.t.length - 1] : -1; }
  };
}
function watchdog() {
  const ws = S.ws;
  if (!ws || ws.readyState !== 1) return;
  if (Date.now() - C.lastRx > DEAD_MS) { lostConnection(); reconnect(0); return; }   // tote/hängende Verbindung
  ws.send(JSON.stringify({ type: "ping", t: Date.now() }));
}
setInterval(watchdog, PING_MS);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  const ws = S.ws;
  if (!ws || ws.readyState > 1) { lostConnection(); reconnect(0); return; }
  if (ws.readyState !== 1) return;   // baut gerade auf
  const t = Date.now();              // Probe: antwortet der Server binnen 3 s? Sonst neu verbinden
  try { ws.send(JSON.stringify({ type: "ping", t })); } catch (e) { /* tot */ }
  setTimeout(() => { if (S.ws === ws && C.lastRx < t) { lostConnection(); reconnect(0); } }, 3000);
});
window.addEventListener("pageshow", (e) => { if (e.persisted) { lostConnection(); reconnect(0); } });
window.addEventListener("online", () => { if (!S.ws || S.ws.readyState !== 1) reconnect(0); });
function send(cmd, params) {
  if (!S.ws || S.ws.readyState !== 1) { toast("Keine Verbindung – wird wiederhergestellt …", true); reconnect(0); return; }
  S.ws.send(JSON.stringify({ type: "command", cmd, params: params || {}, id: ++S.cmdId }));
}
// Steuerbefehl: falls noch keine Steuerung, zuerst übernehmen
function command(cmd, params) {
  if (!S.mine) { S.pendingCtrl = [cmd, params]; send("acquire_control"); return; }
  send(cmd, params);
}
function onAck(m) {
  if (!m.ok) { toast(m.error || "Fehler", true); S.pendingCtrl = null; if (S.status) fillControls(S.status); return; }
  if (m.cmd === "acquire_control" && S.pendingCtrl) { const [c, p] = S.pendingCtrl; S.pendingCtrl = null; S.mine = true; send(c, p); return; }
  if (m.cmd !== "acquire_control" && m.cmd !== "release_control") toast("OK: " + m.cmd);
}

// ------------------------------------------------------------------ Status / Steuerelemente
function onStatus(st) {
  S.status = st; S.mine = !!(st.control && st.control.mine);
  if (C.hadControl) {   // erste Statusmeldung nach Wiederverbindung
    C.hadControl = false;
    if (!S.mine) toast(st.control && st.control.held ? "Verbindung war unterbrochen – ein anderes Gerät steuert jetzt"
      : "Verbindung war unterbrochen – Steuerung wurde abgegeben", true);
  }
  const rs = $("runstate");
  rs.textContent = st.running ? "läuft" : "gestoppt"; rs.className = "pill " + (st.running ? "run" : "stop");
  updateCtrl(); fillControls(st);
  if (st.error) toast(st.error, !st.error.startsWith("Ende"));
}
function updateCtrl() {
  const st = S.status, b = $("ctrlBtn"), other = !S.mine && !!(st && st.control && st.control.held);
  b.classList.toggle("mine", S.mine); b.classList.toggle("viewer", other);
  b.textContent = S.mine ? "Sie steuern" : (other ? "Nur Anzeige" : "Steuerung übernehmen");
  b.title = other ? "Ein anderes Gerät steuert – dieses Gerät zeigt nur an" : "Steuerung übernehmen/abgeben";
  const li = $("lockinfo"); li.classList.toggle("viewer", other);
  li.textContent = S.mine ? "Sie haben die Steuerung" :
    (other ? "Nur Anzeige – ein anderes Gerät steuert" : "Änderung übernimmt die Steuerung automatisch");
}
function fillControls(st) {
  const s = st.settings, info = st.info || {};
  const fsel = $("file");
  const names = (st.files || []).map((f) => f.name);
  if (fsel.dataset.k !== names.join("|")) {
    fsel.innerHTML = names.map((n, i) => `<option value="${n}">${n} (${st.files[i].size_mb} MB)</option>`).join("");
    fsel.dataset.k = names.join("|");
  }
  fsel.value = st.file || "";
  const res = info.resolution_ps || 1, maxb = Math.min(info.max_binning ?? 12, 15);
  const bsel = $("binning"), bk = res + "|" + maxb;
  if (bsel.dataset.k !== bk) {
    let h = ""; for (let b = 0; b <= maxb; b++) { const w = res * 2 ** b;
      h += `<option value="${b}">${fmtWidth(w)}</option>`; }
    bsel.innerHTML = h; bsel.dataset.k = bk;
  }
  const lsel = $("hist_len_code");
  if (!lsel.options.length) for (let c = 0; c <= 7; c++) lsel.add(new Option(String(1024 * 2 ** c) + " Bins", c));
  for (const k of ["refresh_ms", "speed", "binning", "hist_len_code", "mode", "display_points"]) {
    const el = $(k); if (document.activeElement !== el) el.value = String(s[k]);
  }
  if ($("speed").value !== String(s.speed)) { $("speed").add(new Option(fmtSpeed(s.speed), String(s.speed))); $("speed").value = String(s.speed); }
  const nch = info.num_channels || 4, first = info.first_channel ?? 1, ids = chanIds(first, nch), rsel = $("ref_channel");
  if (rsel.dataset.n !== ids.join(",")) {
    rsel.innerHTML = ids.map((c) => `<option value="${c}">K${c}</option>`).join("");
    rsel.dataset.n = ids.join(",");
  }
  if (document.activeElement !== rsel) rsel.value = String(s.ref_channel ?? 1);
  const cbase = info.mode === "T3" ? 1 : res, csel = $("corr_binning"), ck = String(cbase);
  if (csel.dataset.k !== ck) {
    let h = ""; for (let b = 0; b <= 24; b++) { const w = cbase * 2 ** b; if (w >= 1 && w <= 1e7) h += `<option value="${b}">${fmtWidth(w)}</option>`; }
    csel.innerHTML = h; csel.dataset.k = ck;
  }
  if (document.activeElement !== csel) csel.value = String(s.corr_binning);
  if (document.activeElement !== $("window_frames")) $("window_frames").value = s.window_frames;
  $("window_frames").disabled = s.mode !== "sliding";
  $("loop").checked = s.loop;
  fillGnControls(st);
  buildChanButtons(ids);
  renderInfo();
}
function bindControls() {
  $("bStart").onclick = () => command("start");
  $("bStop").onclick = () => command("stop");
  $("bReset").onclick = () => { command("reset"); S.tr = { t: [], r: [] }; };
  $("bRewind").onclick = () => { command("rewind"); S.tr = { t: [], r: [] }; };
  $("file").onchange = (e) => { command("open_file", { name: e.target.value }); S.tr = { t: [], r: [] }; };
  const num = { refresh_ms: parseInt, speed: parseFloat, binning: parseInt, hist_len_code: parseInt, display_points: parseInt, window_frames: parseInt };
  for (const k of Object.keys(num)) $(k).addEventListener("change", (e) => command("set", { [k]: num[k](e.target.value) }));
  $("mode").onchange = (e) => command("set", { mode: e.target.value });
  $("ref_channel").onchange = (e) => command("set", { ref_channel: parseInt(e.target.value) });
  $("corr_binning").onchange = (e) => command("set", { corr_binning: parseInt(e.target.value) });
  $("loop").onchange = (e) => command("set", { loop: e.target.checked });
  $("viewBtn").onclick = (e) => {   // Tippen auf ein Segment wählt es; sonst zur nächsten Ansicht
    const sp = e.target.closest("span[data-v]");
    setView(sp ? sp.dataset.v : VIEWS[(VIEWS.indexOf(S.view) + 1) % VIEWS.length]);
  };
  $("ctrlBtn").onclick = () => send(S.mine ? "release_control" : "acquire_control");
  $("gn_range_ps").onchange = (e) => command("set", { gn_range_ps: parseInt(e.target.value) });
  $("gn_win_ps").onchange = (e) => command("set", { gn_win_ps: parseInt(e.target.value) });
  $("bRecal").onclick = () => command("gn_recal");
  $("gnCombo").onchange = (e) => {
    const v = e.target.value.split(",").map(Number);
    if (S.view === "corr") {           // g²-Paar: nur Anzeige (alle Paare werden ohnehin berechnet)
      G.combo2 = v; try { localStorage.setItem("harp.gn2", v.join(",")); } catch (x) { /* privat */ }
      buildGnBar(); drawGnTiles(); return;
    }
    command("set", { [S.view === "g4" ? "combo4" : "combo3"]: v });
  };
  $("gnTau3").oninput = (e) => { G.tau3 = +e.target.value; drawGn(); };
  $("gnCanvas").addEventListener("pointerdown", gnPick);
  $("gnCanvas").addEventListener("pointermove", (e) => { if (e.buttons) gnPick(e); });
}
// Ansicht im großen Diagramm: Histogramm (log) oder Zählraten-Zeitverlauf (linear, kcps)
function setView(v) {
  S.view = v; try { localStorage.setItem("harp.view", v); } catch (e) { /* privat */ }
  document.querySelectorAll("#viewBtn span").forEach((x) => x.classList.toggle("on", x.dataset.v === v));
  $("histPlot").hidden = v !== "hist"; $("tracePlot").hidden = v !== "trace"; $("corrPlot").hidden = v !== "corr";
  const gn = v === "g3" || v === "g4";
  $("gnPlot").hidden = !gn;
  if (showGnBar()) { buildGnBar(); drawGnTiles(); }
  $("readout").innerHTML = "&nbsp;"; $("readout").dataset.auto = "1"; $("readout").hidden = false;
  $("gnSliderRow").hidden = true;
  sendView();
  if (gn) { buildGnBar(); drawGn(); }
  updateHint();
  onResize(0);
}
// Kanal-Toggles: blenden Kurven nur in der Anzeige ein/aus (kein Steuerbefehl, auch für Zuschauer)
function buildChanButtons(ids) {
  const cb = $("chanbox");
  if (cb.dataset.n === ids.join(",")) return;
  cb.dataset.n = ids.join(",");
  cb.classList.toggle("many", ids.length >= 5);   // 5 Tasten: etwas schmaler, Kopfzeile bleibt einzeilig
  cb.innerHTML = ids.map((c) =>
    `<button type="button" class="chbtn" data-ch="${c}" style="--c:${chColor(c)}" aria-pressed="true">K${c}</button>`).join("");
  cb.querySelectorAll(".chbtn").forEach((b) => b.addEventListener("click", () => {
    const c = +b.dataset.ch;
    if (S.hidden.has(c)) S.hidden.delete(c); else S.hidden.add(c);
    saveHidden(); applyVisibility();
  }));
  applyVisibility();
}
function applyVisibility() {
  document.querySelectorAll(".chbtn").forEach((b) => {
    const off = S.hidden.has(+b.dataset.ch); b.classList.toggle("off", off); b.setAttribute("aria-pressed", String(!off));
  });
  for (const p of Object.values(S.lp)) if (p.u) p.ch.forEach((c, i) => { const show = !S.hidden.has(c);
    if (p.u.series[i + 1].show !== show) p.u.setSeries(i + 1, { show }); });
  if (S.trace) for (let i = 1; i < S.trace.series.length; i++) { const show = !S.hidden.has(S.trCh[i - 1]);
    if (S.trace.series[i].show !== show) S.trace.setSeries(i, { show }); }
  document.querySelectorAll(".rate[data-ch]").forEach((t) => t.classList.toggle("dim", S.hidden.has(+t.dataset.ch)));
}

// ------------------------------------------------------------------ Plots
function plotWidth(el) { return Math.max(240, Math.floor(el.clientWidth)); }
function histHeight() {
  const W = window.innerWidth, H = window.innerHeight;
  const head = document.querySelector(".hist-card .card-head"), top = document.querySelector(".topbar");
  const used = (head ? head.offsetHeight : 40) + 30;             // Kopfzeile + Messwertzeile
  if (W > H && H < 560) return Math.max(160, H - used - 12);     // Handy quer: fast volle Höhe
  if (W >= 1000) return Math.max(320, Math.min(720, H - (top ? top.offsetHeight : 50) - used - 40));
  return Math.round(Math.max(260, Math.min(H * 0.56, W * 1.15)));   // Handy hoch
}
// Einheitliche Diagrammhöhe für alle Ansichten (Histo, g², g³, g⁴, Zeit): Höhe der quadratischen g³/g⁴-Karte
// (Seite = Breite − 2·Rand, + Achsen oben/unten), höchstens histHeight(). Damit beginnt die Leiste darunter
// in allen Ansichten auf derselben Höhe; auf breiten/quer liegenden Bildschirmen gilt weiter histHeight().
const MAP_TOP = 8, MAP_BOT = 40;
function mapMargin(W) { return W < 500 ? 42 : 50; }
function chartHeight() {
  const W = plotWidth(document.querySelector(".chartwrap"));
  return Math.round(Math.max(160, Math.min(histHeight(), W - 2 * mapMargin(W) + MAP_TOP + MAP_BOT)));
}
function histRange(u, mn, mx) {
  const top = Math.max(10, (mx || 1) * 1.6);
  return [Y_FLOOR, 10 ** Math.ceil(Math.log10(top))];
}
// Log-Diagramme: 'hist' (Zeit seit Sync: T3 dtime, T2 seit letztem Sync) und 'corr' (Kreuzkorrelation)
const LOGPLOT = {
  hist: { el: "histPlot", xlab: (m) => (m.hist_kind === "ref" ? `t nach K${m.corr_ref} / ns` : "t nach Sync / ns"),
          sym: "t", suffix: () => "" },
  corr: { el: "corrPlot", xlab: (m) => `τ = t(Kn) − t(K${m.corr_ref}) / ns`, sym: "τ", suffix: (m) => "×K" + m.corr_ref },
};
function makeLog(kind, chans, m) {
  const def = LOGPLOT[kind], el = $(def.el); el.innerHTML = "";
  const p = S.lp[kind] = { ch: chans.slice(), raw: null, key: "", m };
  const series = [{}];
  chans.forEach((c) => series.push({ label: "K" + c, stroke: chColor(c), width: 1.6, show: !S.hidden.has(c),
    points: { show: false }, spanGaps: true }));
  const narrow = chartBox().clientWidth < 500, ysz = narrow ? 34 : 40, corr = kind === "corr";
  // Korrelogramm zentriert: rechts derselbe Rand wie die y-Achse links, x-Bereich symmetrisch um τ = 0
  const xr = corr ? { range: () => { const W = -(S.lp.corr ? S.lp.corr.m.corr_x0_ps : m.corr_x0_ps) / 1000; return [-W, W]; } }
    : { range: (u, mn, mx) => (mn == null || mn === mx ? [0, 1] : [mn, mx]) };   // Daten über volle Breite
  p.u = new uPlot({ width: plotWidth(chartBox()), height: chartHeight(), series, pxAlign: false,
    padding: [8, ysz, 0, 0],   // rechts so breit wie die y-Achse links → Zeichenfläche zentriert
    legend: { show: false },
    cursor: { drag: { x: true, y: false }, points: { size: 7 } },
    scales: { x: { time: false, ...xr }, y: { distr: 3, log: 10, range: histRange } },
    axes: [{ ...AXIS, label: def.xlab(m), labelSize: 16, labelGap: 0, size: 30, gap: 3,
             values: (u, sp) => sp.map((v) => String(+v.toFixed(2))) },
           { ...AXIS, size: ysz, gap: 3, values: (u, sp) => sp.map(pow10Label) }],
    hooks: { setCursor: [(u) => logReadout(kind, u)] } }, [[]], el);
  return p;
}
function logReadout(kind, u) {
  if (S.view !== kind) return;
  const p = S.lp[kind], i = u.cursor.idx, r = $("readout");
  if (i == null || !p || !p.raw) { r.innerHTML = "&nbsp;"; return; }
  const def = LOGPLOT[kind];
  const parts = [`<b>${def.sym} = ${u.data[0][i].toFixed(3)} ns</b>`];
  p.ch.forEach((c, k) => { if (!S.hidden.has(c) && p.raw[k])
    parts.push(`<span style="color:${chColor(c)}">K${c}${def.suffix(p.m)} ${fmtCount(p.raw[k][i])}</span>`); });
  r.innerHTML = parts.join(" · ");
}
function drawLog(kind, chans, rows, x0ps, bwps, m) {
  let p = S.lp[kind];
  const key = chans.join(",") + "|" + m.corr_ref + "|" + m.hist_kind + "|" + (kind === "corr" ? m.corr_x0_ps : "");
  if (!p || p.key !== key) { p = makeLog(kind, chans, m); p.key = key; }
  p.m = m;
  const n = rows.length ? rows[0].length : 0, bw = bwps / 1000, x0 = x0ps / 1000;
  const x = new Float64Array(n); for (let i = 0; i < n; i++) x[i] = x0 + (i + 0.5) * bw;
  p.raw = rows;
  const ys = rows.map((row) => row.map((v) => (v > Y_FLOOR ? v : Y_FLOOR)));   // 0 → Boden, Linie bleibt geschlossen
  p.u.setData([x, ...ys]);
  if (p.u.cursor.idx != null) logReadout(kind, p.u);
}
function drawHist(m) {
  drawLog("hist", m.channels, m.hist, 0, m.bin_width_ps, m);
  if (m.corr) drawLog("corr", m.corr_channels, m.corr, m.corr_x0_ps, m.corr_bin_ps, m);
  S.hist = S.lp.hist && S.lp.hist.u;
  updateHint();
}
function updateHint() {
  const m = S.lastFrame, h = $("chartHint");
  let txt = "";
  if (m && S.view === "hist" && !m.has_histogram)
    txt = "Kein Histogramm verfügbar – bitte „Zeit“ oder „g²“ wählen.";
  else if (m && S.view === "corr" && !m.corr) txt = "Korrelation mit dieser Datenquelle nicht verfügbar.";
  else if (m && S.view === "corr" && m.corr && !m.corr_channels.length) txt = "Keine Kanäle außer dem Referenzkanal.";
  else if (S.view === "g3" || S.view === "g4") txt = gnHint();
  h.innerHTML = gsym(txt); h.hidden = !txt;
  h.classList.toggle("info", S.view === "g3" || S.view === "g4");   // Hinweise zum Sammeln: grau, keine Warnung
}
function makeTrace(ids) {
  const el = $("tracePlot"); el.innerHTML = "";
  const series = [{}];
  S.trCh = ids.slice();
  ids.forEach((c) => series.push({ label: "K" + c, stroke: chColor(c), width: 1.6, points: { show: false },
    show: !S.hidden.has(c) }));
  // gleiche Zeichenfläche wie Histo/g²: y-Achse ysz links, gleich breiter Rand rechts, x-Achse 30 px
  const ysz = chartBox().clientWidth < 500 ? 34 : 40;
  S.trace = new uPlot({ width: plotWidth(chartBox()), height: chartHeight(), series, pxAlign: false, padding: [8, ysz, 0, 0],
    legend: { show: false }, cursor: { points: { size: 6 } },
    scales: { x: { time: false, range: (u, mn, mx) => (mn === mx ? [mn - 1, mx + 1] : [mn, mx]) },
              y: { range: (u, mn, mx) => [0, Math.max(1, (mx || 0) * 1.1)] } }, hooks: { setCursor: [traceReadout] },
    axes: [{ ...AXIS, label: "t / s  ·  Zählrate / kcps", labelSize: 16, labelGap: 0, size: 30, gap: 3, values: (u, sp) => sp.map((v) => String(+v.toFixed(1))) },
           { ...AXIS, size: ysz, gap: 3, values: (u, sp) => sp.map(fmtNum) }] }, [[]], el);
}
function drawTrace(m) {
  const n = m.rates.length, ids = chanIds(m.first_channel ?? 1, (m.first_channel ?? 1) + n - 1);
  if (S.traceKey !== ids.join(",") || !S.trace) { makeTrace(ids); S.traceKey = ids.join(","); }
  if (m.t_file_s < S.lastT) S.tr = { t: [], r: [] };      // Datei neu begonnen
  S.lastT = m.t_file_s;
  S.tr.t.push(m.t_file_s); S.tr.r.push(m.rates.map((r) => r / 1000));
  const MAX = 600; if (S.tr.t.length > MAX) { S.tr.t.splice(0, S.tr.t.length - MAX); S.tr.r.splice(0, S.tr.r.length - MAX); }
  const cols = [S.tr.t]; for (let i = 0; i < n; i++) cols.push(S.tr.r.map((r) => r[i]));
  S.trace.setData(cols);
}
// Breite des sichtbaren Diagrammbereichs (auch wenn die andere Ansicht gerade versteckt ist)
function chartBox() { return $({ hist: "histPlot", trace: "tracePlot", corr: "corrPlot", g3: "gnPlot", g4: "gnPlot" }[S.view]); }
function traceReadout(u) {
  if (S.view !== "trace") return;
  const i = u.cursor.idx, r = $("readout");
  if (i == null || !u.data[0].length) { r.innerHTML = "&nbsp;"; return; }
  const parts = [`<b>t = ${u.data[0][i].toFixed(2)} s</b>`];
  for (let k = 1; k < u.series.length; k++) if (!S.hidden.has(S.trCh[k - 1]) && u.data[k])
    parts.push(`<span style="color:${chColor(S.trCh[k - 1])}">K${S.trCh[k - 1]} ${(u.data[k][i] ?? 0).toFixed(1)} kcps</span>`);
  r.innerHTML = parts.join(" · ");
}
function drawRates(m) {
  // T2: Sync-Eingang ist Datenkanal K0 (eigene Kachel, nur wenn die Datei K0-Ereignisse enthält);
  // T3: Kachel „Sync“ mit der Sync-Rate
  const f = m.first_channel ?? 1, t2 = ((S.status || {}).info || {}).mode === "T2";
  const tiles = t2 || f === 0 ? [] : [["Sync", m.sync_rate, "#cbd5e1", null]];
  m.rates.forEach((r, i) => tiles.push(["K" + (f + i), r, chColor(f + i), f + i]));
  const box = $("rates"); box.style.setProperty("--n", Math.min(tiles.length, 5));
  box.innerHTML = tiles.map(([k, r, c, ch]) =>
    `<div class="rate${ch != null && S.hidden.has(ch) ? " dim" : ""}"${ch != null ? ` data-ch="${ch}"` : ""} style="border-color:${ch != null ? c + "66" : ""}" title="${fmtRate(r).join(" ")}"><div class="k"><i style="background:${c}"></i>${k}</div><div class="v" style="color:${ch != null ? c : ""}">${fmtCompact(r)}</div></div>`).join("");
  $("accinfo").textContent = (m.mode === "sliding" ? "Fenster " : "akkumuliert ") + m.acc_time_s.toFixed(2) + " s";
}
function renderInfo() {
  const st = S.status || {}, info = st.info || {}, m = S.lastFrame;
  const rows = [["Quelle", st.source + (info.record_type ? " · " + info.record_type : "")], ["Datei", st.file || "–"],
    ["Modus", (info.mode || "–") + ", " + (info.num_channels || "?") + " Kanäle"
      + (info.mode === "T2" ? ((info.first_channel ?? 1) === 0 ? " + K0" : "")
        : ", Sync " + fmtRate(info.sync_rate_hz || 0).join(" "))],
    ["Auflösung", (info.resolution_ps || "–") + " ps · Dauer " + (info.duration_s || 0).toFixed(2) + " s"]];
  if (m) rows.push(["Frame", `#${m.seq} · t = ${m.t_file_s.toFixed(2)} s · ${S.fps.toFixed(1)} fps`],
    ["Anzeige", `${m.n_bins} von ${m.n_bins_full} Bins (×${m.rebin_factor}) à ${(m.bin_width_ps / 1000).toFixed(3)} ns`],
    ["Datenmenge", `${fmtBytes(S.lastBytes || 0)}/Frame · ${S.kBps.toFixed(1)} kB/s empfangen · Server ${m.calc_ms} ms`]);
  const gh = G.head;
  if (gh) {
    const dl = Object.entries(gh.delays || {}).map(([k, v]) => `K${k} ${v >= 0 ? "+" : ""}${(v / 1000).toFixed(2)} ns`).join(", ");
    rows.push(["Laufzeiten", (dl || "keine") + (gh.cal_status === "unnoetig" ? " (vernachlässigbar, g² breit)" : gh.cal_status === "kein_merkmal" ? " (kein Merkmal – ohne Offsets)" : gh.cal_status === "teilweise" ? " (unvollständig)" : gh.cal_done ? "" : " (Kalibrierung läuft)")],
      ["Rechenkern", `${gh.backend === "gpu" ? "GPU (wgpu" + (gh.gpu_name ? ", " + gh.gpu_name : "") + ")" : (ENGINE_NAME[gh.backend] || gh.backend) + (gh.threads ? " · " + gh.threads + " Threads" : "")} · ${gh.proc_mtags ?? "–"} Mtags/s · Latenz ${gh.latency_ms} ms${S.rtt != null ? " + Netz ≈ " + Math.round(S.rtt / 2) + " ms" : ""} · ${fmtBytes(G.bytes || 0)}/Frame${(S.view === "g3" || S.view === "g4") && S.gxHz ? " · " + S.gxHz.toFixed(1) + " Hz" : ""}${gh.engine_note ? " · " + gh.engine_note : ""}`]);
  }
  rows.push(["Clients", String(st.clients ?? "–")]);
  if (st.version) $("appver").textContent = "ExSE Harp GX Mobil " + st.version;
  $("infolist").innerHTML = rows.map(([k, v]) => `<dt>${gsym(k)}</dt><dd>${gsym(v)}</dd>`).join("");
  if (m) $("progress").firstElementChild.style.width = (m.progress * 100).toFixed(1) + "%";
}
let infoTick = 0;
function onFrame(m, len) {
  // „lite“: ohne Histogramm-/g²-Kurven (Ansichten g³, g⁴, Zeitverlauf) – die zuletzt empfangenen Kurven bleiben
  const full = !m.lite;
  S.lastFrame = full || !S.lastFrame ? m : { ...S.lastFrame, ...m, lite: false };
  S.lastBytes = len; S.frames++;
  const now = performance.now();
  if (now - S.fpsT > 1000) { const d = now - S.fpsT; S.fps = S.frames * 1000 / d; S.kBps = S.rxB / d; S.gxHz = S.gxN * 1000 / d;
    S.frames = 0; S.rxB = 0; S.gxN = 0; S.fpsT = now; }
  if (full && m.hist) drawHist(m); else updateHint();
  drawRates(m); drawTrace(m);
  if (++infoTick % 3 === 0) renderInfo();
}
// ------------------------------------------------------------------ GX: g³ / g⁴
// Binär-Frame: "GXF1" | uint32 Kopf-Länge | JSON-Kopf | deflate(uint16-Felder, log-kodiert)
const G = { head: null, map3: null, cube4: null, bytes: 0, tau3: null, cut: null, cutKey: "",
  combo2: (localStorage.getItem("harp.gn2") || "").split(",").filter(Boolean).map(Number),
  mode3: localStorage.getItem("harp.gn3") || "map", mode4: localStorage.getItem("harp.gn4") || "slice", geom: null };
const VIRIDIS = [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]];
function sendView() { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ type: "view", v: S.view })); }
async function inflate(u8) {
  if (typeof DecompressionStream === "undefined") throw new Error("Browser ohne DecompressionStream");
  const st = new Blob([u8]).stream().pipeThrough(new DecompressionStream("deflate"));
  return await new Response(st).arrayBuffer();
}
async function onBinary(buf) {
  const dv = new DataView(buf);
  if (String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3)) !== "GXF1") return;
  const n = dv.getUint32(4, true);
  const h = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, n)));
  const raw = await inflate(new Uint8Array(buf, 8 + n));
  for (const m of h.arrays) {
    const cnt = m.shape.reduce((a, b) => a * b, 1), q = new Uint16Array(raw, m.offset, cnt), f = new Float32Array(cnt);
    for (let i = 0; i < cnt; i++) f[i] = q[i] ? 10 ** ((q[i] - 1) / 65534 * h.log_span + h.log_lo) : NaN;
    G[m.name] = { v: f, nb: m.shape[0] };
  }
  G.head = h; G.bytes = buf.byteLength; if (h.arrays.length) S.gxN++;
  if (S.view === "g3" || S.view === "g4") { showGnBar(); buildGnBar(); drawGn(); }
  else if (S.view === "corr" && showGnBar()) { buildGnBar(); drawGnTiles(); }
}
function fillGnControls(st) {
  const s = st.settings, info = st.info || {};
  const opt = (id, vals, cur) => {
    const el = $(id), list = vals.includes(cur) ? vals : [...vals, cur].sort((a, b) => a - b), k = list.join(",");
    if (el.dataset.k !== k) { el.innerHTML = list.map((v) => `<option value="${v}">${fmtWidth(v)}</option>`).join(""); el.dataset.k = k; }
    if (document.activeElement !== el) el.value = String(cur);
  };
  opt("gn_range_ps", [5e3, 1e4, 25e3, 5e4, 1e5, 25e4, 1e6, 25e5, 1e7, 25e6, 1e8], s.gn_range_ps);
  opt("gn_win_ps", [100, 200, 500, 1e3, 2e3, 4e3, 6e3, 1e4, 2e4, 1e5, 5e5, 1e6, 2e6], s.gn_win_ps);
  G.ids = chanIds(info.first_channel ?? 1, Math.min(info.num_channels || 4, 8));
  G.combo3 = s.combo3; G.combo4 = s.combo4;
  if (gnOrder() && !$("gnbar").hidden) buildGnBar();
}
function combos(ids, k) {
  const out = [], rec = (st, acc) => { if (acc.length === k) { out.push(acc.slice()); return; }
    for (let i = st; i < ids.length; i++) { acc.push(ids[i]); rec(i + 1, acc); acc.pop(); } };
  rec(0, []); return out;
}
// g mit Exponent typografisch (Exponent ≈ 70 % der g-Größe, angehoben), überall gleich
const gsym = (s) => String(s).replace(/g([²³⁴])/g, (m, c) => `<span class="gx">g<sup>${({ "²": 2, "³": 3, "⁴": 4 })[c]}</sup></span>`);
const sup = (o) => (o === 3 ? "³" : o === 4 ? "⁴" : "²");
// Ordnung der Ansicht: g² (corr) = 2, g³ = 3, g⁴ = 4, sonst 0
const gnOrder = () => ({ corr: 2, g3: 3, g4: 4 })[S.view] || 0;
function gnCombo2() {
  const ids = G.ids || [1, 2, 3, 4], pairs = combos(ids, 2).map((c) => c.join(","));
  if (G.combo2.length === 2 && pairs.includes(G.combo2.join(","))) return G.combo2;
  const data = ids.filter((k) => k >= 1);
  return data.length >= 2 ? data.slice(0, 2) : ids.slice(0, 2);
}
function showGnBar() {
  const o = gnOrder();
  $("gnbar").hidden = !o || (o === 2 && !G.head);   // g²: nur wenn der GX-Rechenkern Daten liefert
  return !$("gnbar").hidden;
}
function buildGnBar() {
  const o = gnOrder() || 3, ids = G.ids || [1, 2, 3, 4], cur = (o === 2 ? gnCombo2() : o === 3 ? G.combo3 : G.combo4) || [];
  const sel = $("gnCombo"), list = combos(ids, o), key = o + "|" + ids.join(",") + "|" + cur.join(",");
  if (sel.dataset.k !== key) {
    const all = list.map((c) => c.join(","));
    if (cur.length && !all.includes(cur.join(","))) all.unshift(cur.join(","));
    sel.innerHTML = all.length ? all.map((c) => `<option value="${c}">${c.split(",").map((x) => "K" + x).join("·")}</option>`).join("")
      : `<option>zu wenige Kanäle</option>`;
    sel.disabled = !list.length; sel.value = cur.join(","); sel.dataset.k = key;
  }
  const modes = o === 2 ? [] : o === 3 ? [["map", "Karte"], ["diag", "Diag."], ["t1", "τ₁=0"], ["t2", "τ₂=0"]] : [["slice", "Schnitt τ₃"], ["diag", "Diagonale"]];
  const cm = o === 3 ? G.mode3 : G.mode4, seg = $("gnMode"), mk = o + cm;
  seg.hidden = !modes.length;
  if (seg.dataset.k !== mk) {
    seg.innerHTML = modes.map(([v, t]) => `<button type="button" data-m="${v}" class="${v === cm ? "on" : ""}">${t}</button>`).join("");
    seg.querySelectorAll("button").forEach((b) => b.onclick = () => {
      if (o === 3) G.mode3 = b.dataset.m; else G.mode4 = b.dataset.m;
      try { localStorage.setItem(o === 3 ? "harp.gn3" : "harp.gn4", b.dataset.m); } catch (e) { /* privat */ }
      buildGnBar(); drawGn(); });
    seg.dataset.k = mk;
  }
  const sl4 = o === 4 && G.mode4 === "slice";   // Regler sitzt an Stelle der Messwertzeile (gleiche Höhe)
  $("gnSliderRow").hidden = !sl4; $("readout").hidden = sl4;
}
function gnHint() {
  const h = G.head;
  if (!h) return "Warte auf g³/g⁴-Daten …";
  if (S.view === "g3" && !h.n3) return `Sammelt Daten … noch keine Tripel im Bereich (${h.T_s.toFixed(1)} s) – größeres Fenster/Bereich beschleunigt.`;
  if (S.view === "g4" && !h.n4) return `Sammelt Daten … noch keine Quadrupel im Bereich (${h.T_s.toFixed(1)} s) – größeres Fenster/Bereich beschleunigt.`;
  return "";
}
function viridis(t) {
  const x = Math.min(1, Math.max(0, t)) * (VIRIDIS.length - 1), i = Math.min(VIRIDIS.length - 2, Math.floor(x)), f = x - i;
  return VIRIDIS[i].map((c, k) => Math.round(c + (VIRIDIS[i + 1][k] - c) * f));
}
// Farbskala: logarithmische 1-2-5-Teilung über den sichtbaren Bereich [10^lo, 10^hi], immer mehrere Marken, 1 als Bezug
// Farbskala der g³/g⁴-Karten: höchstens 4 Dekaden unter dem Maximum, sonst der Datenbereich (adaptiv)
let MAP_DECADES = 4;   // let: für Vergleichs-Screenshots umstellbar
const ENGINE_NAME = { rust: "Rust (rayon)", numba: "Numba", numpy: "NumPy" };   // aktiver Rechenkern (Info-Zeile)
function colorTicks(lo, hi, maxN) {
  const pick = (ms) => { const t = []; for (let e = Math.floor(lo) - 1; e <= Math.ceil(hi); e++) for (const m of ms) {
    const v = m * 10 ** e, l = Math.log10(v); if (l >= lo - 1e-9 && l <= hi + 1e-9) t.push(+v.toPrecision(3)); } return t; };
  let t = pick([1, 2, 5]);
  if (t.length > maxN) { t = pick([1]); if (t.length < 3) t = pick([1, 3]); }
  if (t.length < 3) t = pick([1, 1.5, 2, 3, 5, 7]);
  if (t.length < 3) t = pick([1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9]);
  if (t.length < 2) { t = [+(10 ** lo).toPrecision(2), +(10 ** hi).toPrecision(2)]; if (t[0] === t[1]) t = [t[0]]; }
  while (t.length > maxN) {           // ausdünnen, 1 behalten
    const keep = t.filter((v, i) => i % 2 === 0 || v === 1); if (keep.length === t.length) break; t = keep;
  }
  return t;
}
function fmtTick(v) { return v >= 1e4 || v < 0.01 ? v.toExponential(0).replace("e+", "e") : String(+v.toPrecision(2)); }   // kurz: 2e4, 5e-3 (passt rechts neben die Skala)
function niceStep(r) { const p = 10 ** Math.floor(Math.log10(r)), m = r / p; return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p; }
function fmtTau(ns) { return Math.abs(ns) >= 1000 ? +(ns / 1000).toPrecision(3) + "µ" : String(+ns.toPrecision(3)); }
function tauUnit(Rns) { return Rns >= 2000 ? ["µs", 1000] : ["ns", 1]; }
// Heatmap: vals[x*nb+y], x → τ1 (rechts), y → τ2 (oben); symmetrische Ränder (Farbskala rechts = Achse links)
function drawHeat(vals, nb, Rps, xl, yl) {
  // g⁴-Schnitt: der τ₃-Regler sitzt an Stelle der Messwertzeile → Karte so groß wie bei g³
  const cv = $("gnCanvas"), dpr = window.devicePixelRatio || 1, W = plotWidth($("gnPlot")), Hmax = chartHeight();
  const m = mapMargin(W), top = MAP_TOP, bot = MAP_BOT, side = Math.max(60, Math.min(W - 2 * m, Hmax - top - bot));
  const H = side + top + bot;   // quadratische Karte, keine Leerfläche darunter
  cv.style.height = H + "px"; cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const c = cv.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
  const x0 = Math.round((W - side) / 2), y0 = top;
  let mx = -Infinity, mn = Infinity;
  for (const v of vals) if (v > 0) { if (v > mx) mx = v; if (v < mn) mn = v; }
  if (!(mx > 0)) { mx = 10; mn = 0.1; }
  const hi = Math.log10(mx), lo = Math.max(Math.log10(mn), hi - MAP_DECADES), span = Math.max(hi - lo, 1e-6);
  const img = new ImageData(nb, nb);
  for (let x = 0; x < nb; x++) for (let y = 0; y < nb; y++) {
    const v = vals[x * nb + y], p = ((nb - 1 - y) * nb + x) * 4;
    if (v > 0) { const [r, g, b] = viridis((Math.log10(v) - lo) / span); img.data[p] = r; img.data[p + 1] = g; img.data[p + 2] = b; img.data[p + 3] = 255; }
    else { img.data[p] = 11; img.data[p + 1] = 18; img.data[p + 2] = 34; img.data[p + 3] = 255; }
  }
  const off = document.createElement("canvas"); off.width = nb; off.height = nb; off.getContext("2d").putImageData(img, 0, 0);
  c.imageSmoothingEnabled = false; c.drawImage(off, x0, y0, side, side);
  c.strokeStyle = "rgba(148,163,184,0.35)"; c.strokeRect(x0 + 0.5, y0 + 0.5, side - 1, side - 1);
  // Achsen
  const Rns = Rps / 1000, [unit, div] = tauUnit(Rns), st = niceStep(Rns / div / 2.2) * div;
  c.font = AXIS.font; c.fillStyle = AXIS.stroke; c.textAlign = "center"; c.textBaseline = "top";
  for (let t = -Math.floor(Rns / st) * st; t <= Rns + 1e-9; t += st) {
    const px = x0 + (t + Rns) / (2 * Rns) * side, py = y0 + side - (t + Rns) / (2 * Rns) * side;
    c.fillText(fmtTau(t / div).replace("µ", ""), px, y0 + side + 4);
    c.save(); c.textAlign = "right"; c.textBaseline = "middle"; c.fillText(fmtTau(t / div).replace("µ", ""), x0 - 5, py); c.restore();
    c.strokeStyle = "rgba(148,163,184,0.10)"; c.beginPath(); c.moveTo(px, y0); c.lineTo(px, y0 + side); c.moveTo(x0, py); c.lineTo(x0 + side, py); c.stroke();
  }
  c.font = AXIS.labelFont; c.fillText(`${xl} / ${unit}`, x0 + side / 2, y0 + side + 20);
  c.save(); c.translate(x0 - m + 9, y0 + side / 2); c.rotate(-Math.PI / 2); c.textBaseline = "middle"; c.fillText(`${yl} / ${unit}`, 0, 0); c.restore();
  // Farbskala (rechter Rand)
  const bx = x0 + side + 7, bw = 8;
  for (let i = 0; i < side; i++) { const [r, g, b] = viridis(1 - i / side); c.fillStyle = `rgb(${r},${g},${b})`; c.fillRect(bx, y0 + i, bw, 1.5); }
  c.font = AXIS.font; c.fillStyle = AXIS.stroke; c.textAlign = "left"; c.textBaseline = "middle";
  const ticks = colorTicks(lo, hi, Math.max(3, Math.floor(side / 18)));
  let lastY = Infinity;
  for (const v of ticks) {
    const y = y0 + side - (Math.log10(v) - lo) / span * side, ref = v === 1;
    if (!ref && Math.abs(lastY - y) < 12) continue;
    c.fillStyle = ref ? "#e2e8f0" : AXIS.stroke; c.fillRect(bx - 2, y - 0.5, bw + 4, ref ? 1.5 : 1);
    c.font = ref ? "600 " + AXIS.font : AXIS.font;
    c.fillText(fmtTick(v), bx + bw + 4, Math.min(y0 + side - 5, Math.max(y0 + 5, y)));
    lastY = y;
  }
  c.font = AXIS.font;
  G.ticks = ticks;
  G.geom = { x0, y0, side, nb, Rps, vals };
}
function gnPick(e) {
  const g = G.geom; if (!g) return;
  const r = $("gnCanvas").getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
  const x = Math.floor((px - g.x0) / g.side * g.nb), y = Math.floor((g.y0 + g.side - py) / g.side * g.nb);
  if (x < 0 || y < 0 || x >= g.nb || y >= g.nb) return;
  const bw = 2 * g.Rps / g.nb, t1 = ((x + 0.5) * bw - g.Rps) / 1000, t2 = ((y + 0.5) * bw - g.Rps) / 1000, v = g.vals[x * g.nb + y];
  $("readout").dataset.auto = "0";
  $("readout").innerHTML = `<b>τ₁ = ${t1.toFixed(2)} ns · τ₂ = ${t2.toFixed(2)} ns</b> · g = ${v > 0 ? v.toPrecision(3) : "–"}`;
  if ($("readout").hidden) drawGnTiles();     // g⁴-Schnitt: Messwert erscheint in der Hinweiszeile
}
function drawCut(xs, ys, xlab, key) {
  const el = $("gnCut");
  if (!G.cut || G.cutKey !== key) {
    el.innerHTML = ""; G.cutKey = key;
    const ysz = chartBox().clientWidth < 500 ? 34 : 40;
    G.cut = new uPlot({ width: plotWidth($("gnPlot")), height: chartHeight(), pxAlign: false, padding: [8, ysz, 0, 0],
      legend: { show: false }, cursor: { points: { size: 7 } },
      series: [{}, { stroke: "#38bdf8", width: 1.8, points: { show: true, size: 3 }, spanGaps: false }],
      scales: { x: { time: false, range: (u, mn, mx) => [Math.min(mn, -mx), Math.max(mx, -mn)] }, y: { distr: 3, log: 10,
        range: (u, mn, mx) => [10 ** Math.floor(Math.log10(mn > 0 ? mn : 0.1)), 10 ** Math.ceil(Math.log10(mx > 0 ? mx * 1.3 : 10))] } },
      axes: [{ ...AXIS, label: xlab, labelSize: 16, labelGap: 0, size: 30, gap: 3, values: (u, sp) => sp.map((v) => String(+v.toFixed(2))) },
             { ...AXIS, size: ysz, gap: 3, values: (u, sp) => sp.map(pow10Label) }],
      hooks: { setCursor: [(u) => { const i = u.cursor.idx; if (i != null && u.data[1][i] != null && ($("readout").dataset.auto = "0"))
        $("readout").innerHTML = `<b>τ = ${u.data[0][i].toFixed(2)} ns</b> · g = ${u.data[1][i].toPrecision(3)}`; }] } }, [[]], el);
  }
  G.cut.setData([xs, ys.map((v) => (v > 0 ? v : null))]);
}
function drawGn() {
  const h = G.head, v3 = S.view === "g3";
  updateHint(); drawGnTiles();
  if (!h) return;
  const o = v3 ? 3 : 4, cmb = v3 ? h.combo3 : h.combo4, K = (i) => "K" + cmb[i];
  const R = v3 ? h.range_ps : h.range4_ps, d = v3 ? G.map3 : G.cube4;
  const mode = v3 ? G.mode3 : G.mode4, showMap = v3 ? mode === "map" : mode === "slice";
  $("gnCanvas").hidden = !showMap; $("gnCut").hidden = showMap;
  if (!d) return;
  const nb = d.nb, bw = 2 * R / nb, tau = (i) => ((i + 0.5) * bw - R) / 1000, i0 = Math.floor(nb / 2);
  const xl1 = `τ₁ = t(${K(1)})−t(${K(0)})`, xl2 = `τ₂ = t(${K(2)})−t(${K(0)})`;
  if (v3) {
    if (mode === "map") { drawHeat(d.v, nb, R, "τ₁", "τ₂"); }
    else {
      const xs = [], ys = [];
      for (let i = 0; i < nb; i++) { xs.push(tau(i)); ys.push(mode === "diag" ? d.v[i * nb + i] : mode === "t1" ? d.v[i0 * nb + i] : d.v[i * nb + i0]); }
      drawCut(xs, ys, mode === "diag" ? "τ₁ = τ₂ / ns" : mode === "t1" ? xl2.split(" =")[0] + " / ns (τ₁ = 0)" : xl1.split(" =")[0] + " / ns (τ₂ = 0)", "3" + mode);
    }
  } else {
    const sl = $("gnTau3");
    if (+sl.max !== nb - 1) { sl.max = String(nb - 1); }
    if (G.tau3 == null || G.tau3 >= nb) G.tau3 = i0;
    sl.value = String(G.tau3);
    $("gnTau3v").textContent = `${tau(G.tau3).toFixed(2)} ns`;
    if (mode === "slice") {
      const sv = new Float32Array(nb * nb), z = G.tau3;
      for (let x = 0; x < nb; x++) for (let y = 0; y < nb; y++) sv[x * nb + y] = d.v[(x * nb + y) * nb + z];
      drawHeat(sv, nb, R, "τ₁", "τ₂");
    } else {
      const xs = [], ys = [];
      for (let i = 0; i < nb; i++) { xs.push(tau(i)); ys.push(d.v[(i * nb + i) * nb + i]); }
      drawCut(xs, ys, "τ₁ = τ₂ = τ₃ / ns", "4diag");
    }
  }
  if ($("readout").dataset.auto !== "0") $("readout").innerHTML = gnReadout(h, o);
}
// Messwertzeile „Tripel … · T · Bin …“ bzw. „Quadrupel … · T · Bin …“ (g³-Zeile; in g⁴ zusätzlich neben der großen Kachel)
function gnReadout(h, o) {
  const R = o === 3 ? h.range_ps : h.range4_ps, d = o === 3 ? G.map3 : G.cube4;
  const bin = d && d.nb ? ` · Bin ${fmtWidth(2 * R / d.nb)}` : "";
  return `${o === 3 ? "Tripel" : "Quadrupel"} ${fmtCompact(o === 3 ? h.n3 : h.n4)} · ${h.T_s.toFixed(1)} s${bin}`;
}
function drawGnTiles() {
  const h = G.head, o = gnOrder() || 3, big = $("gnBig");
  const zero = o === 2 ? "0" : o === 3 ? "0,0" : "0,0,0";
  big.querySelector(".k").innerHTML = `<span class="gx">g<sup>${o}</sup></span>(${zero})`;
  if (!h) { big.querySelector(".v").textContent = "–"; big.querySelector(".e").textContent = ""; $("gnList").innerHTML = ""; $("gnNotes").innerHTML = ""; return; }
  const cmb = (o === 2 ? gnCombo2() : o === 3 ? h.combo3 : h.combo4).slice().sort((a, b) => a - b).join(",");
  const lab = (t) => (t.kind === "g2h" ? `<span class="gx">g<sup>2</sup><sub>h</sub></span> K${t.ch[0]}|K${t.ch[1]}K${t.ch[2]}` : `K${t.ch.join("K")}`);
  const fmtG = (g) => (g == null ? "–" : g >= 1e6 ? g.toExponential(2).replace("e+", "e") : g >= 100 ? g.toFixed(0) : g >= 10 ? g.toFixed(1) : g.toFixed(g < 0.1 ? 3 : 2));
  const isLow = (t) => t.low || t.g == null;
  const mine = h.tiles.filter((t) => t.ch.length === o && t.kind !== "g2h");
  const cur = mine.find((t) => t.ch.join(",") === cmb);
  const low = cur && isLow(cur);
  big.classList.toggle("low", !!low);
  big.querySelector(".v").textContent = !cur ? "–" : low ? "sammelt Daten …" : fmtG(cur.g);
  big.querySelector(".e").textContent = !cur ? "" : low ? `n ${fmtCompact(cur.n)} von ≥ 10 · ${h.T_s.toFixed(1)} s` : `± ${cur.err != null ? fmtG(cur.err) : "–"} · n ${fmtCompact(cur.n)}`;
  big.title = h.period_ps > 0 ? "Seitenpeak-normiert (gepulst)" : "auf Zufallskoinzidenzen normiert (Dauerstrich)";
  const her = o <= 3 ? h.tiles.filter((t) => t.kind === "g2h") : [];
  // Ausnahme g⁴: die Messwertzeile unter der Karte weicht dem τ₃-Regler → dieselbe Zeile wie in g³ im freien Platz neben der Kachel
  const cnt = o === 4 ? `<div class="cnt" title="Quadrupel im Bereich (gesamt) · Messzeit · Binbreite">${gnReadout(h, 4)}</div>` : "";
  $("gnList").classList.toggle("wide", o === 4 && her.length + mine.length <= 2);   // wenige g⁴-Kacheln: volle Breite, große Zahlen passen
  $("gnList").innerHTML = [...her, ...mine].map((t) =>
    `<div class="${t.ch.join(",") === cmb && t.kind !== "g2h" ? "cur" : ""}${t.kind === "g2h" ? " her" : ""}" title="n = ${t.n}">${lab(t)} <b>${isLow(t) ? `… n ${fmtCompact(t.n)}` : fmtG(t.g)}</b></div>`).join("") + cnt;
  const norm = h.period_ps > 0 ? "Seitenpeak-normiert" : "auf Zufallskoinzidenzen normiert";
  const notes = [`Fenster ${fmtWidth(h.win_ps)} · ${norm} · ${h.T_s.toFixed(1)} s`];
  if (o === 4 && $("readout").hidden && $("readout").dataset.auto === "0") notes.unshift($("readout").innerHTML + ".");   // angetippter Messwert
  if (her.length) notes.push(`<span class="gx">g<sup>2</sup><sub>h</sub></span>: mit K0 als Herald.`);
  const c = calNote(h); if (c) notes.push(gsym(c));
  $("gnNotes").innerHTML = notes.map((x) => `<span>${x}</span>`).join(" ");
}
function calNote(h) {
  const n = [], g = h.geo;
  if (g && g.changed) n.push(g.basis === "g2-Breite"
    ? `Fenster ${fmtWidth(g.win_ps)} / Bereich ±${fmtWidth(g.range_ps)} automatisch aus der g²-Breite (FWHM ${fmtWidth(g.fwhm_ps)}).`
    : `Fenster ${fmtWidth(g.win_ps)} / Bereich ±${fmtWidth(g.range_ps)} nach Statistik gewählt (kein Merkmal im g²).`);
  const c = calText(h);
  if (c) n.push(c);
  return n.join(" ");
}
function calText(h) {
  if (h.cal_status === "unnoetig") return "Laufzeiten vernachlässigbar (g² viel breiter als der Kabelversatz).";
  if (h.cal_status === "kein_merkmal") return "Keine Laufzeit-Kalibrierung möglich (kein Merkmal im g²) – ohne Offsets gerechnet.";
  if (h.cal_status === "teilweise") return `Kalibrierung unvollständig: ohne Offset für ${h.cal_missing.map((k) => "K" + k).join(", ")}.`;
  if (h.cal_status === "läuft") return "Laufzeit-Kalibrierung läuft (2 s Messzeit) …";
  return "";
}

let resizeT = 0;
function onResize(delay) {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => {
    const w = plotWidth(chartBox()), h = chartHeight();
    for (const p of Object.values(S.lp)) if (p.u) p.u.setSize({ width: w, height: h });
    if (S.trace) S.trace.setSize({ width: w, height: h });
    if (G.cut) G.cut.setSize({ width: w, height: h });
    if (S.view === "g3" || S.view === "g4") drawGn();
  }, typeof delay === "number" ? delay : 80);
}
window.addEventListener("resize", () => onResize());
window.addEventListener("orientationchange", () => onResize());
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost"))
  navigator.serviceWorker.register("/sw.js").catch(() => {});
bindControls(); setView(S.view); connect();
