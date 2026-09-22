/* Basis · Trainings-Dashboard — Rendering & Coach-Logik */

const WEEKDAYS_SHORT = { "Montag": "Mo", "Dienstag": "Di", "Mittwoch": "Mi", "Donnerstag": "Do", "Freitag": "Fr", "Samstag": "Sa", "Sonntag": "So" };
const MONTH_NAMES = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
const TYPE_ICON = { lauf: "🏃", rad: "🚴", kraft: "🏋", core: "◆", emom: "⏱", sonstiges: "•" };
const OVERRIDES_KEY = "basisOverrides_v2";

let APP_DATA = null;

/* ---------- utils ---------- */

function fmtDateLong(iso) {
  const d = new Date(iso + "T00:00:00");
  const weekday = Object.keys(WEEKDAYS_SHORT)[(d.getDay() + 6) % 7];
  return `${weekday}, ${d.getDate()}. ${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`;
}
function fmtDateShort(iso) {
  const d = new Date(iso + "T00:00:00");
  return `${String(d.getDate()).padStart(2,"0")}.${String(d.getMonth()+1).padStart(2,"0")}.`;
}
function fmtMin(min) {
  if (min === null || min === undefined || Number.isNaN(min)) return "–";
  if (min >= 60) {
    const h = Math.floor(min / 60), m = Math.round(min % 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  return `${Math.round(min)} min`;
}
function fmtPace(secPerKm) {
  if (secPerKm === null || secPerKm === undefined || Number.isNaN(secPerKm)) return "–";
  const m = Math.floor(secPerKm / 60), s = Math.round(secPerKm % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function fmtDuration(totalSec) {
  if (totalSec === null || totalSec === undefined || Number.isNaN(totalSec)) return "–";
  const h = Math.floor(totalSec / 3600), m = Math.floor((totalSec % 3600) / 60), s = Math.round(totalSec % 60);
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
function fmtVal(v, unit = "") { return (v === null || v === undefined || Number.isNaN(v)) ? "–" : `${v}${unit}`; }
function escapeHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function canEdit() {
  return typeof CURRENT_ROLE === "undefined" || CURRENT_ROLE !== "viewer";
}
function statusDotHtml(dateStr, u) {
  if (!canEdit()) return `<span class="status-dot ${u.status}"></span>`;
  return `<span class="status-dot ${u.status} clickable" data-toggle-date="${dateStr}" data-toggle-unit="${escapeHtml(u.name)}"></span>`;
}

function computeRecoveryScore(sleep) {
  const parts = [];
  if (typeof sleep.sleepScore === "number") parts.push({ value: sleep.sleepScore, weight: 0.4 });
  if (typeof sleep.bodyBattery === "number") parts.push({ value: sleep.bodyBattery, weight: 0.35 });
  if (typeof sleep.hrv === "number" && typeof sleep.hrvBaseline === "number" && sleep.hrvBaseline > 0) {
    parts.push({ value: Math.min(150, (sleep.hrv / sleep.hrvBaseline) * 100), weight: 0.25 });
  }
  if (!parts.length) return null;
  const totalWeight = parts.reduce((s, p) => s + p.weight, 0);
  return Math.round(parts.reduce((s, p) => s + p.value * p.weight, 0) / totalWeight);
}

/* ---------- manual overrides (Abhaken + Tagesnotiz + Verschieben) ----------
   Werden lokal gecacht (sofortige Reaktion, funktioniert auch offline) UND
   verschluesselt zum Server gepusht, damit alle Geraete/Personen dieselben
   Aenderungen sehen statt nur der Browser, auf dem sie gemacht wurden. */

let CACHED_OVERRIDES = null;
let overridesPushTimer = null;

function loadOverrides() {
  if (CACHED_OVERRIDES) return CACHED_OVERRIDES;
  try { return JSON.parse(localStorage.getItem(OVERRIDES_KEY) || "{}"); }
  catch { return {}; }
}
function saveOverrides(o) {
  CACHED_OVERRIDES = o;
  try { localStorage.setItem(OVERRIDES_KEY, JSON.stringify(o)); } catch { /* ignore */ }
  clearTimeout(overridesPushTimer);
  overridesPushTimer = setTimeout(() => pushOverridesToServer(o), 1500);
}

async function initOverridesFromServer() {
  if (typeof IS_HOSTED === "undefined" || !IS_HOSTED || typeof CURRENT_DEK === "undefined" || !CURRENT_DEK) return;
  try {
    const encFile = await fetch(`${RAW_DATA_BASE}/data/overrides.enc.json`, { cache: "no-store" }).then(r => r.json());
    CACHED_OVERRIDES = await decryptDataFile(CURRENT_DEK, encFile);
  } catch {
    // Datei existiert evtl. noch nicht (erste Nutzung) oder Abruf fehlgeschlagen -
    // dann mit dem lokalen Stand weitermachen, bis der naechste Push klappt.
    try { CACHED_OVERRIDES = JSON.parse(localStorage.getItem(OVERRIDES_KEY) || "{}"); }
    catch { CACHED_OVERRIDES = {}; }
  }
}

async function pushOverridesToServer(overrides) {
  if (typeof IS_HOSTED === "undefined" || !IS_HOSTED || typeof CURRENT_DEK === "undefined" || !CURRENT_DEK) return;
  if (!canEdit()) return;
  try {
    const encrypted = await encryptJson(CURRENT_DEK, overrides);
    await fetch(HOSTED_SYNC_WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "save-overrides", payload: encrypted }),
    });
  } catch { /* naechste Aenderung versucht es erneut */ }
}
const STATUS_CYCLE = { planned: "done", done: "skipped", skipped: "planned" };

function setUnitOverride(date, unitName, status) {
  const overrides = loadOverrides();
  const day = overrides[date] || { units: {}, note: "" };
  day.units[unitName] = status;
  overrides[date] = day;
  saveOverrides(overrides);
}
function setNoteOverride(date, text) {
  const overrides = loadOverrides();
  const day = overrides[date] || { units: {}, note: "" };
  day.note = text;
  overrides[date] = day;
  saveOverrides(overrides);
}
function applyOverrides(data) {
  const overrides = loadOverrides();
  const applyTo = (units, dateStr) => {
    const day = overrides[dateStr];
    if (!day || !day.units) return;
    units.forEach(u => {
      if (Object.prototype.hasOwnProperty.call(day.units, u.name)) {
        u.status = day.units[u.name];
      }
    });
  };
  applyTo(data.today.units, data.today.date);
  data.week.days.forEach(d => applyTo(d.units, d.date));
  data.today.note = (overrides[data.today.date] && overrides[data.today.date].note) || "";
}

/* ---------- manuelles Verschieben einer Einheit auf einen anderen Wochentag ---------- */

function setMoveOverride(weekStart, homeWeekday, unitName, targetDate) {
  const overrides = loadOverrides();
  overrides.__moves = overrides.__moves || {};
  const key = `${weekStart}|${homeWeekday}|${unitName}`;
  if (targetDate === null) delete overrides.__moves[key];
  else overrides.__moves[key] = targetDate;
  saveOverrides(overrides);
}

/* ---------- verworfene Tausch-Vorschläge bei Anfragen (persistiert, sonst
   taucht der Vorschlag beim naechsten Neu-Rendern/Reload wieder auf) ---------- */

function setSwapDismissed(issueNumber) {
  const overrides = loadOverrides();
  overrides.__dismissedSwaps = overrides.__dismissedSwaps || {};
  overrides.__dismissedSwaps[issueNumber] = true;
  saveOverrides(overrides);
}
function isSwapDismissed(issueNumber) {
  const overrides = loadOverrides();
  return !!(overrides.__dismissedSwaps && overrides.__dismissedSwaps[issueNumber]);
}

function applyMoves(data) {
  const overrides = loadOverrides();
  const moves = overrides.__moves || {};
  const weekStart = data.week.startDate;
  const dayByWeekday = {};
  data.week.days.forEach(d => {
    dayByWeekday[d.weekday] = d;
    d.units.forEach(u => { u.homeWeekday = d.weekday; });
  });
  Object.entries(moves).forEach(([key, targetDate]) => {
    const [wk, homeWeekday, unitName] = key.split("|");
    if (wk !== weekStart) return;
    const homeDay = dayByWeekday[homeWeekday];
    const targetDay = data.week.days.find(d => d.date === targetDate);
    if (!homeDay || !targetDay || homeDay.date === targetDate) return;
    const idx = homeDay.units.findIndex(u => u.name === unitName);
    if (idx === -1) return;
    const [unit] = homeDay.units.splice(idx, 1);
    unit.movedFromWeekday = homeWeekday;
    targetDay.units.push(unit);
  });
  const todayDay = data.week.days.find(d => d.date === data.today.date);
  if (todayDay) data.today.units = todayDay.units;
}

function moveSelectHtml(u, currentDate, weekDays, weekStart) {
  if (!canEdit()) return "";
  const options = weekDays.map(d =>
    `<option value="${d.date}" ${d.date === currentDate ? "selected" : ""}>${WEEKDAYS_SHORT[d.weekday]}</option>`
  ).join("");
  return `<select class="move-select" data-week-start="${weekStart}" data-home-weekday="${u.homeWeekday}" data-move-unit="${escapeHtml(u.name)}" title="Einheit auf anderen Tag verschieben">${options}</select>`;
}

function autoMoveButtonHtml(u) {
  if (!canEdit()) return "";
  return `<button class="btn-small auto-move-btn" type="button" style="padding:6px 9px; font-size:12px;"
    data-auto-weekday="${u.homeWeekday}" data-auto-unit="${escapeHtml(u.name)}"
    title="Automatisch auf einen sinnvollen Tag verschieben – oder streichen, falls keiner passt">🪄</button>`;
}

function showToast(html, ms = 7000) {
  const panel = document.getElementById("sync-panel");
  if (!panel) return;
  panel.innerHTML = html;
  panel.hidden = false;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => { panel.hidden = true; }, ms);
}

/**
 * Sucht regelbasiert den sinnvollsten verbleibenden Tag dieser Woche fuer eine
 * Einheit: Schluesseltage bleiben tabu, Tage mit bereits gleicher Pflicht-Sportart
 * (z. B. schon ein Pflicht-Lauf/-Rad) werden vermieden, sonst gewinnt der Tag mit
 * der geringsten bestehenden Last. Findet sich nichts Sinnvolles, wird die
 * Einheit stattdessen als "abgelehnt" markiert statt sie irgendwo reinzuquetschen.
 */
function autoRescheduleUnit(homeWeekday, unitName) {
  if (!APP_DATA) return;
  const data = APP_DATA;
  const weekStart = data.week.startDate;
  const todayDate = data.today.date;

  let currentDay = null, unit = null;
  data.week.days.forEach(d => {
    const found = d.units.find(u => u.name === unitName && u.homeWeekday === homeWeekday);
    if (found) { currentDay = d; unit = found; }
  });
  if (!unit || !currentDay) return;

  const candidates = data.week.days.filter(d => d.date >= todayDate && d.date !== currentDay.date);
  let best = null, bestScore = Infinity;
  candidates.forEach(d => {
    if (d.units.some(u => u.keySession)) return;
    let score = d.units.length;
    if (d.units.some(u => u.type === unit.type && u.tag === "pflicht")) score += 10;
    if (score < bestScore) { bestScore = score; best = d; }
  });

  if (!best || bestScore >= 10) {
    setUnitOverride(currentDay.date, unitName, "skipped");
    showToast(`<div class="title">Kein guter Tag gefunden</div><div>An den restlichen Tagen ist schon eine Pflicht-Einheit vom gleichen Typ geplant – „${escapeHtml(unitName)}" wurde für diese Woche als abgelehnt markiert, statt sie irgendwo reinzuquetschen.</div>`);
  } else {
    setMoveOverride(weekStart, homeWeekday, unitName, best.date);
    showToast(`<div class="title">Automatisch verschoben</div><div>„${escapeHtml(unitName)}" → ${best.weekday} (${fmtDateShort(best.date)}) – dort war im Vergleich am wenigsten los.</div>`);
  }
  renderAll();
}

/* ---------- progress bar system ---------- */

function progressBar({ name, value, target, unit = "", decimals = 0, variant = "" }) {
  const pct = target > 0 ? (value / target) * 100 : 0;
  const widthPct = clamp(pct, 0, 100);
  const cls = pct > 100 ? "over" : variant;
  const valTxt = `${value.toFixed(decimals)}${unit}`;
  const targetTxt = `${target.toFixed(decimals)}${unit}`;
  return `
    <div class="bar-block">
      <div class="bar-top"><span class="name">${name}</span><span class="value">${valTxt} <span style="color:var(--muted);font-weight:600;">/ ${targetTxt}</span></span></div>
      <div class="bar-track"><div class="bar-fill ${cls}" style="width:${widthPct}%"></div></div>
    </div>`;
}

function miniBar(value, target, variant = "") {
  const pct = target > 0 ? clamp((value / target) * 100, 0, 100) : 0;
  const cls = (target > 0 && value / target > 1) ? "over" : variant;
  return `<div class="bar-track bar-mini-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>`;
}

/* ---------- recovery ring ---------- */

let ringCounter = 0;
function recoveryRing(pct, valueLabel, sublabel) {
  ringCounter++;
  const gid = `ring-grad-${ringCounter}`;
  const r = 40, c = 2 * Math.PI * r;
  const offset = c * (1 - clamp(pct, 0, 100) / 100);
  let stops;
  if (pct >= 70) stops = ["#2f7dc4", "#2fd6a0"];
  else if (pct >= 45) stops = ["#1d3a5f", "#5bc4f0"];
  else stops = ["#3a2712", "#f2a13c"];
  return `
    <div class="ring-wrap">
      <svg viewBox="0 0 96 96" width="96" height="96">
        <defs><linearGradient id="${gid}" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="${stops[0]}"/><stop offset="100%" stop-color="${stops[1]}"/>
        </linearGradient></defs>
        <circle class="ring-track" cx="48" cy="48" r="${r}"></circle>
        <circle class="ring-fill" cx="48" cy="48" r="${r}" stroke="url(#${gid})"
          stroke-dasharray="${c}" stroke-dashoffset="${offset}"></circle>
      </svg>
      <div class="ring-label"><span class="val">${valueLabel}</span><span class="lbl">${sublabel}</span></div>
    </div>`;
}

/* ---------- line charts (no external lib) ---------- */

function lineChartSVG(points, opts = {}) {
  const w = 640, h = opts.compact ? 70 : 200;
  if (!points || points.length === 0) {
    return opts.compact ? `<svg class="chart-svg" viewBox="0 0 ${w} ${h}"></svg>`
      : `<svg class="chart-svg" viewBox="0 0 ${w} ${h}"><text class="chart-axis-label" x="${w/2}" y="${h/2}" text-anchor="middle">noch keine Daten</text></svg>`;
  }
  const padL = opts.compact ? 2 : 40, padR = opts.compact ? 2 : 14;
  const padT = opts.compact ? 4 : 16, padB = opts.compact ? 4 : 26;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const values = points.map(p => p.value);
  let min = Math.min(...values), max = Math.max(...values);
  if (min === max) { min -= 1; max += 1; }
  const pad = (max - min) * 0.15;
  min -= pad; max += pad;
  const xStep = points.length > 1 ? innerW / (points.length - 1) : 0;

  const xy = points.map((p, i) => {
    const x = padL + i * xStep;
    const t = (p.value - min) / (max - min);
    const y = opts.invert ? padT + t * innerH : padT + innerH - t * innerH;
    return { x, y, label: p.label, value: p.value };
  });

  const pathD = xy.map((p, i) => (i === 0 ? "M" : "L") + p.x.toFixed(1) + "," + p.y.toFixed(1)).join(" ");
  const gid = "area-grad-" + Math.random().toString(36).slice(2, 8);
  const areaD = `${pathD} L${xy[xy.length - 1].x.toFixed(1)},${padT + innerH} L${xy[0].x.toFixed(1)},${padT + innerH} Z`;

  let gridLines = "", xLabels = "";
  if (!opts.compact) {
    gridLines = [0, 0.5, 1].map(f => {
      const y = padT + innerH * f;
      return `<line class="chart-grid-line" x1="${padL}" x2="${w - padR}" y1="${y}" y2="${y}"/>`;
    }).join("");
    const step = Math.max(1, Math.ceil(points.length / 6));
    xLabels = xy.filter((_, i) => i % step === 0 || i === xy.length - 1)
      .map(p => `<text class="chart-axis-label" x="${p.x}" y="${h - 8}" text-anchor="middle">${p.label}</text>`).join("");
  }
  const dots = xy.map(p => `<circle class="chart-dot" cx="${p.x}" cy="${p.y}" r="${opts.compact ? 2 : 3.2}"></circle>`).join("");

  return `<svg class="chart-svg" viewBox="0 0 ${w} ${h}">
      <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#5bc4f0" stop-opacity="0.35"/>
        <stop offset="100%" stop-color="#5bc4f0" stop-opacity="0"/>
      </linearGradient></defs>
      ${gridLines}
      <path d="${areaD}" fill="url(#${gid})" stroke="none"></path>
      <path class="chart-line" d="${pathD}"></path>
      ${opts.compact ? "" : dots}
      ${xLabels}
    </svg>`;
}

/* ---------- gestapeltes Wochenplan-Balkendiagramm (Woche-Tab) ---------- */

function weekPlanBarsSVG(weeks) {
  const w = 640, h = 130;
  const padL = 28, padR = 10, padT = 8, padB = 18;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const totals = weeks.map(wk => wk.runHours + wk.bikeHours + wk.strengthHours);
  const maxTotal = Math.max(...totals, 1) * 1.15;
  const slot = innerW / weeks.length;
  const barWidth = Math.max(1.5, Math.min(20, slot * 0.65));
  const scale = innerH / maxTotal;
  const monthOf = (label) => (label || "").split(".")[1];
  const monthShort = (mm) => MONTH_NAMES[parseInt(mm, 10) - 1]?.slice(0, 3) || "";

  const gridCount = 4;
  const gridLines = Array.from({ length: gridCount + 1 }, (_, i) => {
    const frac = i / gridCount;
    const y = padT + innerH * (1 - frac);
    const val = Math.round(maxTotal * frac);
    return `<line class="chart-grid-line" x1="${padL}" x2="${w - padR}" y1="${y}" y2="${y}"/>` +
      `<text class="chart-axis-label" x="${padL - 6}" y="${y + 3}" text-anchor="end">${val}h</text>`;
  }).join("");

  const bars = weeks.map((wk, i) => {
    const x = padL + i * slot + (slot - barWidth) / 2;
    const segs = [
      { val: wk.runHours, color: "var(--sky-400)" },
      { val: wk.bikeHours, color: "var(--ocean-600)" },
      { val: wk.strengthHours, color: "var(--teal)" },
    ];
    let yCursor = padT + innerH;
    const rects = segs.filter(s => s.val > 0).map(seg => {
      const segH = Math.max(seg.val * scale, 1);
      yCursor -= segH;
      return `<rect x="${x.toFixed(1)}" y="${yCursor.toFixed(1)}" width="${barWidth}" height="${segH.toFixed(1)}" fill="${seg.color}" rx="1"></rect>`;
    }).join("");
    const highlight = wk.isCurrent
      ? `<rect x="${(x - 4).toFixed(1)}" y="${padT - 4}" width="${barWidth + 8}" height="${innerH + 8}" fill="none" stroke="var(--sky-400)" stroke-width="1.5" rx="6" opacity="0.55"></rect>`
      : "";
    const recoveryDot = wk.weekType === "recovery"
      ? `<circle cx="${(x + barWidth / 2).toFixed(1)}" cy="${padT - 1}" r="2" fill="var(--amber)"></circle>`
      : "";
    const noteDot = wk.note
      ? `<circle cx="${(x + barWidth / 2).toFixed(1)}" cy="${padT - 1}" r="2" fill="var(--sky-400)"></circle>`
      : "";

    const thisMonth = monthOf(wk.label);
    const prevMonth = i > 0 ? monthOf(weeks[i - 1].label) : null;
    const showLabel = i === 0 || thisMonth !== prevMonth;
    const labelStyle = wk.isCurrent ? ' style="fill:var(--ice-300); font-weight:700;"' : "";
    const label = showLabel
      ? `<text class="chart-axis-label" x="${(x + barWidth / 2).toFixed(1)}" y="${h - padB + 14}" text-anchor="middle"${labelStyle}>${monthShort(thisMonth)}</text>`
      : "";
    // Grosszuegiger unsichtbarer Hit-Bereich ueber den ganzen Slot, weil die
    // Balken bei 51 Wochen im Chart teils nur 1-2px schmal sind.
    const hit = `<rect class="week-bar-hit" data-week-idx="${i}" x="${(padL + i * slot).toFixed(1)}" y="${padT}" width="${slot.toFixed(1)}" height="${innerH}" fill="transparent" style="cursor:pointer;"></rect>`;
    return `${highlight}${rects}${recoveryDot}${noteDot}${label}${hit}`;
  }).join("");

  return `<svg class="chart-svg" viewBox="0 0 ${w} ${h}">${gridLines}${bars}</svg>`;
}

function weekPlanDetailText(wk) {
  if (!wk) return "";
  const typeLabel = wk.weekType === "recovery" ? "Recovery-Woche" : "Aufbau-Woche";
  const parts = [`<b>Woche ab ${escapeHtml(wk.label)}</b> – ${typeLabel}`];
  if (wk.note) parts.push(escapeHtml(wk.note));
  parts.push(`Geschätzt: ${wk.runHours}h Laufen, ${wk.bikeHours}h Rad, ${wk.strengthHours}h Kraft/EMOM/Core`);
  return parts.join(" · ");
}

function weekPreviewDaysHtml(days) {
  if (!days) return "";
  return `<div class="week-grid" style="margin-top:10px;">${days.map(d => `
    <div class="day-col">
      <div class="day-col-head"><span class="day-name">${d.weekday}</span><span class="day-date">${fmtDateShort(d.date)}</span></div>
      <div style="font-size:11px; color:var(--muted); margin-bottom:2px;">${escapeHtml(d.focus)}</div>
      <div class="stack" style="gap:6px;">${d.units.length ? d.units.map(u => `
        <div class="day-mini-unit"><span style="flex:1;">${escapeHtml(u.name)}${u.keySession ? ' <span class="unit-key-badge">Key</span>' : ""}${u.detail ? `<div class="unit-detail" style="margin-top:2px;">${escapeHtml(u.detail)}</div>` : ""}</span></div>
      `).join("") : `<div class="card-note">Nichts geplant.</div>`}</div>
    </div>`).join("")}</div>`;
}

function setupWeekPlanClicks(weeks) {
  const detail = document.getElementById("week-plan-detail");
  const svg = detail ? detail.closest(".card").querySelector(".chart-svg") : null;
  if (!svg || !detail) return;
  svg.querySelectorAll(".week-bar-hit").forEach(hit => {
    hit.addEventListener("click", () => {
      const wk = weeks[Number(hit.dataset.weekIdx)];
      detail.style.display = "block";
      detail.innerHTML = weekPlanDetailText(wk) + weekPreviewDaysHtml(wk.days);
    });
  });
}

/* ---------- shared: full week overview (Heute + Woche + Kraft) ---------- */

function unitRowHtml(u, dateStr, weekDays, weekStart) {
  const moveControls = weekDays
    ? `${moveSelectHtml(u, dateStr, weekDays, weekStart)}${autoMoveButtonHtml(u)}`
    : "";
  return `
    <div class="day-mini-unit">
      ${statusDotHtml(dateStr, u)}
      <span style="flex:1;">
        ${escapeHtml(u.name)}${u.keySession ? ' <span class="unit-key-badge">Key</span>' : ""}${u.planLabel ? ` <span class="unit-key-badge" style="color:var(--sky-400);">${escapeHtml(u.planLabel)}</span>` : ""}
        ${u.detail ? `<div class="unit-detail" style="margin-top:2px;">${escapeHtml(u.detail)}${u.plannedDurationMin ? ` · ~${u.plannedDurationMin} min` : ""}</div>` : ""}
        ${u.movedFromWeekday ? `<div class="moved-note">verschoben von ${u.movedFromWeekday}</div>` : ""}
      </span>
      ${moveControls}
    </div>`;
}

function buildWeekOverview(data) {
  const todayDate = data.today.date;
  return data.week.days.map(d => {
    const unitsHtml = d.units.map(u => unitRowHtml(u, d.date, data.week.days, data.week.startDate)).join("");
    return `
      <div class="day-col ${d.date === todayDate ? "is-today" : ""}">
        <div class="day-col-head"><span class="day-name">${d.weekday}</span><span class="day-date">${fmtDateShort(d.date)}</span></div>
        <div style="font-size:11px; color:var(--muted); margin-bottom:2px;">${escapeHtml(d.focus)}</div>
        <div class="stack" style="gap:6px;">${unitsHtml}</div>
        ${d.fallbackNote ? `<div class="fallback-note">${escapeHtml(d.fallbackNote)}</div>` : ""}
      </div>`;
  }).join("");
}

/* ---------- sleep tips ---------- */

function buildSleepTips(sleep) {
  const tips = [];
  if (sleep.totalMin != null && sleep.totalMin < 360) {
    tips.push("Unter 6 h Schlaf – priorisiere heute Nacht eine frühere Bettzeit, besonders vor anspruchsvollen Einheiten.");
  }
  if (sleep.awakeMin != null && sleep.totalMin > 0 && sleep.awakeMin / sleep.totalMin > 0.12) {
    tips.push("Recht viel Wachzeit in der Nacht – Bildschirmzeit/Koffein am Abend reduzieren, Zimmertemperatur prüfen.");
  }
  if (sleep.deepMin != null && sleep.totalMin > 0 && sleep.deepMin / sleep.totalMin < 0.10) {
    tips.push("Wenig Tiefschlaf-Anteil – späte, schwere Mahlzeiten oder Alkohol am Abend können das drücken.");
  }
  if (sleep.sleepScore != null && sleep.sleepScore < 60) {
    tips.push("Niedriger Schlaf-Score – heute bewusst genug Erholung zwischen den Einheiten einplanen.");
  }
  if (!tips.length) {
    tips.push("Guter Schlaf letzte Nacht – solide Basis für die heutigen Einheiten.");
  }
  return tips;
}

/* ---------- tab navigation ---------- */

function setupTabs() {
  document.querySelectorAll("[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("is-active", b.dataset.tab === tab));
      document.querySelectorAll("[data-tab-panel]").forEach(p => p.classList.toggle("is-active", p.dataset.tabPanel === tab));
      window.scrollTo({ top: 0 });
    });
  });
}

function setupInteractions() {
  document.body.addEventListener("click", (e) => {
    const copyBtn = e.target.closest(".copy-cmd-btn");
    if (copyBtn) {
      const restore = copyBtn.textContent;
      const done = () => { copyBtn.textContent = "Kopiert!"; setTimeout(() => { copyBtn.textContent = restore; }, 1500); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(copyBtn.dataset.cmd).then(done).catch(done);
      } else {
        done();
      }
      return;
    }

    if (typeof CURRENT_ROLE !== "undefined" && CURRENT_ROLE === "viewer") return;

    const autoBtn = e.target.closest(".auto-move-btn");
    if (autoBtn) {
      autoRescheduleUnit(autoBtn.dataset.autoWeekday, autoBtn.dataset.autoUnit);
      return;
    }

    const dot = e.target.closest(".status-dot.clickable");
    if (!dot) return;
    const current = ["done", "skipped", "planned"].find(s => dot.classList.contains(s)) || "planned";
    setUnitOverride(dot.dataset.toggleDate, dot.dataset.toggleUnit, STATUS_CYCLE[current]);
    if (PRISTINE_DATA) renderAll();
  });

  document.body.addEventListener("change", (e) => {
    if (typeof CURRENT_ROLE !== "undefined" && CURRENT_ROLE === "viewer") return;
    const sel = e.target.closest(".move-select");
    if (!sel) return;
    const targetDate = sel.value;
    const homeWeekday = sel.dataset.homeWeekday;
    const isHome = APP_DATA && APP_DATA.week.days.find(d => d.weekday === homeWeekday)?.date === targetDate;
    setMoveOverride(sel.dataset.weekStart, homeWeekday, sel.dataset.moveUnit, isHome ? null : targetDate);
    if (PRISTINE_DATA) renderAll();
  });
}

function setupSyncButton() {
  const btn = document.getElementById("sync-btn");
  const panel = document.getElementById("sync-panel");
  const label = document.getElementById("sync-btn-label");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.classList.add("is-syncing");
    label.textContent = "Synchronisiere…";
    panel.hidden = true;

    try {
      const res = await fetch("/api/sync", { method: "POST" });
      const result = await res.json();
      const lines = (result.log || "").split("\n").map(l => l.trim()).filter(Boolean);
      panel.innerHTML = `<div class="title">${result.ok ? "Sync erfolgreich" : "Sync fehlgeschlagen"}</div><ul>${lines.map(l => `<li>${escapeHtml(l)}</li>`).join("")}</ul>`;
      panel.hidden = false;

      if (result.ok) {
        const freshData = await fetch("data/training-data.json?_=" + Date.now()).then(r => r.json());
        renderAll(freshData);
      }
    } catch (err) {
      panel.innerHTML = `<div class="title">Fehler beim Sync</div><div>${escapeHtml(String(err))}</div>`;
      panel.hidden = false;
    } finally {
      btn.disabled = false;
      btn.classList.remove("is-syncing");
      label.textContent = "Synchronisieren";
      setTimeout(() => { panel.hidden = true; }, 10000);
    }
  });
}

/* ---------- render: Heute ---------- */

function renderHeute(data) {
  const t = data.today;
  const recoveryScore = computeRecoveryScore(t.sleep);

  const unitsHtml = t.units.map(u => `
    <div class="unit">
      ${statusDotHtml(t.date, u)}
      <div>
        <div class="unit-name">${escapeHtml(u.name)}${u.keySession ? ' <span class="unit-key-badge">Key</span>' : ""}${u.planLabel ? ` <span class="unit-key-badge" style="color:var(--sky-400);">${escapeHtml(u.planLabel)}</span>` : ""}</div>
        <div class="unit-detail">${escapeHtml(u.detail)}${u.plannedDurationMin ? ` · ~${u.plannedDurationMin} min` : ""}</div>
        ${u.movedFromWeekday ? `<div class="moved-note">verschoben von ${u.movedFromWeekday}</div>` : ""}
      </div>
      <span class="tag ${u.tag}">${u.tag}</span>
      ${moveSelectHtml(u, t.date, data.week.days, data.week.startDate)}
      ${autoMoveButtonHtml(u)}
    </div>`).join("");

  document.getElementById("tab-heute").innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">${data.week.label}</div>
      <div class="page-title">${fmtDateLong(t.date)}</div>
      <div class="page-sub">${escapeHtml(t.dayFocus)}</div>
    </div>

    <div class="stack">
      ${t.overloadWarning ? `
      <div class="card accent-amber">
        <div class="card-head"><span class="card-title">⚠ Überlastungs-Hinweis</span></div>
        <div class="card-note">${t.overloadWarning.reasons.map(escapeHtml).join(" · ")}</div>
        <div class="card-note" style="margin-top:6px;">Mehrere Warnsignale gleichzeitig – heute eher lockerer angehen oder einen Ruhetag einschieben.</div>
      </div>` : ""}

      <div class="card accent-teal">
        <div class="card-head"><span class="card-title">Heutige Einheiten</span><span class="card-note">Kreis: geplant → erledigt → abgelehnt · Dropdown: Tag wählen · 🪄: automatisch sinnvoll verschieben</span></div>
        <div class="unit-list">${unitsHtml}</div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-head"><span class="card-title">Erholung</span><span class="card-note">Body Battery &amp; HRV</span></div>
          <div style="display:flex; align-items:center; gap:20px; flex-wrap:wrap;">
            ${recoveryRing(recoveryScore ?? 0, fmtVal(recoveryScore), "Score")}
            <div class="grid" style="flex:1; grid-template-columns:1fr 1fr; gap:14px; min-width:180px;">
              <div class="stat"><span class="stat-value">${fmtVal(t.sleep.restingHr)}<span class="unit">bpm</span></span><span class="stat-label">Ruhepuls</span></div>
              <div class="stat"><span class="stat-value">${fmtVal(t.sleep.hrv)}<span class="unit">ms</span></span><span class="stat-label">HRV</span></div>
              <div class="stat"><span class="stat-value">${fmtVal(t.sleep.bodyBattery)}</span><span class="stat-label">Body Battery</span></div>
              <div class="stat"><span class="stat-value">${fmtVal(t.sleep.sleepScore)}</span><span class="stat-label">Schlaf-Score</span></div>
              <div class="stat"><span class="stat-value">${fmtVal(t.sleep.stress)}</span><span class="stat-label">Stresslevel</span></div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><span class="card-title">Schlaf letzte Nacht</span><span class="card-note">${fmtMin(t.sleep.totalMin)} gesamt</span></div>
          <div class="sleep-bar">
            <div class="sleep-seg deep" style="width:${t.sleep.totalMin ? t.sleep.deepMin/t.sleep.totalMin*100 : 0}%"></div>
            <div class="sleep-seg light" style="width:${t.sleep.totalMin ? t.sleep.lightMin/t.sleep.totalMin*100 : 0}%"></div>
            <div class="sleep-seg rem" style="width:${t.sleep.totalMin ? t.sleep.remMin/t.sleep.totalMin*100 : 0}%"></div>
            <div class="sleep-seg awake" style="width:${t.sleep.totalMin ? t.sleep.awakeMin/t.sleep.totalMin*100 : 0}%"></div>
          </div>
          <div class="sleep-legend">
            <span class="lg"><span class="sw deep"></span>Tief ${fmtMin(t.sleep.deepMin)}</span>
            <span class="lg"><span class="sw light"></span>Leicht ${fmtMin(t.sleep.lightMin)}</span>
            <span class="lg"><span class="sw rem"></span>REM ${fmtMin(t.sleep.remMin)}</span>
            <span class="lg"><span class="sw awake"></span>Wach ${fmtMin(t.sleep.awakeMin)}</span>
          </div>
          <ul class="tips-list">${buildSleepTips(t.sleep).map(x => `<li>${x}</li>`).join("")}</ul>
        </div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-head"><span class="card-title">Wochenfortschritt</span><span class="card-note">Details im Tab „Woche“</span></div>
          <div class="stack" style="gap:12px;">
            ${progressBar({ name: "Lauf", value: data.week.actuals.runVolumeKm, target: data.week.targets.runVolumeKm, unit: " km", decimals: 1 })}
            ${progressBar({ name: "Rad", value: data.week.actuals.bikeVolumeKm, target: data.week.targets.bikeVolumeKm, unit: " km", decimals: 1 })}
            ${progressBar({ name: "Zeit", value: data.week.actuals.timeMin, target: data.week.targets.timeMin, unit: " min" })}
          </div>
        </div>

        <div class="card">
          <div class="card-head"><span class="card-title">Körperwerte</span></div>
          <div class="stat-row">
            <div class="stat"><span class="stat-value xl">${fmtVal(t.body.weightKg)}<span class="unit">kg</span></span><span class="stat-label">Gewicht</span></div>
            <div class="stat"><span class="stat-value xl">${fmtVal(t.body.vo2max)}</span><span class="stat-label">VO2max</span></div>
          </div>
          ${t.steps !== undefined && t.steps !== null ? `
          <div style="margin-top:14px;">
            ${progressBar({ name: "Schritte heute", value: t.steps, target: t.stepGoal || 10000, unit: "", decimals: 0 })}
          </div>` : ""}
        </div>
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Tagesnotiz</span><span class="card-note">fließt in die Coach-Einschätzung ein · <span id="note-saved-hint" class="note-saved-hint">gespeichert</span></span></div>
        <div style="display:flex; gap:8px; align-items:flex-start;">
          <textarea id="daily-note" class="note-box" ${canEdit() ? "" : "readonly"} placeholder="Wie fühlst du dich heute? z. B. Beine schwer, gut geschlafen, motiviert…">${escapeHtml(t.note || "")}</textarea>
          ${canEdit() ? `<button id="note-mic-btn" class="btn-small" type="button" title="Notiz per Sprache diktieren">🎤</button>` : ""}
        </div>
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Wochenübersicht</span><span class="card-note">Alle Einheiten dieser Woche</span></div>
        <div class="week-grid">${buildWeekOverview(data)}</div>
      </div>
    </div>`;

  const noteEl = document.getElementById("daily-note");
  if (noteEl) {
    let debounceTimer;
    noteEl.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        setNoteOverride(t.date, noteEl.value);
        if (APP_DATA) {
          APP_DATA.today.note = noteEl.value;
          renderCoach(APP_DATA);
        }
        const hint = document.getElementById("note-saved-hint");
        if (hint) {
          hint.classList.add("show");
          setTimeout(() => hint.classList.remove("show"), 1500);
        }
      }, 400);
    });
    attachSpeechButton(document.getElementById("note-mic-btn"), (transcript) => {
      noteEl.value = (noteEl.value ? noteEl.value.trim() + " " : "") + transcript;
      noteEl.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
}

/* ---------- render: Woche ---------- */

function weeklyStepsHtml(days, prevWeekAvg) {
  const maxSteps = Math.max(...days.map(d => d.steps || 0), prevWeekAvg || 0, 1);
  const barBlock = (value, label, color, has = true) => {
    const pct = has ? clamp((value / maxSteps) * 100, 3, 100) : 0;
    return `
      <div style="display:flex; flex-direction:column; align-items:center; gap:6px; flex:1;">
        <div style="font-size:11px; color:var(--muted);">${has ? Math.round(value).toLocaleString("de-DE") : "–"}</div>
        <div style="width:100%; height:50px; display:flex; align-items:flex-end; background:var(--surface-2); border-radius:4px; overflow:hidden;">
          <div style="width:100%; height:${pct}%; background:${color};"></div>
        </div>
        <div style="font-size:11px; color:var(--text-dim); font-weight:600;">${label}</div>
      </div>`;
  };
  const bars = days.map(d => {
    const has = d.steps !== undefined && d.steps !== null;
    const overGoal = has && d.stepGoal && d.steps >= d.stepGoal;
    return barBlock(d.steps || 0, WEEKDAYS_SHORT[d.weekday], overGoal ? "var(--teal)" : "var(--ocean-500)", has);
  }).join("");
  const prevBar = (prevWeekAvg !== undefined && prevWeekAvg !== null)
    ? `<div style="width:1px; background:var(--border-soft); align-self:stretch;"></div>${barBlock(prevWeekAvg, "Ø Vorwoche", "var(--amber)")}`
    : "";
  return `<div style="display:flex; gap:8px;">${bars}${prevBar}</div>`;
}

function renderWoche(data) {
  const w = data.week;
  const selfCoachHtml = w.selfCoaching.map(s => `<li>${escapeHtml(s)}</li>`).join("");

  document.getElementById("tab-woche").innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">${w.startDate === w.endDate ? "" : `${fmtDateShort(w.startDate)} – ${fmtDateShort(w.endDate)}`}</div>
      <div class="page-title">${w.label}</div>
      <div class="page-sub">Zielrhythmus: ${escapeHtml(data.profile.cycle)}</div>
    </div>

    <div class="stack">
      <div class="card">
        <div class="card-head"><span class="card-title">Wochenfortschritt im Detail</span></div>
        <div class="grid grid-2" style="gap:16px;">
          ${progressBar({ name: "Lauf", value: w.actuals.runVolumeKm, target: w.targets.runVolumeKm, unit: " km", decimals: 1 })}
          ${progressBar({ name: "Rad", value: w.actuals.bikeVolumeKm, target: w.targets.bikeVolumeKm, unit: " km", decimals: 1 })}
          ${progressBar({ name: "Zeit", value: w.actuals.timeMin, target: w.targets.timeMin, unit: " min" })}
          ${progressBar({ name: "Zone-2-Anteil", value: w.actuals.zone2SharePct, target: w.targets.zone2SharePct, unit: " %", variant: "good" })}
        </div>
        <div class="bar-block" style="margin-top:14px;">
          <div class="bar-top"><span class="name">Belastung vs. Schnitt (letzte 4 Wochen)</span><span class="value">${w.actuals.loadVsAvgPct > 0 ? "+" : ""}${w.actuals.loadVsAvgPct}%</span></div>
          <div class="bar-track"><div class="bar-fill ${w.actuals.loadVsAvgPct < -30 ? "low" : ""}" style="width:${clamp(w.actuals.loadVsAvgPct + 100, 0, 100)}%"></div></div>
          ${w.actuals.loadTrendNote ? `<div class="card-note" style="margin-top:6px; color:${w.actuals.loadTrendNote.level === "high" ? "var(--amber)" : "var(--text-dim)"};">${escapeHtml(w.actuals.loadTrendNote.text)}</div>` : ""}
        </div>
        <div class="card-note" style="margin-top:10px;">Höhenmeter diese Woche: <b>${w.actuals.elevationGainM.toLocaleString("de-DE")} hm</b></div>
      </div>

      <div class="week-grid">${buildWeekOverview(data)}</div>

      ${w.days.some(d => d.steps !== undefined && d.steps !== null) ? `
      <div class="card">
        <div class="card-head"><span class="card-title">Schritte diese Woche</span><span class="card-note">Ø ${Math.round(w.days.filter(d => d.steps != null).reduce((s, d) => s + d.steps, 0) / w.days.filter(d => d.steps != null).length).toLocaleString("de-DE")} / Tag</span></div>
        ${weeklyStepsHtml(w.days, data.performance?.weeks?.length > 1 ? data.performance.weeks[data.performance.weeks.length - 2].avgSteps : null)}
      </div>` : ""}

      <div class="card accent-amber">
        <div class="card-head"><span class="card-title">Selbststeuerung &amp; Fallback</span></div>
        <ul class="coach-reasons">${selfCoachHtml}</ul>
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Trainingsplan – nächste Wochen</span><span class="card-note">Anklicken für Details · <span style="color:var(--amber);">•</span> Recovery · <span style="color:var(--sky-400);">•</span> Besonderheit</span></div>
        ${weekPlanBarsSVG(data.upcomingPlan || [])}
        <div id="week-plan-detail" class="card-note" style="margin-top:8px; display:none;"></div>
        <div style="display:flex; gap:16px; margin-top:6px; font-size:11px; color:var(--muted); flex-wrap:wrap;">
          <span style="display:flex; align-items:center; gap:6px;"><span style="width:10px; height:10px; border-radius:3px; background:var(--sky-400); display:inline-block;"></span>Laufen</span>
          <span style="display:flex; align-items:center; gap:6px;"><span style="width:10px; height:10px; border-radius:3px; background:var(--ocean-600); display:inline-block;"></span>Radfahren</span>
          <span style="display:flex; align-items:center; gap:6px;"><span style="width:10px; height:10px; border-radius:3px; background:var(--teal); display:inline-block;"></span>Kraft/EMOM/Core</span>
        </div>
      </div>
    </div>`;
  setupWeekPlanClicks(data.upcomingPlan || []);
}

/* ---------- render: Verlauf ---------- */

function renderVerlauf(data) {
  const h = data.history;

  const wc = h.weekCompare, mc = h.monthCompare;
  const compareBlock = (current, previous, currentHeading, previousHeading) => {
    const max = Math.max(current.distanceKm, previous.distanceKm, 1);
    const diff = current.distanceKm - previous.distanceKm;
    const pct = previous.distanceKm > 0 ? Math.round((diff / previous.distanceKm) * 100) : (current.distanceKm > 0 ? 100 : 0);
    const up = diff >= 0;
    const deltaText = Math.abs(diff) < 0.05
      ? "Genau wie zuvor"
      : `${up ? "+" : ""}${diff.toFixed(1)} km (${up ? "+" : ""}${pct}%) ${up ? "mehr" : "weniger"} als ${previousHeading.toLowerCase()}`;
    return `
      <div class="compare-pair">
        <div class="compare-side">
          <div class="compare-heading">${currentHeading}</div>
          <span class="stat-value xl">${current.distanceKm}<span class="unit">km</span></span>
          <div class="stat-label">${current.label}</div>
          <div class="card-note">${current.sessions} Einheiten${current.note ? " · " + escapeHtml(current.note) : ""}</div>
        </div>
        <div class="compare-vs">vs</div>
        <div class="compare-side">
          <div class="compare-heading" style="color:var(--muted);">${previousHeading}</div>
          <span class="stat-value xl">${previous.distanceKm}<span class="unit">km</span></span>
          <div class="stat-label">${previous.label}</div>
          <div class="card-note">${previous.sessions} Einheiten${previous.note ? " · " + escapeHtml(previous.note) : ""}</div>
        </div>
      </div>
      <div class="compare-bars">
        <div class="compare-bar-row"><span class="compare-bar-label">${currentHeading}</span><div class="compare-bar-track"><div class="compare-bar-fill current" style="width:${(current.distanceKm / max * 100).toFixed(0)}%"></div></div></div>
        <div class="compare-bar-row"><span class="compare-bar-label">${previousHeading}</span><div class="compare-bar-track"><div class="compare-bar-fill previous" style="width:${(previous.distanceKm / max * 100).toFixed(0)}%"></div></div></div>
      </div>
      <div class="compare-delta ${up ? "up" : "down"}">${deltaText}</div>`;
  };

  const logHtml = h.log.map(l => `
    <div class="log-row">
      <span class="log-date">${fmtDateShort(l.date)}</span>
      <div style="display:flex; align-items:center; gap:10px;">
        <span class="type-chip">${TYPE_ICON[l.type] || "•"}</span>
        <div><div class="log-name">${escapeHtml(l.name)}</div>${l.note ? `<div class="log-note">${escapeHtml(l.note)}</div>` : ""}</div>
      </div>
      <span class="log-metric">${l.distanceKm ? l.distanceKm + " km" : fmtMin(l.durationMin)}</span>
    </div>`).join("");

  document.getElementById("tab-verlauf").innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">Verlauf</div>
      <div class="page-title">Wie du dich entwickelst</div>
      <div class="page-sub">Vergleich zu vorheriger Woche &amp; vorherigem Monat</div>
    </div>

    <div class="stack">
      <div class="grid grid-2">
        <div class="card"><div class="card-head"><span class="card-title">Diese Woche vs. letzte Woche</span></div>${compareBlock(wc.thisWeek, wc.lastWeek, "Diese Woche", "Letzte Woche")}</div>
        <div class="card"><div class="card-head"><span class="card-title">Dieser Monat vs. letzter Monat</span></div>${compareBlock(mc.thisMonth, mc.lastMonth, "Dieser Monat", "Letzter Monat")}</div>
      </div>

      <div class="card flush">
        <div style="padding:18px 20px 8px;"><span class="card-title">Log der letzten Einheiten</span></div>
        <div class="log-list" style="padding:0 20px 20px;">${logHtml}</div>
      </div>
    </div>`;
}

/* ---------- render: Performance ---------- */

function deltaInfo(firstVal, lastVal, { decimals = 0, unit = "", lowerIsBetter = false, sinceLabel, formatFn } = {}) {
  if (firstVal === null || firstVal === undefined || lastVal === null || lastVal === undefined) {
    return { text: "noch nicht genug Daten", up: true };
  }
  const diff = lastVal - firstVal;
  const better = lowerIsBetter ? diff <= 0 : diff >= 0;
  const shownDiff = formatFn ? formatFn(Math.abs(diff)) : Math.abs(diff).toFixed(decimals);
  const sign = diff === 0 ? "±" : (lowerIsBetter ? (diff < 0 ? "−" : "+") : (diff >= 0 ? "+" : "−"));
  return { text: `${sign}${shownDiff}${unit} seit ${sinceLabel}`, up: better };
}

function renderPerformance(data) {
  const weeks = data.performance.weeks;
  const first = weeks[0], last = weeks[weeks.length - 1];

  const statCard = (label, valNow, valUnit, spark, delta) => `
    <div class="card">
      <div class="stat"><span class="stat-value">${valNow}<span class="unit">${valUnit}</span></span><span class="stat-label">${label}</span></div>
      <div style="margin:8px 0 2px;">${lineChartSVG(spark, { compact: true })}</div>
      <span class="stat-delta ${delta.up ? "up" : "down"}">${delta.text}</span>
    </div>`;

  const sparkOf = (key) => weeks.map(w => ({ value: w[key], label: w.label })).filter(p => p.value !== null && p.value !== undefined);

  const runPacePoints = data.performance.runPace.map(p => ({ value: p.paceSecPerKm, label: fmtDateShort(p.date) }));
  const bikeSpeedPoints = data.performance.bikeSpeed.map(p => ({ value: p.avgSpeedKmh, label: fmtDateShort(p.date) }));

  document.getElementById("tab-performance").innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">Performance</div>
      <div class="page-title">Letzte 8 Wochen</div>
      <div class="page-sub">${first.label} – ${last.label}</div>
    </div>

    <div class="stack">
      <div class="grid-auto">
        ${statCard("VO2max", fmtVal(last.vo2max), "", sparkOf("vo2max"),
          deltaInfo(first.vo2max, last.vo2max, { sinceLabel: first.label }))}
        ${statCard("Zone-2-Pace", fmtPace(last.zone2PaceSecPerKm), "/km", sparkOf("zone2PaceSecPerKm"),
          deltaInfo(first.zone2PaceSecPerKm, last.zone2PaceSecPerKm, { unit: "s", sinceLabel: first.label, lowerIsBetter: true }))}
        ${statCard("Laufumfang", fmtVal(last.runVolumeKm), "km", sparkOf("runVolumeKm"),
          deltaInfo(first.runVolumeKm, last.runVolumeKm, { unit: " km", sinceLabel: first.label }))}
        ${statCard("Radumfang", fmtVal(last.bikeVolumeKm), "km", sparkOf("bikeVolumeKm"),
          deltaInfo(first.bikeVolumeKm, last.bikeVolumeKm, { unit: " km", sinceLabel: first.label }))}
        ${statCard("Gewicht", fmtVal(last.weightKg), "kg", sparkOf("weightKg"),
          deltaInfo(first.weightKg, last.weightKg, { decimals: 1, unit: " kg", sinceLabel: first.label, lowerIsBetter: true }))}
        ${weeks.some(w => w.avgSteps != null) ? statCard("Schritte Ø/Tag", fmtVal(last.avgSteps), "", sparkOf("avgSteps"),
          deltaInfo(first.avgSteps, last.avgSteps, { sinceLabel: first.label })) : ""}
        ${weeks.some(w => w.completionPct != null) ? statCard("Erledigungsquote", fmtVal(last.completionPct), "%", sparkOf("completionPct"),
          deltaInfo(first.completionPct, last.completionPct, { unit: " %", sinceLabel: first.label })) : ""}
      </div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-head"><span class="card-title">Lauf-Tempo</span><span class="card-note">Zone-2 · min/km · niedriger = schneller</span></div>
          ${lineChartSVG(runPacePoints, { invert: true })}
        </div>

        <div class="card">
          <div class="card-head"><span class="card-title">Rad-Schnitt</span><span class="card-note">km/h</span></div>
          ${lineChartSVG(bikeSpeedPoints)}
        </div>
      </div>

      ${data.performance.racePredictions && Object.keys(data.performance.racePredictions).length ? `
      <div class="card">
        <div class="card-head"><span class="card-title">Geschätzte Wettkampfzeit</span><span class="card-note">Von Garmin anhand deiner aktuellen Fitness geschätzt, kein echtes Rennen nötig</span></div>
        <div class="stat-row">
          <div class="stat"><span class="stat-value">${fmtDuration(data.performance.racePredictions.time5kSec)}</span><span class="stat-label">5 km</span></div>
          <div class="stat"><span class="stat-value">${fmtDuration(data.performance.racePredictions.time10kSec)}</span><span class="stat-label">10 km</span></div>
          <div class="stat"><span class="stat-value">${fmtDuration(data.performance.racePredictions.timeHalfMarathonSec)}</span><span class="stat-label">Halbmarathon</span></div>
          <div class="stat"><span class="stat-value">${fmtDuration(data.performance.racePredictions.timeMarathonSec)}</span><span class="stat-label">Marathon</span></div>
        </div>
      </div>` : ""}
    </div>`;
}

/* ---------- coach rule engine ---------- */

function buildCoachRecommendation(data) {
  const t = data.today, w = data.week;
  const recoveryScore = computeRecoveryScore(t.sleep);
  const recoveryLow = recoveryScore !== null && recoveryScore < 55;
  const dayIndex = w.days.findIndex(d => d.date === t.date);
  const todayPlan = w.days[dayIndex];
  const isKeyDay = todayPlan.units.some(u => u.keySession);
  const weekFraction = (dayIndex + 1) / 7;
  const expectedTimeMin = w.targets.timeMin * weekFraction;
  const timeGapPct = w.targets.timeMin > 0 ? ((w.actuals.timeMin - expectedTimeMin) / w.targets.timeMin) * 100 : 0;

  const reasons = [];
  const hrvNote = (t.sleep.hrv && t.sleep.hrvBaseline) ? `, HRV ${t.sleep.hrv} ms vs. Basis ${t.sleep.hrvBaseline} ms` : "";
  reasons.push(`Erholung: Score ${fmtVal(recoveryScore)} (Schlaf-Score ${fmtVal(t.sleep.sleepScore)}, Body Battery ${fmtVal(t.sleep.bodyBattery)}${hrvNote}).`);
  reasons.push(`Wochenfortschritt: ${fmtMin(w.actuals.timeMin)} von ${fmtMin(w.targets.timeMin)} Zielzeit (Lauf ${w.actuals.runVolumeKm} km, Rad ${w.actuals.bikeVolumeKm} km) – Tag ${dayIndex + 1} von 7.`);

  let headline;
  if (recoveryLow && isKeyDay) {
    const key = todayPlan.units.find(u => u.keySession);
    headline = `Erholung ist niedrig, aber heute ist mit ${key.name} eine Schlüsseleinheit – lauf sie, nimm aber Tempo und Zusatzreize raus.`;
    reasons.push(`${key.name} bleibt bestehen – das ist eine der beiden Laufeinheiten, die nicht durchs Rad ersetzt werden sollten.`);
  } else if (recoveryLow) {
    headline = `Heute eher locker – deine Erholung ist niedrig, das ist kein Tag zum Kämpfen.`;
    reasons.push(`Falls die Beine grundsätzlich nicht mitmachen: ersatzweise ca. 90 min Rad Zone 2 statt der Laufeinheit.`);
  } else if (isKeyDay) {
    const key = todayPlan.units.find(u => u.keySession);
    headline = `Heute zählt: ${key.name}. Der Rest der Woche kann sich danach richten.`;
    reasons.push(`Erholung ist gut genug, um die Einheit wie geplant anzugehen (${escapeHtml(key.detail)}).`);
  } else if (timeGapPct < -20 && dayIndex > 1) {
    headline = `Du liegst zeitlich hinter deinem Wochenpensum – heute sauber Zone 2 abspulen, ohne zu überziehen.`;
    reasons.push(`Rückstand von ca. ${Math.abs(timeGapPct).toFixed(0)}% zur erwarteten Trainingszeit an diesem Wochentag.`);
  } else if (dayIndex === 0) {
    headline = `Sauberer Start in die Woche: heute geht es um Konstanz in Zone 2, nicht um Tempo.`;
    reasons.push(`Aerobe Basis entsteht über Wiederholbarkeit – lieber 5 bpm unter der Zielzone als 5 bpm drüber.`);
  } else {
    headline = `Konzentriere dich heute darauf, konstant in Zone 2 zu laufen.`;
    reasons.push(`Kein akuter Handlungsbedarf – bleib beim Plan und achte auf die HF-Zone.`);
  }

  if (recoveryScore !== null && recoveryScore >= 55 && recoveryScore < 65) {
    reasons.push(`Erholung ist solide, aber nicht top – Zusatzreize (EMOM/Core) bei Bedarf als erstes streichen.`);
  }

  if (t.note && t.note.trim()) {
    const note = escapeHtml(t.note.trim());
    const lower = t.note.toLowerCase();
    if (/müde|kaputt|schwer|erschöpft|schlapp/.test(lower)) {
      reasons.push(`Deine Notiz („${note}“) klingt nach Erschöpfung – nimm das ernst, auch wenn die Zahlen ok aussehen, und reduziere lieber Umfang oder Intensität.`);
    } else if (/gut|stark|frisch|motiviert|fit/.test(lower)) {
      reasons.push(`Deine Notiz („${note}“) klingt positiv – nutze den Schwung, ohne den Plan zu sprengen.`);
    } else {
      reasons.push(`Deine Notiz: „${note}“.`);
    }
  }

  return { headline, reasons, recoveryScore, dayIndex, isKeyDay, timeGapPct };
}

/* ---------- render: Coach ---------- */

function renderCoach(data) {
  const rec = buildCoachRecommendation(data);
  const w = data.week;

  document.getElementById("tab-coach").innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">Coach</div>
      <div class="page-title">Deine Einschätzung für heute</div>
      <div class="page-sub">Regelbasiert aus Erholung, Trainingslast, Wochenfortschritt, Konstanz &amp; deiner Notiz</div>
    </div>

    <div class="stack">
      <div class="card coach-hero">
        <div class="coach-headline">${rec.headline}</div>
        <ul class="coach-reasons">${rec.reasons.map(r => `<li>${r}</li>`).join("")}</ul>
      </div>

      <div class="grid-auto">
        <div class="card">
          <div class="stat"><span class="stat-value">${fmtVal(rec.recoveryScore)}</span><span class="stat-label">Erholungs-Score</span></div>
        </div>
        <div class="card">
          <div class="stat"><span class="stat-value">${fmtMin(w.actuals.timeMin)}<span class="unit">/ ${fmtMin(w.targets.timeMin)}</span></span><span class="stat-label">Wochenzeit</span></div>
          ${miniBar(w.actuals.timeMin, w.targets.timeMin)}
        </div>
        <div class="card">
          <div class="stat"><span class="stat-value">${w.actuals.runVolumeKm}<span class="unit">/ ${w.targets.runVolumeKm} km</span></span><span class="stat-label">Lauf diese Woche</span></div>
          ${miniBar(w.actuals.runVolumeKm, w.targets.runVolumeKm)}
        </div>
        <div class="card">
          <div class="stat"><span class="stat-value">${rec.dayIndex + 1}<span class="unit">/ 7</span></span><span class="stat-label">Wochentag</span></div>
        </div>
      </div>

      ${canEdit() ? `
      <div class="card">
        <div class="card-head"><span class="card-title">Frag den Coach</span><span class="card-note">Regelbasiert aus deinen Daten – kein echtes KI-Gespräch</span></div>
        <div style="display:flex; gap:8px;">
          <input type="text" id="coach-question" class="text-input" placeholder="z. B. „Wie ist mein Schlaf?“ oder „Soll ich heute laufen?“" />
          <button id="coach-mic-btn" class="btn-small" type="button" title="Frage per Sprache eingeben">🎤</button>
          <button id="coach-ask-btn" class="btn-small" type="button">Fragen</button>
        </div>
        <div id="coach-qa-log" class="stack" style="margin-top:12px; gap:8px;"></div>
      </div>` : ""}
    </div>`;

  setupCoachQA(data);
}

function answerCoachQuestion(question, data) {
  const q = question.toLowerCase();
  const t = data.today, w = data.week;
  const recoveryScore = computeRecoveryScore(t.sleep);
  const findUnit = (name) => w.days.flatMap(d => d.units).find(u => u.name === name);

  if (/schlaf/.test(q)) {
    return `Letzte Nacht: ${fmtMin(t.sleep.totalMin)} gesamt, Schlaf-Score ${fmtVal(t.sleep.sleepScore)}. ${buildSleepTips(t.sleep)[0]}`;
  }
  if (/erholung|body battery|hrv/.test(q)) {
    return `Erholungs-Score heute: ${fmtVal(recoveryScore)} (Body Battery ${fmtVal(t.sleep.bodyBattery)}, Schlaf-Score ${fmtVal(t.sleep.sleepScore)}, Ruhepuls ${fmtVal(t.sleep.restingHr)} bpm).`;
  }
  if (/gewicht/.test(q)) {
    return `Aktuelles Gewicht: ${fmtVal(t.body.weightKg)} kg.`;
  }
  if (/vo2max/.test(q)) {
    return `Aktueller VO2max-Wert: ${fmtVal(t.body.vo2max)}.`;
  }
  if (/rad/.test(q)) {
    return `Diese Woche bisher ${w.actuals.bikeVolumeKm} von ${w.targets.bikeVolumeKm} km Rad-Ziel.`;
  }
  if (/(wie viel|wieviel|km).*lauf|lauf.*(woche|km)/.test(q)) {
    return `Diese Woche bisher ${w.actuals.runVolumeKm} von ${w.targets.runVolumeKm} km Lauf-Ziel.`;
  }
  if (/zeit|trainiert|umfang/.test(q)) {
    return `Diese Woche bisher ${fmtMin(w.actuals.timeMin)} von ${fmtMin(w.targets.timeMin)} Zielzeit trainiert.`;
  }
  if (/was.*heute|heute.*(einheit|plan)/.test(q)) {
    return t.units.length
      ? t.units.map(u => `${u.name} (${u.status === "done" ? "erledigt" : u.status === "skipped" ? "abgelehnt" : "geplant"})`).join(", ")
      : "Heute stehen keine Einheiten an.";
  }
  if (/soll ich.*(laufen|trainieren|fahren)|heute.*(laufen|trainieren)/.test(q)) {
    return buildCoachRecommendation(data).headline;
  }
  if (/langer lauf|lang.*lauf|mittwoch/.test(q)) {
    const u = findUnit("Langer Lauf");
    return u ? `Langer Lauf: ${u.detail}` : "Kein langer Lauf in dieser Woche gefunden.";
  }
  if (/intervall|freitag/.test(q)) {
    const u = findUnit("Intervalle");
    return u ? `Intervalle: ${u.detail}` : "Keine Intervalle in dieser Woche gefunden.";
  }
  if (/emom/.test(q)) {
    const u = t.units.find(x => x.type === "emom");
    return u ? `Heutiges EMOM: ${u.detail}` : "Heute steht kein EMOM an.";
  }
  return "Dazu hab ich noch keine feste Antwort. Frag z. B. nach Schlaf, Erholung, Gewicht, VO2max, Wochenfortschritt (Lauf/Rad/Zeit), dem langen Lauf, den Intervallen oder ob du heute trainieren solltest.";
}

/**
 * Verbindet einen Mikrofon-Button per Web Speech API mit einer Callback-Funktion,
 * die den erkannten Text bekommt. Rein lokal im Browser, keine Daten verlassen das Geraet
 * ausser an die Spracherkennung des Browsers/Betriebssystems selbst.
 */
function attachSpeechButton(micBtn, onTranscript) {
  if (!micBtn) return;
  const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognitionImpl) {
    micBtn.disabled = true;
    micBtn.title = "Spracheingabe wird von diesem Browser nicht unterstützt";
    return;
  }
  const recognition = new SpeechRecognitionImpl();
  recognition.lang = "de-DE";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  micBtn.addEventListener("click", () => {
    micBtn.classList.add("is-listening");
    try { recognition.start(); } catch { /* schon aktiv */ }
  });
  recognition.addEventListener("result", (e) => onTranscript(e.results[0][0].transcript));
  recognition.addEventListener("end", () => micBtn.classList.remove("is-listening"));
  recognition.addEventListener("error", () => micBtn.classList.remove("is-listening"));
}

function setupCoachQA(data) {
  const input = document.getElementById("coach-question");
  const askBtn = document.getElementById("coach-ask-btn");
  const micBtn = document.getElementById("coach-mic-btn");
  const log = document.getElementById("coach-qa-log");
  if (!input) return;

  const ask = () => {
    const question = input.value.trim();
    if (!question) return;
    const answer = answerCoachQuestion(question, data);
    const item = document.createElement("div");
    item.className = "qa-item";
    item.innerHTML = `<div class="qa-question">${escapeHtml(question)}</div><div class="qa-answer">${escapeHtml(answer)}</div>`;
    log.prepend(item);
    input.value = "";
  };

  askBtn.addEventListener("click", ask);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
  attachSpeechButton(micBtn, (transcript) => { input.value = transcript; });
}

/* ---------- render: Kraft ---------- */

function strengthUnitRow(u, dateStr) {
  return `
    <div class="exercise-row">
      <div style="display:flex; align-items:center; gap:10px; min-width:0;">
        ${statusDotHtml(dateStr, u)}
        <span class="exercise-name">${escapeHtml(u.name)}${u.keySession ? ' <span class="unit-key-badge">Key</span>' : ""}${u.planLabel ? ` <span class="unit-key-badge" style="color:var(--sky-400);">${escapeHtml(u.planLabel)}</span>` : ""}</span>
      </div>
      <span class="exercise-spec">${escapeHtml(u.detail)}${u.plannedDurationMin ? ` · ~${u.plannedDurationMin} min` : ""}</span>
    </div>`;
}

function strengthUnitBlock(u, dateStr) {
  if (u.exercises && u.exercises.length) {
    return `
      <div class="card accent-teal">
        <div class="card-head">
          <span class="card-title" style="display:flex; align-items:center; gap:8px; text-transform:none; font-size:15px;">
            ${statusDotHtml(dateStr, u)}
            ${escapeHtml(u.name)}
          </span>
          <span class="card-note">${u.plannedDurationMin ? `~${u.plannedDurationMin} min` : ""}</span>
        </div>
        <div class="exercise-list">${u.exercises.map(e => `
          <div class="exercise-row">
            <span class="exercise-name">${escapeHtml(e.name)}</span>
            <span class="exercise-spec">${e.sets}×${e.reps} · ${escapeHtml(e.rest)} Pause</span>
          </div>`).join("")}</div>
      </div>`;
  }
  return `<div class="card"><div class="exercise-list">${strengthUnitRow(u, dateStr)}</div></div>`;
}

function strengthReferenceBlock(u) {
  const spec = u.exercises && u.exercises.length
    ? `<div class="exercise-list">${u.exercises.map(e => `
        <div class="exercise-row">
          <span class="exercise-name">${escapeHtml(e.name)}</span>
          <span class="exercise-spec">${e.sets}×${e.reps} · ${escapeHtml(e.rest)} Pause</span>
        </div>`).join("")}</div>`
    : `<div class="unit-detail">${escapeHtml(u.detail)}</div>`;
  return `
    <div class="card">
      <div class="card-head">
        <span class="card-title" style="text-transform:none; font-size:15px;">${escapeHtml(u.name)}</span>
        <span class="card-note">${u.plannedDurationMin ? `~${u.plannedDurationMin} min` : ""}</span>
      </div>
      ${spec}
    </div>`;
}

function renderKraft(data) {
  const isStrength = (u) => u.type === "kraft" || u.type === "emom";
  const todayEntry = data.week.days.find(d => d.date === data.today.date);
  const todayUnits = todayEntry ? todayEntry.units.filter(isStrength) : [];

  const todayCard = `
    <div>
      <div class="card-title" style="margin-bottom:10px;">Heute</div>
      <div class="stack">
        ${todayUnits.length
          ? todayUnits.map(u => strengthUnitBlock(u, data.today.date)).join("")
          : '<div class="card"><div class="card-note">Kein Kraft-/EMOM-Programm heute.</div></div>'}
      </div>
    </div>`;

  const weekDays = data.week.days.map(d => {
    const units = d.units.filter(isStrength);
    return `
      <div class="day-col ${d.date === data.today.date ? "is-today" : ""}">
        <div class="day-col-head"><span class="day-name">${d.weekday}</span><span class="day-date">${fmtDateShort(d.date)}</span></div>
        ${units.length
          ? `<div class="stack" style="gap:6px;">${units.map(u => unitRowHtml(u, d.date, data.week.days, data.week.startDate)).join("")}</div>`
          : `<div class="card-note" style="margin-top:4px;">–</div>`}
      </div>`;
  }).join("");

  const seenNames = new Set();
  const referenceUnits = [];
  data.week.days.forEach(d => {
    d.units.filter(u => u.type === "kraft").forEach(u => {
      if (!seenNames.has(u.name)) { seenNames.add(u.name); referenceUnits.push(u); }
    });
  });
  const referenceCard = `
    <div>
      <div class="card-title" style="margin-bottom:10px;">Allgemeiner Plan</div>
      <div class="card-note" style="margin-bottom:10px;">Deine Kraft-Übungen unabhängig vom Wochentag, zum Nachschlagen</div>
      <div class="stack">${referenceUnits.map(strengthReferenceBlock).join("")}</div>
    </div>`;

  document.getElementById("tab-kraft").innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">Kraft</div>
      <div class="page-title">Kraft- &amp; EMOM-Programm</div>
      <div class="page-sub">Alle Kraft- und EMOM-Einheiten aus deinem Wochenplan an einem Ort</div>
    </div>

    <div class="stack">
      ${todayCard}
      <div class="card">
        <div class="card-head"><span class="card-title">Diese Woche</span></div>
        <div class="week-grid">${weekDays}</div>
      </div>
      ${referenceCard}
    </div>`;
}

/* ---------- render: Planänderungen / Anfragen (ueber GitHub Issues) ---------- */

let PLAN_REQUESTS_CACHE = null;

async function fetchPlanRequests() {
  const repo = typeof GITHUB_REPO !== "undefined" ? GITHUB_REPO : null;
  if (!repo) return { error: "Kein Repository konfiguriert (nur in der Online-Version verfügbar)." };
  try {
    const res = await fetch(`https://api.github.com/repos/${repo}/issues?labels=anfrage&state=all&per_page=20`, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!res.ok) throw new Error(`GitHub antwortete mit ${res.status}`);
    return { items: await res.json() };
  } catch (err) {
    return { error: String(err.message || err) };
  }
}

async function fetchIssueComments(issueNumber) {
  const repo = typeof GITHUB_REPO !== "undefined" ? GITHUB_REPO : null;
  if (!repo) return [];
  try {
    const res = await fetch(`https://api.github.com/repos/${repo}/issues/${issueNumber}/comments`, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!res.ok) return [];
    return await res.json();
  } catch { return []; }
}

const WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function mentionedDaysContext(text) {
  if (!text || typeof APP_DATA === "undefined" || !APP_DATA) return [];
  const lower = text.toLowerCase();
  return WEEKDAY_NAMES
    .filter(w => lower.includes(w.toLowerCase()))
    .map(w => APP_DATA.week.days.find(d => d.weekday === w))
    .filter(Boolean);
}

function findUnitMention(text) {
  if (!text || !APP_DATA) return null;
  const lower = text.toLowerCase();
  const candidates = [];
  APP_DATA.week.days.forEach(d => {
    d.units.forEach(u => {
      const key = u.name.split(/[\s-]/)[0].toLowerCase();
      if (key.length >= 4 && lower.includes(key)) candidates.push({ day: d, unit: u });
    });
  });
  candidates.sort((a, b) => b.unit.name.length - a.unit.name.length);
  return candidates[0] || null;
}

function suggestSwapForRequest(text) {
  if (!text || !APP_DATA) return null;
  const lower = text.toLowerCase();
  const targetDay = APP_DATA.week.days.find(d => lower.includes(d.weekday.toLowerCase()));
  if (!targetDay) return null;

  const mention = findUnitMention(text);
  if (!mention || mention.day.date === targetDay.date) return null;

  const sourceDay = mention.day;
  const sourceUnit = mention.unit;
  const targetUnit = targetDay.units.find(u => u.tag === "pflicht" && u.type !== "kraft");
  if (!targetUnit || targetUnit.name === sourceUnit.name) return null;

  const warnings = [];
  if (sourceUnit.keySession) warnings.push(`"${sourceUnit.name}" ist eine Schlüsseleinheit – nicht ideal zum Verschieben`);
  if (targetUnit.keySession) warnings.push(`"${targetUnit.name}" ist eine Schlüsseleinheit – nicht ideal zum Verschieben`);
  if (sourceDay.units.some(u => u.keySession && u.name !== sourceUnit.name)) {
    warnings.push(`An ${sourceDay.weekday} steht noch eine andere Schlüsseleinheit an`);
  }
  if (targetDay.units.some(u => u.keySession && u.name !== targetUnit.name)) {
    warnings.push(`An ${targetDay.weekday} steht noch eine andere Schlüsseleinheit an`);
  }

  return { sourceDay, sourceUnit, targetDay, targetUnit, warnings };
}

function swapSuggestionHtml(sug, issueNumber) {
  return `
    <div class="swap-suggestion" style="margin-top:8px; padding:10px; border-radius:8px; background:var(--surface-2);">
      <div class="card-note"><b>Vorschlag:</b> „${escapeHtml(sug.sourceUnit.name)}" (${sug.sourceDay.weekday}) ↔ „${escapeHtml(sug.targetUnit.name)}" (${sug.targetDay.weekday}) tauschen</div>
      <div class="card-note" style="margin-top:6px; color:${sug.warnings.length ? "var(--amber)" : "var(--teal)"};">
        Meine Einschätzung: ${sug.warnings.length ? sug.warnings.map(escapeHtml).join("; ") : "sieht unproblematisch aus."}
      </div>
      <div style="display:flex; gap:8px; margin-top:8px;">
        <button class="btn-small apply-swap-btn" type="button"
          data-source-date="${sug.sourceDay.date}" data-source-weekday="${sug.sourceUnit.homeWeekday}" data-source-unit="${escapeHtml(sug.sourceUnit.name)}"
          data-target-date="${sug.targetDay.date}" data-target-weekday="${sug.targetUnit.homeWeekday}" data-target-unit="${escapeHtml(sug.targetUnit.name)}"
          style="background:var(--teal); color:#fff;">✓ Tauschen</button>
        <button class="btn-small dismiss-swap-btn" type="button" data-issue-number="${issueNumber}">✗ Verwerfen</button>
      </div>
    </div>`;
}

function dayContextHtml(day) {
  const unitsHtml = day.units.length
    ? day.units.map(u => `<div class="day-mini-unit"><span style="flex:1;">${escapeHtml(u.name)}${u.keySession ? ' <span class="unit-key-badge">Key</span>' : ""}</span>${moveSelectHtml(u, day.date, APP_DATA.week.days, APP_DATA.week.startDate)}${autoMoveButtonHtml(u)}</div>`).join("")
    : `<div class="card-note">Nichts geplant.</div>`;
  return `
    <div style="margin-top:8px; padding:10px; border-radius:8px; background:var(--surface-2);">
      <div class="card-note" style="margin-bottom:6px;"><b>${day.weekday} (${fmtDateShort(day.date)})</b> aktuell geplant – hier direkt verschieben, falls nötig:</div>
      ${unitsHtml}
    </div>`;
}

function requestItemHtml(issue, comments) {
  const isOpen = issue.state === "open";
  const commentsHtml = (comments || []).map(c => `
    <div class="qa-answer" style="margin-top:4px; padding-left:10px; border-left:2px solid var(--ocean-600);">${escapeHtml(c.body)}</div>`).join("");
  const fullText = `${issue.title} ${issue.body || ""}`;
  const swap = (canEdit() && isOpen && !isSwapDismissed(issue.number)) ? suggestSwapForRequest(fullText) : null;
  const days = (canEdit() && isOpen && !swap) ? mentionedDaysContext(fullText) : [];
  return `
    <div class="qa-item" data-issue-number="${issue.number}">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
        <span class="qa-question">${escapeHtml(issue.title)}</span>
        <span class="tag ${isOpen ? "ergaenzung" : "pflicht"}">${isOpen ? "offen" : "erledigt"}</span>
      </div>
      ${issue.body && issue.body.trim() !== issue.title.trim() ? `<div class="qa-answer" style="margin-top:4px;">${escapeHtml(issue.body.slice(0, 300))}</div>` : ""}
      ${commentsHtml}
      <div class="card-note" style="margin-top:6px;">${new Date(issue.created_at).toLocaleDateString("de-DE")}</div>
      ${swap ? swapSuggestionHtml(swap, issue.number) : days.map(dayContextHtml).join("")}
      ${(canEdit() && isOpen) ? `
        <div style="display:flex; gap:8px; margin-top:8px;">
          <input type="text" class="text-input reply-request-input" placeholder="Antwort schreiben (optional)…" style="flex:1;" />
          <button class="btn-small reply-request-btn" type="button" data-issue-number="${issue.number}">Antworten &amp; schließen</button>
        </div>
        <div class="card-note reply-request-status" style="margin-top:4px;"></div>` : ""}
    </div>`;
}

async function renderRequestsList(result) {
  const list = document.getElementById("requests-list");
  if (!list) return;
  if (result.error) {
    list.innerHTML = `<div class="card-note">Konnte Anfragen nicht laden: ${escapeHtml(result.error)}</div>`;
    return;
  }
  if (!result.items.length) {
    list.innerHTML = `<div class="card-note">Noch keine Anfragen.</div>`;
    return;
  }
  list.innerHTML = `<div class="card-note">Lade…</div>`;
  const allComments = await Promise.all(result.items.map(issue => fetchIssueComments(issue.number)));
  list.innerHTML = result.items.map((issue, i) => requestItemHtml(issue, allComments[i])).join("");

  list.querySelectorAll(".reply-request-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const item = btn.closest("[data-issue-number]");
      const input = item.querySelector(".reply-request-input");
      const statusEl = item.querySelector(".reply-request-status");
      const replyText = input.value.trim();
      if (!replyText) return;
      replyToRequest(Number(btn.dataset.issueNumber), replyText, statusEl, btn);
    });
  });

  list.querySelectorAll(".apply-swap-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const d = btn.dataset;
      const weekStart = APP_DATA.week.startDate;
      setMoveOverride(weekStart, d.sourceWeekday, d.sourceUnit, d.targetDate);
      setMoveOverride(weekStart, d.targetWeekday, d.targetUnit, d.sourceDate);
      renderAll();
      btn.closest(".swap-suggestion").innerHTML = `<div class="card-note" style="color:var(--teal);">Getauscht.</div>`;
    });
  });
  list.querySelectorAll(".dismiss-swap-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      setSwapDismissed(btn.dataset.issueNumber);
      btn.closest(".swap-suggestion").remove();
    });
  });
}

async function replyToRequest(issueNumber, replyText, statusEl, btn) {
  const adminKey = getAdminKey();
  if (!adminKey) {
    statusEl.style.color = "var(--amber, orange)";
    statusEl.textContent = 'Erst im "Logins"-Tab den Freischalt-Code eingeben und speichern.';
    return;
  }
  btn.disabled = true;
  statusEl.style.color = "";
  statusEl.textContent = "Sende Antwort…";
  try {
    const res = await fetch(HOSTED_SYNC_WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "reply-request", issueNumber, replyText, adminKey }),
    });
    const result = await res.json();
    if (!result.ok) throw new Error(result.error || "Unbekannter Fehler");
    statusEl.style.color = "var(--teal)";
    statusEl.textContent = "Beantwortet und geschlossen.";
    setTimeout(() => { PLAN_REQUESTS_CACHE = null; renderPlanaenderungen(); }, 1500);
  } catch (err) {
    statusEl.style.color = "var(--amber, orange)";
    statusEl.textContent = `Fehler: ${err.message || err}`;
    btn.disabled = false;
  }
}

function renderPlanaenderungen() {
  const panel = document.getElementById("tab-planaenderungen");
  if (!panel) return;
  const repoConfigured = typeof GITHUB_REPO !== "undefined";

  panel.innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">Anfragen</div>
      <div class="page-title">Planänderungen &amp; Anfragen</div>
      <div class="page-sub">Für Trainingspartner: hier eine Nachricht hinterlassen (z. B. Terminwunsch)</div>
    </div>

    <div class="stack">
      ${repoConfigured ? `
      <div class="card">
        <div class="card-head"><span class="card-title">Neue Anfrage</span></div>
        <textarea id="request-text" class="note-box" placeholder="z. B. „Ich würde gerne Donnerstag um 12 Uhr mit Willi laufen“"></textarea>
        <button id="request-send-btn" class="btn-small" type="button" style="margin-top:10px;">Anfrage senden</button>
        <div class="card-note request-send-status" style="margin-top:6px;"></div>
      </div>` : `
      <div class="card"><div class="card-note">Anfragen funktionieren nur in der online gehosteten Version.</div></div>`}

      <div class="card">
        <div class="card-head"><span class="card-title">Bisherige Anfragen</span><span class="card-note"><span id="requests-refresh" style="cursor:pointer; text-decoration:underline;">aktualisieren</span></span></div>
        <div id="requests-list" class="stack" style="gap:8px;"><div class="card-note">Lade…</div></div>
      </div>
    </div>`;

  const sendBtn = document.getElementById("request-send-btn");
  const sendStatus = panel.querySelector(".request-send-status");
  if (sendBtn) {
    sendBtn.addEventListener("click", async () => {
      const textEl = document.getElementById("request-text");
      const text = textEl.value.trim();
      if (!text) return;
      sendBtn.disabled = true;
      sendStatus.style.color = "";
      sendStatus.textContent = "Sende…";
      try {
        const title = text.length > 60 ? text.slice(0, 57) + "…" : text;
        const res = await fetch(HOSTED_SYNC_WORKER_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "create-request", title, body: text }),
        });
        const result = await res.json();
        if (!result.ok) throw new Error(result.error || "Unbekannter Fehler");
        textEl.value = "";
        sendStatus.style.color = "var(--teal)";
        sendStatus.textContent = "Anfrage gesendet.";
        PLAN_REQUESTS_CACHE = null;
        loadAndRender();
      } catch (err) {
        sendStatus.style.color = "var(--amber, orange)";
        sendStatus.textContent = `Fehler: ${err.message || err}`;
      } finally {
        sendBtn.disabled = false;
      }
    });
  }

  const refreshEl = document.getElementById("requests-refresh");
  const loadAndRender = () => fetchPlanRequests().then(result => { PLAN_REQUESTS_CACHE = result; renderRequestsList(result); });
  if (refreshEl) refreshEl.addEventListener("click", loadAndRender);

  if (PLAN_REQUESTS_CACHE) {
    renderRequestsList(PLAN_REQUESTS_CACHE);
  } else if (repoConfigured) {
    loadAndRender();
  }
}

/* ---------- render: Logins (nur Owner) ---------- */

let LOGIN_REQUESTS_CACHE = null;
const ADMIN_KEY_STORAGE = "basisAdminKey";

function getAdminKey() {
  try { return localStorage.getItem(ADMIN_KEY_STORAGE) || ""; } catch { return ""; }
}
function setAdminKey(key) {
  try { localStorage.setItem(ADMIN_KEY_STORAGE, key.trim()); } catch { /* ignore */ }
}

async function fetchLoginRequests() {
  const repo = typeof GITHUB_REPO !== "undefined" ? GITHUB_REPO : null;
  if (!repo) return { error: "Kein Repository konfiguriert." };
  try {
    const res = await fetch(`https://api.github.com/repos/${repo}/issues?labels=login-request&state=open&per_page=20`, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!res.ok) throw new Error(`GitHub antwortete mit ${res.status}`);
    return { items: await res.json() };
  } catch (err) {
    return { error: String(err.message || err) };
  }
}

function parseLoginRequestBody(issue) {
  const body = issue.body || "";
  const userMatch = body.match(/Benutzername:\s*(\S+)/i);
  const credMatch = body.match(/Credential[^:]*:\s*([0-9a-f]{16,})/i);
  return {
    username: userMatch ? userMatch[1] : issue.title.replace(/^Login-Anfrage:\s*/i, "").trim(),
    credential: credMatch ? credMatch[1] : null,
  };
}

function loginRequestItemHtml(issue) {
  const { username, credential } = parseLoginRequestBody(issue);
  const command = credential ? `python approve_login.py ${username} ${credential}` : null;
  return `
    <div class="qa-item" data-request-item data-issue-number="${issue.number}">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
        <span class="qa-question">${escapeHtml(username)}</span>
        <div style="display:flex; gap:6px;">
          <button class="btn-small approve-login-btn" type="button" data-issue-number="${issue.number}" data-username="${escapeHtml(username)}" style="padding:6px 12px; font-size:12px; background:var(--teal); color:#fff;">✓ Freischalten</button>
          <a href="${issue.html_url}" target="_blank" rel="noopener" class="btn-small" style="text-decoration:none; padding:6px 12px; font-size:12px;">GitHub</a>
        </div>
      </div>
      <div class="card-note approve-status" style="margin-top:8px;"></div>
      ${command
        ? `<div class="card-note" style="margin-top:10px; opacity:.6;">Alternative falls die Automatik mal ausfällt (lokal im sync-Ordner, dann committen &amp; pushen):</div>
           <div class="exercise-row" style="opacity:.6;">
             <span class="exercise-name" style="font-family:var(--font-display); font-size:11px; word-break:break-all;">${escapeHtml(command)}</span>
             <button class="btn-small copy-cmd-btn" type="button" data-cmd="${escapeHtml(command)}" style="padding:6px 10px; font-size:11px;">Kopieren</button>
           </div>`
        : ""}
    </div>`;
}

async function approveLoginRequest(issueNumber, statusEl, btn) {
  const adminKey = getAdminKey();
  if (!adminKey) {
    statusEl.style.color = "var(--amber, orange)";
    statusEl.textContent = "Erst oben den Freischalt-Code eingeben und speichern.";
    return;
  }
  btn.disabled = true;
  statusEl.textContent = "Wird freigeschaltet…";
  statusEl.style.color = "";
  try {
    const res = await fetch(HOSTED_SYNC_WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "approve-login", issueNumber, adminKey }),
    });
    const result = await res.json();
    if (!result.ok) throw new Error(result.error || "Unbekannter Fehler");
    statusEl.style.color = "var(--teal)";
    statusEl.textContent = "Freigeschaltet, warte auf Bestätigung…";
    for (let i = 0; i < 10; i++) {
      await new Promise(r => setTimeout(r, 3000));
      try {
        const config = await fetchFileViaGithubApi("data/auth-config.json");
        const username = btn.dataset.username;
        if (config.users && username && config.users[username]) {
          CURRENT_AUTH_CONFIG = config;
          break;
        }
      } catch { /* naechster Versuch */ }
    }
    LOGIN_REQUESTS_CACHE = null;
    renderLogins();
  } catch (err) {
    if (String(err.message || err).includes("Freischalt-Code")) setAdminKey("");
    statusEl.style.color = "var(--amber, orange)";
    statusEl.textContent = `Fehler: ${err.message || err}`;
    btn.disabled = false;
  }
}

function renderLoginRequestsList(result) {
  const list = document.getElementById("login-requests-list");
  if (!list) return;
  if (result.error) {
    list.innerHTML = `<div class="card-note">Konnte Anfragen nicht laden: ${escapeHtml(result.error)}</div>`;
    return;
  }
  if (!result.items.length) {
    list.innerHTML = `<div class="card-note">Keine offenen Anfragen.</div>`;
    return;
  }
  list.innerHTML = result.items.map(loginRequestItemHtml).join("");
}

function renderLogins() {
  const panel = document.getElementById("tab-logins");
  if (!panel) return;
  if (typeof CURRENT_ROLE !== "undefined" && CURRENT_ROLE !== "owner") { panel.innerHTML = ""; return; }

  const usersMap = (typeof CURRENT_AUTH_CONFIG !== "undefined" && CURRENT_AUTH_CONFIG && CURRENT_AUTH_CONFIG.users) || {};
  const approvedUsers = Object.keys(usersMap)
    .map(u => ({ username: u, role: usersMap[u].role || "viewer" }))
    .sort((a, b) => (a.role === "owner" ? -1 : 0) - (b.role === "owner" ? -1 : 0));

  panel.innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">Logins</div>
      <div class="page-title">Zugänge verwalten</div>
      <div class="page-sub">Nur für dich als Owner sichtbar</div>
    </div>

    <div class="stack">
      <div class="card">
        <div class="card-head">
          <span class="card-title">Freischalt-Code</span>
          <span class="card-note">Schützt "Freischalten" unten – nur du kennst ihn</span>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <input type="password" id="admin-key-field" class="login-input" style="max-width:260px;"
            autocapitalize="off" autocorrect="off" autocomplete="off" spellcheck="false"
            placeholder="Freischalt-Code" value="${escapeHtml(getAdminKey())}" />
          <button id="admin-key-save" class="btn-small" type="button" style="padding:8px 14px;">Speichern</button>
          <span id="admin-key-status" class="card-note"></span>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <span class="card-title">Offene Login-Anfragen</span>
          <span class="card-note"><span id="logins-refresh" style="cursor:pointer; text-decoration:underline;">aktualisieren</span></span>
        </div>
        <div id="login-requests-list" class="stack" style="gap:8px;"><div class="card-note">Lade…</div></div>
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Freigeschaltete Logins</span></div>
        ${approvedUsers.length
          ? `<div class="stack" style="gap:6px;">${approvedUsers.map(u => `
              <div class="day-mini-unit">
                <span style="flex:1;">${escapeHtml(u.username)}</span>
                <span class="tag ${u.role === "owner" ? "pflicht" : "ergaenzung"}">${u.role === "owner" ? "Owner" : "viewer"}</span>
                <button class="btn-small logout-user-btn" type="button" data-username="${escapeHtml(u.username)}" style="padding:4px 10px; font-size:11px; margin-left:8px; background:var(--amber, #c07a1e); color:#fff;">Abmelden</button>
                <button class="btn-small revoke-user-btn" type="button" data-username="${escapeHtml(u.username)}" style="padding:4px 10px; font-size:11px; margin-left:6px; background:#c0392b; color:#fff;">Blockieren</button>
              </div>`).join("")}
             <div class="card-note revoke-status" style="margin-top:4px;"></div>`
          : `<div class="card-note">Noch niemand freigeschaltet.</div>`}
      </div>
    </div>`;

  const refreshEl = document.getElementById("logins-refresh");
  const loadAndRender = () => fetchLoginRequests().then(result => { LOGIN_REQUESTS_CACHE = result; renderLoginRequestsList(result); });
  if (refreshEl) refreshEl.addEventListener("click", loadAndRender);

  const adminKeyField = document.getElementById("admin-key-field");
  const adminKeySave = document.getElementById("admin-key-save");
  const adminKeyStatus = document.getElementById("admin-key-status");
  if (adminKeySave) adminKeySave.addEventListener("click", () => {
    setAdminKey(adminKeyField.value);
    adminKeyStatus.style.color = "var(--teal)";
    adminKeyStatus.textContent = "Gespeichert.";
    setTimeout(() => { adminKeyStatus.textContent = ""; }, 3000);
  });

  const listEl = document.getElementById("login-requests-list");
  if (listEl) listEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".approve-login-btn");
    if (!btn) return;
    const statusEl = btn.closest("[data-request-item]")?.querySelector(".approve-status");
    approveLoginRequest(Number(btn.dataset.issueNumber), statusEl, btn);
  });

  const revokeStatusEl = panel.querySelector(".revoke-status");
  panel.querySelectorAll(".revoke-user-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const username = btn.dataset.username;
      if (!window.confirm(`"${username}" wirklich blockieren? Kann sich danach nie wieder einloggen (nur per neuer Anfrage).`)) return;
      revokeUser(username, revokeStatusEl, btn);
    });
  });
  panel.querySelectorAll(".logout-user-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const username = btn.dataset.username;
      logoutUser(username, revokeStatusEl, btn);
    });
  });

  if (LOGIN_REQUESTS_CACHE) renderLoginRequestsList(LOGIN_REQUESTS_CACHE);
  else loadAndRender();
}

async function revokeUser(username, statusEl, btn) {
  const adminKey = getAdminKey();
  if (!adminKey) {
    if (statusEl) { statusEl.style.color = "var(--amber, orange)"; statusEl.textContent = "Erst oben den Freischalt-Code eingeben und speichern."; }
    return;
  }
  btn.disabled = true;
  if (statusEl) { statusEl.style.color = ""; statusEl.textContent = `Entferne "${username}"…`; }
  try {
    const res = await fetch(HOSTED_SYNC_WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "revoke-login", username, adminKey }),
    });
    const result = await res.json();
    if (!result.ok) throw new Error(result.error || "Unbekannter Fehler");
    if (statusEl) { statusEl.style.color = "var(--teal)"; statusEl.textContent = `"${username}" wird entfernt, dauert ca. 30 Sek…`; }
    for (let i = 0; i < 12; i++) {
      await new Promise(r => setTimeout(r, 5000));
      try {
        const config = await fetchFileViaGithubApi("data/auth-config.json");
        if (!config.users || !config.users[username]) {
          CURRENT_AUTH_CONFIG = config;
          if (statusEl) statusEl.textContent = `"${username}" entfernt.`;
          renderLogins();
          return;
        }
      } catch { /* naechster Versuch */ }
    }
    if (statusEl) statusEl.textContent = `Dauert länger als erwartet – Seite in Kürze neu laden.`;
  } catch (err) {
    if (statusEl) { statusEl.style.color = "var(--amber, orange)"; statusEl.textContent = `Fehler: ${err.message || err}`; }
    btn.disabled = false;
  }
}

async function logoutUser(username, statusEl, btn) {
  const adminKey = getAdminKey();
  if (!adminKey) {
    if (statusEl) { statusEl.style.color = "var(--amber, orange)"; statusEl.textContent = "Erst oben den Freischalt-Code eingeben und speichern."; }
    return;
  }
  btn.disabled = true;
  if (statusEl) { statusEl.style.color = ""; statusEl.textContent = `Melde "${username}" ab…`; }
  try {
    const res = await fetch(HOSTED_SYNC_WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "logout-login", username, adminKey }),
    });
    const result = await res.json();
    if (!result.ok) throw new Error(result.error || "Unbekannter Fehler");
    if (statusEl) { statusEl.style.color = "var(--teal)"; statusEl.textContent = `"${username}" wird beim nächsten Laden der Seite abgemeldet (Passwort bleibt gültig).`; }
  } catch (err) {
    if (statusEl) { statusEl.style.color = "var(--amber, orange)"; statusEl.textContent = `Fehler: ${err.message || err}`; }
  } finally {
    btn.disabled = false;
  }
}

/* ---------- boot ---------- */

let PRISTINE_DATA = null;

/* ---------- Airis: Mail-/Kalenderuebersicht (nur Owner) ---------- */

function renderAiris(data) {
  const panel = document.getElementById("tab-airis");
  if (!panel || typeof CURRENT_ROLE === "undefined" || CURRENT_ROLE !== "owner") return;
  if (!data) {
    panel.innerHTML = `
      <div class="page-head">
        <div class="page-eyebrow">Airis</div>
        <div class="page-title">Übersicht</div>
      </div>
      <div class="stack"><div class="card"><div class="card-note">Lade…</div></div></div>`;
    return;
  }

  const mailCard = (label, m) => {
    if (!m) return "";
    if (m.error) {
      return `
        <div class="card">
          <div class="card-head"><span class="card-title">${escapeHtml(label)}</span></div>
          <div class="card-note" style="color:var(--amber);">${escapeHtml(m.error)}</div>
        </div>`;
    }
    const items = (m.important || []).map(i => `
      <div class="qa-item" style="margin-bottom:6px;">
        <div class="qa-question" style="font-size:13px;">${escapeHtml(i.from)}</div>
        <div class="card-note">${escapeHtml(i.subject)}</div>
      </div>`).join("");
    return `
      <div class="card">
        <div class="card-head"><span class="card-title">${escapeHtml(label)}</span><span class="card-note">${m.unread} ungelesen</span></div>
        ${items || `<div class="card-note">Nichts Wichtiges offen.</div>`}
      </div>`;
  };

  const cal = data.calendar || {};
  const calBody = cal.error
    ? `<div class="card-note" style="color:var(--amber);">${escapeHtml(cal.error)}</div>`
    : ((cal.events || []).length
      ? cal.events.map(e => `
        <div class="day-mini-unit"><span style="flex:1;">${escapeHtml(e.summary)}<div class="unit-detail" style="margin-top:2px;">${escapeHtml(e.when)}${e.location ? " · " + escapeHtml(e.location) : ""}</div></span></div>`).join("")
      : `<div class="card-note">Keine anstehenden Termine gefunden.</div>`);

  const updated = data.syncedAt ? new Date(data.syncedAt).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "–";
  panel.innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">Airis</div>
      <div class="page-title">Übersicht</div>
      <div class="page-sub">Zuletzt aktualisiert: ${escapeHtml(updated)}</div>
    </div>
    <div class="stack">
      ${mailCard("GMX", data.mail && data.mail.gmx)}
      ${mailCard("iCloud", data.mail && data.mail.icloud)}
      <div class="card">
        <div class="card-head"><span class="card-title">Nächste Termine</span></div>
        ${calBody}
      </div>
    </div>`;
}

function renderAll(freshData) {
  if (freshData) PRISTINE_DATA = freshData;
  const data = structuredClone(PRISTINE_DATA);
  applyMoves(data);
  applyOverrides(data);
  APP_DATA = data;
  const sidenavGoalEl = document.getElementById("sidenav-goal");
  if (sidenavGoalEl) sidenavGoalEl.textContent = data.profile.goal.replace("Ultramarathon ", "");
  renderHeute(data);
  renderWoche(data);
  renderVerlauf(data);
  renderPerformance(data);
  renderCoach(data);
  renderKraft(data);
  renderPlanaenderungen(data);
  renderLogins();
  renderAiris();
}

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupInteractions();
  setupSyncButton();
  bootWithAuth(renderAll);
});
