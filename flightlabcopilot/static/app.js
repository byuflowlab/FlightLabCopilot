"use strict";
// FlightLab Copilot front end. The server pushes a full state snapshot on every
// GPS fix (5 Hz) over /api/stream; this file only draws it and sends user actions.

const $ = (id) => document.getElementById(id);
const R_EARTH = 6371000.0;
const rad = (d) => (d * Math.PI) / 180;
const wrap180 = (a) => { a = ((a + 180) % 360 + 360) % 360; return a - 180; };
const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const compass = (deg) => COMPASS[Math.round(deg / 45) % 8];
const fmtM = (m) => (m == null ? "—" : Math.abs(m) >= 100 ? `${m.toFixed(0)} m` : `${m.toFixed(1)} m`);
const signed = (v) => { const t = Math.abs(v) < 0.05 ? "0.0" : Math.abs(v).toFixed(1); return (v <= -0.05 ? "−" : "+") + t; };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let S = null;                 // latest snapshot
let connected = false;
let lostSince = null;            // when the live stream dropped
let lastEventId = null;
let trail = [];
let lastFixTime = null;
let arrowAngle = 0;
let tableKey = "";

// ------------------------------------------------------------------ server I/O
async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const r = await fetch(url, opts);
  let data = {};
  try { data = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
  return data;
}

async function start() {
  const full = await api("GET", "/api/state");
  trail = full.trail || [];
  lastEventId = full.events.length ? full.events[full.events.length - 1].id : 0;
  onState(full);
  connect();
  setInterval(() => S && renderStatus(), 250);   // ages and staleness tick even without data
}

function connect() {
  const es = new EventSource("/api/stream");
  es.onopen = () => { connected = true; lostSince = null; };
  es.onmessage = (m) => { connected = true; lostSince = null; onState(JSON.parse(m.data)); };
  es.onerror = () => { if (connected || lostSince == null) lostSince = Date.now(); connected = false; };   // EventSource retries by itself
}

function onState(s) {
  const prev = S;
  S = s;
  if (s.gps && s.gps.received !== lastFixTime) {
    lastFixTime = s.gps.received;
    if (s.local && prev) {
      trail.push([s.local.e, s.local.n]);
      const max = (s.settings.trail_seconds || 120) * 5;
      if (trail.length > max) trail.splice(0, trail.length - max);
    }
  }
  for (const ev of s.events) {
    if (lastEventId !== null && ev.id > lastEventId) handleEvent(ev);
  }
  if (s.events.length) lastEventId = Math.max(lastEventId || 0, s.events[s.events.length - 1].id);
  document.documentElement.dataset.theme = s.settings.theme;
  $("btn-theme").textContent = s.settings.theme === "night" ? "Day" : "Night";
  render();
}

function handleEvent(ev) {
  if (ev.kind === "reached") { flash(`✓ ${ev.text.split(" (")[0].toUpperCase()}`); chime(); }
  else if (ev.kind === "finished") { setTimeout(() => flash("COURSE COMPLETE"), 1800); }
  else if (ev.kind === "restart" || ev.kind === "clear") { trail = []; }
}

let flashTimer = null;
function flash(text) {
  const f = $("flash");
  f.textContent = text;
  f.classList.remove("hidden");
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => f.classList.add("hidden"), 1600);
}

// ------------------------------------------------------------------ sound
let audio = null;
function audioReady() { return audio && audio.state === "running"; }
function unlockAudio() {
  try {
    if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state !== "running") audio.resume().then(() => S && renderStatus());
  } catch (_) { /* no audio available */ }
}
document.addEventListener("pointerdown", unlockAudio, { capture: true });

function chime() {
  if (!S || !S.settings.chime || !audioReady()) return;
  const t0 = audio.currentTime;
  [[880, 0], [1320, 0.16], [1760, 0.32]].forEach(([f, dt]) => {
    const o = audio.createOscillator();
    const g = audio.createGain();
    o.type = "sine";
    o.frequency.value = f;
    g.gain.setValueAtTime(0.0001, t0 + dt);
    g.gain.exponentialRampToValueAtTime(0.5, t0 + dt + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + 0.28);
    o.connect(g).connect(audio.destination);
    o.start(t0 + dt);
    o.stop(t0 + dt + 0.3);
  });
}

// ------------------------------------------------------------------ rendering
function gpsAge() {
  if (!S || !S.gps) return null;
  return Date.now() / 1000 - S.gps.received;
}

function render() {
  renderStatus();
  renderGuide();
  renderTable();
  drawMap();
}

function setChip(id, text, cls) {
  const el = $(id);
  el.textContent = text;
  el.className = "chip" + (cls ? " " + cls : "") + (el.tagName === "BUTTON" ? " chip-btn" : "");
}

function renderStatus() {
  const g = S.gps;
  const age = gpsAge();
  const stale = age == null || age > S.settings.stale_after;
  if (!g) setChip("chip-gps", "GPS: no data", "bad");
  else if (!g.fix) setChip("chip-gps", `GPS: no fix · ${g.sats} sats`, "bad");
  else {
    const hd = g.hdop != null ? ` · HDOP ${g.hdop.toFixed(1)}` : "";
    const rate = g.rate ? ` · ${g.rate.toFixed(1)} Hz` : "";
    const cls = stale ? "bad" : g.hdop != null && g.hdop > 2 ? "warn" : "good";
    setChip("chip-gps", `GPS ${g.sats} sats${hd}${rate}${stale ? ` · ${age.toFixed(0)} s old` : ""}`, cls);
  }
  setChip("chip-source", S.source.kind === "none" ? "No GPS source" : S.source.status, S.source.kind === "none" ? "warn" : "");
  const h = S.home;
  if (h.setting) setChip("chip-home", `Setting start point ${h.samples}/${h.needed}…`, "warn");
  else if (h.set) setChip("chip-home", `Start point set ${new Date(h.set_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`, "good");
  else setChip("chip-home", "No start point", "warn");

  const rec = S.recording;
  const rb = $("btn-record");
  if (rec.active) {
    const t = Math.max(0, Date.now() / 1000 - rec.started);
    const mmss = `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
    setChip("chip-rec", `● REC ${mmss}`, "rec");
    $("chip-rec").title = `Recording to ${rec.file}`;
    rb.textContent = "■ Stop";
    rb.className = "record-stop";
    rb.title = `Stop recording (${rec.file})`;
  } else {
    $("chip-rec").className = "chip rec hidden";
    rb.textContent = "● Record";
    rb.className = "record-start";
    rb.title = "Start writing every GPS fix and event to a new CSV";
  }
  const n = S.history.length;
  $("history-note").textContent = n ? `${n} recording${n > 1 ? "s" : ""}` : "no recordings";
  $("btn-download").disabled = n === 0;

  if (!audioReady()) setChip("chip-sound", "🔇 Click to enable chime", "warn");
  else setChip("chip-sound", S.settings.chime ? "🔔 Chime on" : "🔕 Chime off", "");

  // banner: the single most important problem
  const b = $("banner");
  let text = "", cls = "";
  const bd = S.boundary;
  if (!connected && lostSince != null && Date.now() - lostSince > 2000) { text = "Lost connection to the app. Is the terminal window still open?"; cls = "bad"; }
  else if (bd && bd.status === "out" && !stale) { text = "OUT OF BOUNDS — RETURN NOW"; cls = "bad"; }
  else if (S.source.kind === "none") { text = "No GPS source. Click GPS source to connect the radio."; cls = "info"; }
  else if (!g) { text = "Waiting for GPS data…"; cls = "warn"; }
  else if (stale) { text = `NO GPS DATA FOR ${age.toFixed(0)} s`; cls = "bad"; }
  else if (!g.fix) { text = "No GPS fix. Needs open sky; can take a minute."; cls = "warn"; }
  else if (bd && bd.status === "warn") { text = "Close to boundary — ready the pilot"; cls = "warn"; }
  else if (h.setting) { text = `Setting start point — hold still (${h.samples}/${h.needed})`; cls = "warn"; }
  b.textContent = text;
  b.className = "banner" + (text ? " " + cls : " hidden");
  $("guide").classList.toggle("stale", stale);
}

function initDial() {
  const g = $("dial-ticks");
  let s = "";
  for (let a = 0; a < 360; a += 30) {
    const r1 = a % 90 === 0 ? 122 : 130;
    const x1 = Math.sin(rad(a)) * r1, y1 = -Math.cos(rad(a)) * r1;
    const x2 = Math.sin(rad(a)) * 140, y2 = -Math.cos(rad(a)) * 140;
    s += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
  }
  g.innerHTML = s;
  g.classList.add("dial-ticks");
}

function setArrow(deg, cls) {
  arrowAngle += wrap180(deg - arrowAngle);   // shortest way round, no spin past ±180
  const a = $("arrow");
  a.style.transform = `rotate(${arrowAngle}deg)`;
  a.setAttribute("class", "arrow " + cls);
}

function renderGuide() {
  const i = S.active;
  const wps = S.course.waypoints;
  const st = S.steer;
  const g = S.gps;
  if (!wps.length) { $("wp-index").textContent = "No waypoints"; $("wp-name").textContent = "open Course to add some"; }
  else if (i == null) { $("wp-index").textContent = "Course complete"; $("wp-name").textContent = ""; }
  else { $("wp-index").textContent = `WP ${i + 1} of ${wps.length}`; $("wp-name").textContent = wps[i].name; }

  const turn = $("turn-text"), sub = $("turn-sub");
  $("dial-north").classList.remove("show");
  if (!st) {
    turn.className = "turn-text";
    turn.textContent = i == null ? "—" : !g || !g.fix ? "NO GPS" : !S.home.set ? "NO START" : "—";
    sub.textContent = !S.home.set && g && g.fix ? "Set the start point on the ground first" : "";
    setArrow(0, "none");
  } else if (st.relative == null) {
    turn.className = "turn-text";
    turn.textContent = `${compass(st.bearing)} ${st.bearing.toFixed(0)}°`;
    sub.textContent = "Too slow for a ground track: arrow points to the waypoint from north";
    $("dial-north").classList.add("show");
    setArrow(st.bearing, "");
  } else {
    const cls = st.turn === "AHEAD" ? "ahead" : "turn";
    turn.className = "turn-text " + cls;
    turn.textContent = st.turn === "AHEAD" ? "AHEAD" : `${st.turn} ${Math.abs(st.relative).toFixed(0)}°`;
    sub.textContent = `Waypoint bears ${st.bearing.toFixed(0)}° ${compass(st.bearing)} · track ${g.course.toFixed(0)}°`;
    setArrow(st.relative, cls);
  }

  // tiles
  if (st) {
    $("t-dist").textContent = fmtM(st.distance_h);
    $("t-dist-sub").textContent = `3-D ${fmtM(st.distance_3d)}` + (st.time_to_go != null ? ` · ${st.time_to_go.toFixed(0)} s to go` : "");
    const v = st.vertical;
    $("t-alt").textContent = v === "HOLD" ? "HOLD" : `${v === "CLIMB" ? "↑" : "↓"} ${Math.abs(st.climb).toFixed(1)} m`;
    $("tile-alt").classList.toggle("good", v === "HOLD");
    $("t-alt-sub").textContent = `${v === "HOLD" ? "on target" : v.toLowerCase()} · now ${S.local.u.toFixed(1)} m, target ${wps[i].alt.toFixed(1)} m`;
  } else {
    ["t-dist", "t-alt"].forEach((id) => ($(id).textContent = "—"));
    ["t-dist-sub", "t-alt-sub"].forEach((id) => ($(id).textContent = ""));
    $("tile-alt").classList.remove("good");
  }
  const c = i != null ? S.run.waypoints[i].closest : null;
  $("t-close").textContent = c ? fmtM(c.distance) : "—";
  $("t-close-sub").textContent = c ? `horiz ${c.horizontal.toFixed(1)} · vert ${signed(c.vertical)} m` : "";

  const parts = [];
  if (g && g.fix) parts.push(`Speed <b>${g.speed.toFixed(1)} m/s</b>`, `Track <b>${g.course.toFixed(0)}°</b>`);
  if (S.local && S.local.u != null) parts.push(`Height above start <b>${S.local.u.toFixed(1)} m</b>`);
  if (S.boundary) parts.push(`Boundary <b>${{ ok: "inside", warn: "near edge", out: "OUTSIDE" }[S.boundary.status]}</b>`);
  $("small-row").innerHTML = parts.map((p) => `<span>${p}</span>`).join("");
  const sameRadii = S.course.radius_h === S.course.radius_v;
  $("bubble-note").textContent = sameRadii ? `Bubble: ${S.course.radius_h} m sphere` : `Bubble: ${S.course.radius_h} m radius, ±${S.course.radius_v} m height`;
}

function renderTable() {
  const key = JSON.stringify([S.course.waypoints, S.run.waypoints.map((e) => [e.status, e.how, e.closest && e.closest.distance.toFixed(1)]), S.active]);
  if (key !== tableKey) {
    tableKey = key;
    const rows = S.course.waypoints.map((w, i) => {
      const e = S.run.waypoints[i];
      const active = i === S.active;
      let badge = '<span class="badge">pending</span>';
      if (active) badge = '<span class="badge active">ACTIVE</span>';
      else if (e.status === "done") badge = `<span class="badge done">✓ ${e.how === "manual" ? "by hand" : "reached"}</span>`;
      else if (e.status === "skipped") badge = '<span class="badge skipped">skipped</span>';
      const c = e.closest ? `${fmtM(e.closest.distance)} <span class="muted">(h ${e.closest.horizontal.toFixed(1)}, v ${signed(e.closest.vertical)})</span>` : "—";
      const acts = e.status === "pending"
        ? `<button data-i="${i}" data-s="done" title="Count this waypoint as reached">✓ Complete</button> <button data-i="${i}" data-s="skipped">Skip</button>`
        : `<button data-i="${i}" data-s="pending" title="Make this waypoint pending again">Undo</button>`;
      return `<tr class="${active ? "active" : ""}"><td>${i + 1}</td><td>${esc(w.name)}</td><td>${w.alt.toFixed(1)}</td><td>${badge}</td><td>${c}</td><td class="acts">${acts}</td></tr>`;
    });
    $("wp-body").innerHTML = rows.join("") || '<tr><td colspan="6" class="muted">No waypoints yet. Click Course to add them.</td></tr>';
  }
  const evs = S.events.slice(-4).reverse().map((e) => `<div>${new Date(e.at * 1000).toLocaleTimeString()} — ${esc(e.text)}</div>`);
  $("event-log").innerHTML = evs.join("");
}

$("wp-body").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button[data-i]");
  if (!b) return;
  try { await api("POST", `/api/waypoint/${b.dataset.i}`, { status: b.dataset.s }); }
  catch (e) { alert(e.message); }
});

// ------------------------------------------------------------------ map
const tileImages = new Map();
function getImage(src) {
  let img = tileImages.get(src);
  if (!img) {
    img = new Image();
    img.onload = () => drawMap();
    img.src = src;
    tileImages.set(src, img);
  }
  return img.complete && img.naturalWidth ? img : null;
}

function toLocal(lat, lon) {
  const [lat0, lon0] = S.origin;
  return [R_EARTH * Math.cos(rad(lat0)) * rad(lon - lon0), R_EARTH * rad(lat - lat0)];
}

function ellipsePoints(b, scale) {
  const [cx, cy] = toLocal(b.center_lat, b.center_lon);
  const th = rad(b.rotation_deg), ct = Math.cos(th), st = Math.sin(th);
  const pts = [];
  for (let k = 0; k <= 72; k++) {
    const phi = (2 * Math.PI * k) / 72;
    const a = b.semi_east * scale * Math.cos(phi), c = b.semi_north * scale * Math.sin(phi);
    pts.push([cx + a * ct + c * st, cy + a * st - c * ct]);
  }
  return pts;
}

function drawMap() {
  if (!S) return;
  const kind = S.settings.map.kind;
  $("layout").classList.toggle("no-map", kind === "off");
  if (kind === "off") return;
  const cv = $("map");
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const css = getComputedStyle(document.documentElement);
  const col = (n) => css.getPropertyValue(n).trim();
  ctx.fillStyle = col("--map-bg");
  ctx.fillRect(0, 0, W, H);

  // view: fit boundary, waypoints and aircraft
  const b = S.course.boundary;
  let pts = S.wp_local.map((p) => [p[0], p[1]]);
  if (b.enabled) pts = pts.concat(ellipsePoints(b, 1));
  if (S.local) pts.push([S.local.e, S.local.n]);
  if (!pts.length) pts = [[-100, -100], [100, 100]];
  let x0 = Math.min(...pts.map((p) => p[0])), x1 = Math.max(...pts.map((p) => p[0]));
  let y0 = Math.min(...pts.map((p) => p[1])), y1 = Math.max(...pts.map((p) => p[1]));
  const span = Math.max(x1 - x0, y1 - y0, 40);
  const pad = 24;
  const sc = Math.min((W - 2 * pad) / Math.max(x1 - x0, span * 0.3), (H - 2 * pad) / Math.max(y1 - y0, span * 0.3));
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const X = (e) => W / 2 + (e - cx) * sc;
  const Y = (n) => H / 2 - (n - cy) * sc;

  // background
  const m = S.settings.map;
  $("map-attr").textContent = kind === "tiles" ? m.attribution || "" : "";
  const placeImage = (src, north, south, west, east) => {
    const img = getImage(src);
    if (!img) return;
    const [ew, nn] = toLocal(north, west), [ee, ns] = toLocal(south, east);
    ctx.drawImage(img, X(ew), Y(nn), X(ee) - X(ew), Y(ns) - Y(nn));
  };
  if (kind === "image" && m.image) placeImage(`/map/${encodeURIComponent(m.image.file)}`, m.image.north, m.image.south, m.image.west, m.image.east);
  else if (kind === "tiles" && m.tiles) {
    ctx.imageSmoothingEnabled = true;
    for (const t of m.tiles) placeImage(`/map/tiles/${encodeURIComponent(t.file)}`, t.north, t.south, t.west, t.east);
  } else {
    const step = span > 400 ? 100 : span > 150 ? 50 : 20;
    ctx.strokeStyle = col("--map-grid");
    ctx.lineWidth = 1;
    ctx.beginPath();
    const ex0 = cx - W / 2 / sc, ex1 = cx + W / 2 / sc, ny0 = cy - H / 2 / sc, ny1 = cy + H / 2 / sc;
    for (let e = Math.ceil(ex0 / step) * step; e < ex1; e += step) { ctx.moveTo(X(e), 0); ctx.lineTo(X(e), H); }
    for (let n = Math.ceil(ny0 / step) * step; n < ny1; n += step) { ctx.moveTo(0, Y(n)); ctx.lineTo(W, Y(n)); }
    ctx.stroke();
  }
  const onImage = kind === "image" || kind === "tiles";
  const ink = onImage ? "#ffffff" : col("--text");

  // boundary
  const poly = (p, close) => { ctx.beginPath(); p.forEach(([e, n], k) => (k ? ctx.lineTo(X(e), Y(n)) : ctx.moveTo(X(e), Y(n)))); if (close) ctx.closePath(); };
  if (b.enabled) {
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = col("--bad");
    ctx.setLineDash([]);
    poly(ellipsePoints(b, 1), true); ctx.stroke();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = col("--warn");
    ctx.setLineDash([6, 5]);
    poly(ellipsePoints(b, Math.sqrt(b.warn_at)), true); ctx.stroke();
    ctx.setLineDash([]);
  }

  // trail
  if (trail.length > 1) {
    ctx.strokeStyle = onImage ? "rgba(108,180,255,0.9)" : col("--info");
    ctx.lineWidth = 2;
    poly(trail, false); ctx.stroke();
  }

  // line to the active waypoint
  if (S.local && S.active != null) {
    const w = S.wp_local[S.active];
    ctx.strokeStyle = col("--turn");
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(X(S.local.e), Y(S.local.n)); ctx.lineTo(X(w[0]), Y(w[1])); ctx.stroke();
    ctx.setLineDash([]);
  }

  // waypoints
  ctx.font = "bold 13px -apple-system, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  S.wp_local.forEach((p, k) => {
    const e = S.run.waypoints[k];
    const x = X(p[0]), y = Y(p[1]);
    const rTrue = S.course.radius_h * sc;
    const r = Math.max(rTrue, 9);
    // pending: light blue with white text, readable on satellite imagery too
    let fill = "#5aa9e6", stroke = "#1f6fae", text = "#fff";
    if (e.status === "done") { fill = col("--good-bg"); stroke = col("--good"); text = col("--good"); }
    if (k === S.active) { fill = col("--warn-bg"); stroke = col("--turn"); text = col("--text"); }
    if (e.status === "skipped") stroke = col("--arrow-idle");
    ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fillStyle = fill; ctx.fill();
    ctx.lineWidth = k === S.active ? 3 : 2; ctx.strokeStyle = stroke; ctx.stroke();
    ctx.fillStyle = text;
    ctx.fillText(String(k + 1), x, y + 0.5);
  });

  // start point
  if (S.home.set && S.home.lat != null) {
    const [he, hn] = toLocal(S.home.lat, S.home.lon);
    ctx.strokeStyle = ink; ctx.lineWidth = 2;
    ctx.strokeRect(X(he) - 6, Y(hn) - 6, 12, 12);
    ctx.fillStyle = ink; ctx.font = "bold 10px sans-serif"; ctx.fillText("S", X(he), Y(hn) + 0.5);
  }

  // aircraft
  if (S.local && S.gps && S.gps.fix) {
    const x = X(S.local.e), y = Y(S.local.n);
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = col("--info");
    ctx.strokeStyle = onImage ? "#000" : col("--bg");
    ctx.lineWidth = 2;
    if (S.gps.speed >= S.settings.min_speed) {
      ctx.rotate(rad(S.gps.course));
      ctx.beginPath(); ctx.moveTo(0, -13); ctx.lineTo(9, 10); ctx.lineTo(0, 5); ctx.lineTo(-9, 10); ctx.closePath();
    } else {
      ctx.beginPath(); ctx.arc(0, 0, 7, 0, 2 * Math.PI);
    }
    ctx.stroke(); ctx.fill();
    ctx.restore();
  }

  // north arrow and scale bar
  ctx.fillStyle = ink; ctx.strokeStyle = ink; ctx.lineWidth = 2;
  ctx.font = "bold 13px sans-serif";
  ctx.fillText("N", W - 18, 16);
  ctx.beginPath(); ctx.moveTo(W - 18, 26); ctx.lineTo(W - 23, 38); ctx.lineTo(W - 13, 38); ctx.closePath(); ctx.fill();
  const nice = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000];
  const len = nice.find((v) => v * sc > 70) || 1000;
  ctx.beginPath(); ctx.moveTo(12, H - 14); ctx.lineTo(12 + len * sc, H - 14); ctx.stroke();
  ctx.textAlign = "left"; ctx.font = "12px sans-serif";
  ctx.fillText(`${len} m`, 12, H - 26);
}
new ResizeObserver(() => drawMap()).observe($("map-wrap"));

// ------------------------------------------------------------------ top bar actions
$("chip-sound").onclick = async () => {
  if (!audioReady()) { unlockAudio(); return; }
  await api("POST", "/api/settings", { chime: !S.settings.chime });
  if (!S.settings.chime) setTimeout(chime, 100);
};
$("btn-theme").onclick = () => api("POST", "/api/settings", { theme: S.settings.theme === "night" ? "day" : "night" });
$("btn-home").onclick = async () => {
  if (confirm("Take the next 2 s of GPS as the start point?\nAll altitudes are measured from it, so the aircraft should be on the ground and still.")) {
    await api("POST", "/api/home");
  }
};
$("btn-restart").onclick = async () => {
  if (confirm("Restart the run? All waypoints go back to pending and closest approaches are cleared. (The log keeps everything.)")) {
    await api("POST", "/api/run/restart");
  }
};
$("btn-record").onclick = async () => {
  try { await api("POST", "/api/record", { action: S.recording.active ? "stop" : "start" }); }
  catch (e) { alert(e.message); }
};
$("btn-download").onclick = () => { window.location.href = "/api/history/download"; };
$("btn-clear").onclick = async () => {
  const n = S.history.length - (S.recording.active ? 1 : 0);
  const what = n > 0 ? `This deletes ${n} recording${n > 1 ? "s" : ""} from this computer and clears the map track and event list.\nDownload the history first if you need it.` : "This clears the map track and event list.";
  if (!confirm(`Clear history?\n\n${what}` + (S.recording.active ? "\n\nThe recording in progress is kept." : ""))) return;
  try { await api("POST", "/api/history/clear"); trail = []; }
  catch (e) { alert(e.message); }
};
$("btn-exit").onclick = async () => {
  const msg = S.recording.active ? "Stop FlightLab Copilot? The recording will be stopped and saved." : "Stop FlightLab Copilot?";
  if (!confirm(msg)) return;
  try { await api("POST", "/api/exit"); } catch (_) { /* server is going away */ }
  document.body.innerHTML = '<p style="padding:40px;font-size:22px">FlightLab Copilot has stopped. You can close this tab.</p>';
};

// ------------------------------------------------------------------ course dialog
let draft = null;
function openCourse() {
  draft = JSON.parse(JSON.stringify(S.course));
  fillCourseForm();
  $("c-error").textContent = "";
  $("dlg-course").showModal();
}
function fillCourseForm() {
  $("c-name").value = draft.name;
  $("c-rh").value = draft.radius_h;
  $("c-rv").value = draft.radius_v;
  const b = draft.boundary;
  $("b-on").checked = b.enabled;
  $("b-lat").value = b.center_lat; $("b-lon").value = b.center_lon;
  $("b-se").value = b.semi_east; $("b-sn").value = b.semi_north;
  $("b-rot").value = b.rotation_deg; $("b-warn").value = b.warn_at;
  renderCourseRows();
}
function renderCourseRows() {
  $("c-rows").innerHTML = draft.waypoints.map((w, i) => `
    <tr data-i="${i}">
      <td class="num">${i + 1}</td>
      <td><input data-k="name" value="${esc(w.name)}"></td>
      <td><input data-k="lat" inputmode="decimal" value="${w.lat}"></td>
      <td><input data-k="lon" inputmode="decimal" value="${w.lon}"></td>
      <td><input data-k="alt" inputmode="decimal" value="${w.alt}" style="width:6em"></td>
      <td class="acts"><button type="button" data-a="up" title="Move up">↑</button><button type="button" data-a="down" title="Move down">↓</button><button type="button" data-a="del" title="Delete">✕</button></td>
    </tr>`).join("") || '<tr><td colspan="6" class="muted">No waypoints.</td></tr>';
}
function readCourseForm() {
  draft.name = $("c-name").value;
  draft.radius_h = $("c-rh").value;
  draft.radius_v = $("c-rv").value;
  Object.assign(draft.boundary, {
    enabled: $("b-on").checked,
    center_lat: $("b-lat").value, center_lon: $("b-lon").value,
    semi_east: $("b-se").value, semi_north: $("b-sn").value,
    rotation_deg: $("b-rot").value, warn_at: $("b-warn").value,
  });
}
$("c-rows").addEventListener("input", (ev) => {
  const tr = ev.target.closest("tr[data-i]");
  if (tr && ev.target.dataset.k) draft.waypoints[+tr.dataset.i][ev.target.dataset.k] = ev.target.value;
});
$("c-rows").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-a]");
  if (!btn) return;
  const i = +btn.closest("tr").dataset.i;
  const w = draft.waypoints;
  if (btn.dataset.a === "del") w.splice(i, 1);
  if (btn.dataset.a === "up" && i > 0) [w[i - 1], w[i]] = [w[i], w[i - 1]];
  if (btn.dataset.a === "down" && i < w.length - 1) [w[i + 1], w[i]] = [w[i], w[i + 1]];
  renderCourseRows();
});
$("c-add").onclick = () => {
  const last = draft.waypoints[draft.waypoints.length - 1];
  draft.waypoints.push({ name: `WP ${draft.waypoints.length + 1}`, lat: last ? last.lat : "", lon: last ? last.lon : "", alt: last ? last.alt : 15 });
  renderCourseRows();
};
$("c-add-here").onclick = () => {
  if (!S.gps || !S.gps.fix) { $("c-error").textContent = "No GPS fix to take the position from."; return; }
  const u = S.local && S.local.u != null ? Math.round(S.local.u * 10) / 10 : 0;
  draft.waypoints.push({ name: `WP ${draft.waypoints.length + 1}`, lat: S.gps.lat, lon: S.gps.lon, alt: u });
  renderCourseRows();
};
$("c-paste-apply").onclick = () => {
  const out = [];
  const lines = $("c-paste").value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  for (const [k, line] of lines.entries()) {
    const f = line.split(/[,\t;]+|\s+(?=-?\d)/).map((s) => s.trim()).filter((s) => s !== "");
    if (f.length === 3) out.push({ name: `WP ${k + 1}`, lat: f[0], lon: f[1], alt: f[2] });
    else if (f.length >= 4) out.push({ name: f[0], lat: f[1], lon: f[2], alt: f[3] });
    else { $("c-error").textContent = `Line ${k + 1} needs lat, lon, alt: "${line}"`; return; }
  }
  draft.waypoints = out;
  $("c-error").textContent = "";
  renderCourseRows();
};
$("c-import").onchange = async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  try {
    const c = JSON.parse(await f.text());
    draft = Object.assign(JSON.parse(JSON.stringify(S.course)), c);
    fillCourseForm();
    $("c-error").textContent = "Imported. Check it and click Save.";
  } catch (e) { $("c-error").textContent = `Could not read ${f.name}: ${e.message}`; }
  ev.target.value = "";
};
$("c-save").onclick = async () => {
  readCourseForm();
  try { await api("PUT", "/api/course", draft); $("dlg-course").close(); }
  catch (e) { $("c-error").textContent = e.message; }
};
$("btn-course").onclick = openCourse;

// ------------------------------------------------------------------ source dialog
async function loadPorts() {
  const ports = await api("GET", "/api/ports");
  const sel = $("s-port");
  const saved = S.settings.source.port;
  sel.innerHTML = ports.map((p) => `<option value="${esc(p.device)}" ${p.device === saved ? "selected" : ""}>${esc(p.device)}${p.likely ? "" : " (unlikely)"}${p.description && p.description !== "n/a" ? " — " + esc(p.description) : ""}</option>`).join("")
    || "<option value=''>No serial ports found. Is the radio plugged in?</option>";
  $("s-baud").value = S.settings.source.baudrate || 57600;
}
async function sourceAction(fn) {
  $("s-error").textContent = "";
  try { await fn(); $("dlg-source").close(); } catch (e) { $("s-error").textContent = e.message; }
}
$("btn-source").onclick = () => { $("s-error").textContent = ""; loadPorts(); $("dlg-source").showModal(); };
$("s-refresh").onclick = loadPorts;
$("s-connect").onclick = () => sourceAction(() => api("POST", "/api/source", { kind: "serial", port: $("s-port").value, baudrate: +$("s-baud").value }));
$("sim-start").onclick = () => sourceAction(() => api("POST", "/api/source", { kind: "sim" }));
$("s-stop").onclick = () => sourceAction(() => api("POST", "/api/source", { kind: "none" }));
$("r-start").onclick = () => sourceAction(() => {
  const f = $("r-file").files[0];
  if (!f) throw new Error("Choose a CSV file first.");
  const fd = new FormData();
  fd.append("file", f);
  fd.append("speed", $("r-speed").value);
  return api("POST", "/api/source/replay", fd);
});

// ------------------------------------------------------------------ map dialog
function openMap() {
  const m = S.settings.map;
  document.querySelectorAll('input[name="m-kind"]').forEach((r) => (r.checked = r.value === m.kind));
  if (m.image) { $("i-n").value = m.image.north; $("i-s").value = m.image.south; $("i-w").value = m.image.west; $("i-e").value = m.image.east; }
  $("m-error").textContent = "";
  estimateTiles();
  $("dlg-map").showModal();
}
async function estimateTiles() {
  try {
    const r = await api("GET", `/api/map/estimate?zoom=${$("d-zoom").value}`);
    $("d-estimate").textContent = `${r.tiles} tiles` + (r.tiles > r.limit ? ` (over the ${r.limit} limit)` : "");
  } catch (e) { $("d-estimate").textContent = ""; }
}
document.querySelectorAll('input[name="m-kind"]').forEach((r) => (r.onchange = async () => {
  const m = S.settings.map;
  if (r.value === "image" && !m.image) { $("m-error").textContent = "Upload a picture below first."; return; }
  if (r.value === "tiles" && !m.tiles) { $("m-error").textContent = "Download imagery below first."; return; }
  $("m-error").textContent = "";
  await api("POST", "/api/settings", { map: { ...m, kind: r.value } });
}));
$("d-zoom").onchange = estimateTiles;
$("i-upload").onclick = async () => {
  const f = $("i-file").files[0];
  if (!f) { $("m-error").textContent = "Choose a picture first."; return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("north", $("i-n").value); fd.append("south", $("i-s").value);
  fd.append("west", $("i-w").value); fd.append("east", $("i-e").value);
  try { await api("POST", "/api/map/image", fd); tileImages.clear(); $("dlg-map").close(); }
  catch (e) { $("m-error").textContent = e.message; }
};
$("d-start").onclick = async () => {
  $("m-error").textContent = "";
  try { await api("POST", "/api/map/download", { zoom: +$("d-zoom").value }); }
  catch (e) { $("m-error").textContent = e.message; }
};
setInterval(() => {
  if (!S || !$("dlg-map").open) return;
  const j = S.map_job;
  $("d-progress").textContent = !j ? "" : j.error ? j.error : j.running ? `Downloading ${j.done} / ${j.total}…` : `Done: ${j.total} tiles saved.`;
}, 300);
$("btn-map").onclick = openMap;

initDial();
start().catch((e) => { document.body.innerHTML = `<p style="padding:40px">Could not reach the app: ${esc(e.message)}</p>`; });
