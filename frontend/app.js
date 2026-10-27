/* Touchline broadcast studio. Consumes the SSE stream from the API and renders
   the pitch, scorebug, telemetry, persona views and the agent feed. */
const $ = (id) => document.getElementById(id);
const PITCH_W = 105, PITCH_H = 68;

const PHRASES = {
  en: { goal: "IT'S IN! {p} scores for {t}!", shot: "{p} lets fly!", save: "Big save!", corner: "Corner to {t}.", tackle: "Crunching challenge, {t} win it back.", intercept: "Read beautifully, interception!", foul: "Free kick conceded." },
  es: { goal: "¡GOL! ¡{p} marca para {t}!", shot: "¡{p} dispara!", save: "¡Gran parada!", corner: "Cóner para {t}.", tackle: "¡Entrada dura, {t} lo recupera!", intercept: "¡Intercepción leída a la perfección!", foul: "Tiro libre concedido." },
  fr: { goal: "BUT ! {p} marque pour {t} !", shot: "{p} frappe !", save: "Grand arrêt !", corner: "Corner pour {t}.", tackle: "Tacle rugueux, {t} récupère !", intercept: "Interception superbe !", foul: "Coup franc concédé." },
  de: { goal: "TOR! {p} trifft für {t}!", shot: "{p} schließt ab!", save: "Starke Parade!", corner: "Ecke für {t}.", tackle: "Hartes Tackle, {t} holt sich den Ball!", intercept: "Perfekt gelesen, Abfangen!", foul: "Freistoß vergeben." },
  ar: { goal: "هدف! {p} يسجل لـ{t}!", shot: "{p} يسدد!", save: "تصدٍ رائع!", corner: "ركلة ركنية لـ{t}.", tackle: "تدخل قوي، {t} يستعيد الكرة!", intercept: "قراءة ممتازة، اعتراض!", foul: "ركلة حرة." },
  hi: { goal: "गोल! {p} ने {t} के लिए गोल किया!", shot: "{p} ने शॉट लिया!", save: "शानदार सेव!", corner: "{t} के लिए कॉर्नर।", tackle: "कड़ा टैकल, {t} ने बॉल वापस लिया!", intercept: "शानदार इंटरसेप्ट!", foul: "फ्री किक दी गई।" },
};

let meta = null, mode = "analyst", lang = "en", lastInsight = null;
const playerTally = {};

function fmtClock(t) {
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  const mm = t > 45 * 60 + 300 ? Math.min(90, Math.floor((t - 300) / 60)) : Math.min(45, Math.floor(t / 60));
  return String(mm).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}

function drawPitch() {
  const c = $("pitch"), ctx = c.getContext("2d");
  const W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = "#2e4a3a"; ctx.lineWidth = 2;
  ctx.strokeRect(10, 10, W - 20, H - 20);
  ctx.beginPath(); ctx.moveTo(W / 2, 10); ctx.lineTo(W / 2, H - 10); ctx.stroke();
  ctx.beginPath(); ctx.arc(W / 2, H / 2, 40, 0, Math.PI * 2); ctx.stroke();
  const box = (x) => ctx.strokeRect(x, H / 2 - 70, 70, 140);
  box(10); box(W - 80);
}

function toXY(p) {
  const c = $("pitch");
  return { x: 10 + (p.x / PITCH_W) * (c.width - 20), y: 10 + (p.y / PITCH_H) * (c.height - 20) };
}

function markEvent(ev, color) {
  const c = $("pitch"), ctx = c.getContext("2d");
  drawPitch();
  const a = toXY(ev.from);
  if (ev.to) {
    const b = toXY(ev.to);
    ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.setLineDash(ev.type === "pass" ? [6, 4] : []);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(b.x, b.y, 4, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
  }
  ctx.beginPath(); ctx.arc(a.x, a.y, 5, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
}

function colorOf(short) {
  if (!meta) return "#ccc";
  return short === meta.home.short ? meta.home.color : meta.away.color;
}

function renderMeta(m) {
  meta = m;
  $("hName").textContent = m.home.name; $("aName").textContent = m.away.name;
  $("hMeta").textContent = "home"; $("aMeta").textContent = "away";
  $("hBadge").style.background = m.home.color; $("aBadge").style.background = m.away.color;
  $("th").textContent = m.home.short; $("ta").textContent = m.away.short;
  const sel = $("playerPick");
  sel.innerHTML = "";
  for (const side of ["home", "away"]) {
    const g = document.createElement("optgroup"); g.label = m[side].name;
    for (let i = 1; i <= 11; i++) {
      const o = document.createElement("option");
      o.value = m[side].short + " " + String(i).padStart(2, "0");
      o.textContent = m[side].short + " " + String(i).padStart(2, "0") + " (" + ["GK","DF","DF","DF","DF","MF","MF","MF","FW","FW","FW"][i-1] + ")";
      g.appendChild(o);
    }
    sel.appendChild(g);
  }
}

function renderMetrics(m, ev) {
  const h = meta.home.short, a = meta.away.short;
  $("score").textContent = m.score[h] + " : " + m.score[a];
  $("clock").textContent = fmtClock(ev.t);
  if (m.xg) { $("hxg").textContent = m.xg[h].toFixed(2); $("axg").textContent = m.xg[a].toFixed(2); }
  if (m.possession) { $("hposs").textContent = m.possession[h] + "%"; $("aposs").textContent = m.possession[a] + "%"; }
  if (m.ppda) {
    $("hppda").textContent = (m.ppda[h] === null ? "–" : m.ppda[h]); $("appda").textContent = (m.ppda[a] === null ? "–" : m.ppda[a]);
  }
  if (m.control) {
    $("hci").textContent = m.control[h]; $("aci").textContent = m.control[a];
    $("chaosFill").style.width = m.control[h] + "%";
  }
}

function ticker(ins) {
  const el = $("commentary");
  const pick = ins.find((i) => i.kind === "commentary") || ins[0];
  if (pick) {
    el.textContent = pick.text;
    el.dir = lang === "ar" ? "rtl" : "ltr";
  }
}

function addFeed(ins) {
  if (!ins || !ins.length) return;
  const feed = $("feed");
  for (const i of ins.slice().reverse()) {
    const d = document.createElement("div");
    d.className = "line";
    d.innerHTML = '<span class="who">' + i.agent.replace("_", " ") + "</span>" + i.text +
      ' <span class="evidence">[event #' + i.evidence.join(", #") + "]</span>";
    feed.prepend(d);
  }
  while (feed.children.length > 40) feed.lastChild.remove();
}

function addWhyCard(ev, ins) {
  const tac = ins.find((i) => i.kind === "tactical" || i.kind === "recap");
  if (!tac) return;
  const box = $("whyCards");
  const d = document.createElement("div");
  d.className = "card";
  d.textContent = tac.text;
  box.prepend(d);
  while (box.children.length > 6) box.lastChild.remove();
}

function trackPlayer(ev) {
  if (!ev.player) return;
  const key = ev.player.slice(0, 7);
  playerTally[key] = playerTally[key] || { touches: 0, last: "" };
  playerTally[key].touches++;
  playerTally[key].last = ev.type;
  const pick = $("playerPick").value.slice(0, 7);
  if (key === pick) {
    const box = $("playerStats");
    box.innerHTML = "";
    const d = document.createElement("div");
    d.className = "card";
    d.textContent = "Touches so far: " + playerTally[key].touches + " · latest: " + ev.type.replace("_", " ");
    box.appendChild(d);
  }
}

function applyMode() {
  document.querySelectorAll(".panels").forEach((p) => p.classList.add("hidden"));
  document.querySelector(".panels." + mode).classList.remove("hidden");
}

document.querySelectorAll("#personas button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("#personas button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    mode = b.dataset.p; applyMode();
  }));
$("lang").addEventListener("change", (e) => { lang = e.target.value; });
$("recapClose").addEventListener("click", () => $("recapModal").classList.add("hidden"));

/* ---- tick rendering shared by live and replay modes ---- */
function onTick(d) {
  renderMetrics(d.metrics, d.event);
  markEvent(d.event, colorOf(d.event.team));
  ticker(d.insights);
  addFeed(d.insights);
  addWhyCard(d.event, d.insights);
  trackPlayer(d.event);
  if (d.event.type === "goal") {
    $("recapTitle").textContent = "Goal at " + fmtClock(d.event.t);
    $("recapBody").textContent = (d.insights.find((i) => i.kind === "recap") || {}).text ||
      "Goal for " + d.event.team + ".";
    $("recapModal").classList.remove("hidden");
  }
}

function onSummary(s) {
  const h = meta.home.short, a = meta.away.short;
  $("hshots").textContent = s.shots[h] + " (" + s.shots_on_target[h] + ")";
  $("ashots").textContent = s.shots[a] + " (" + s.shots_on_target[a] + ")";
  $("hacc").textContent = s.pass_accuracy[h] + "%";
  $("aacc").textContent = s.pass_accuracy[a] + "%";
  $("recapTitle").textContent = "Full-time recap";
  $("recapBody").textContent = s.score[h] + " : " + s.score[a] +
    " · xG " + s.xg[h] + " v " + s.xg[a] +
    " · possession " + s.possession[h] + "% v " + s.possession[a] + "%";
  $("recapModal").classList.remove("hidden");
  $("kickoff").disabled = false;
}

/* ---- live mode: SSE from the FastAPI backend ---- */
let es = null;

async function startLive(seed, speed) {
  const res = await fetch("/api/match/new", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ seed: Number(seed) }),
  });
  if (!res.ok) throw new Error("api unavailable");
  const data = await res.json();
  renderMeta(data.meta);
  resetFeeds();
  if (es) es.close();
  es = new EventSource("/api/match/" + data.id + "/stream?speed=" + speed);
  es.onmessage = (msg) => {
    const d = JSON.parse(msg.data);
    if (d.kind === "meta") renderMeta(d.meta);
    else if (d.kind === "tick") onTick(d);
    else if (d.kind === "summary") onSummary(d.summary);
  };
}

/* ---- replay mode: precomputed demo/match.json (static hosting friendly) ---- */
let replayTimer = null;

async function startReplay(speed) {
  const res = await fetch("demo/match.json");
  if (!res.ok) throw new Error("no demo data");
  const data = await res.json();
  renderMeta(data.meta);
  resetFeeds();
  const interval = Math.max(16, Math.round(1000 / Number(speed)));
  let i = 0;
  if (replayTimer) clearInterval(replayTimer);
  replayTimer = setInterval(() => {
    if (i >= data.ticks.length) {
      clearInterval(replayTimer);
      onSummary(data.summary);
      return;
    }
    onTick(data.ticks[i]);
    i++;
  }, interval);
}

function resetFeeds() {
  $("feed").innerHTML = ""; $("whyCards").innerHTML = ""; $("score").textContent = "0 : 0";
  $("kickoff").disabled = true;
}

$("kickoff").addEventListener("click", async () => {
  drawPitch();
  const seed = $("seed").value || 7, speed = $("speed").value;
  try {
    await startLive(seed, speed);
  } catch (e) {
    await startReplay(speed);
  }
});

drawPitch();
