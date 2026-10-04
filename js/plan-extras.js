/* Zusatzfunktionen rund um den Plan: Telegram-Zeiten, Verletzung, Schuhe, Backup,
   Gewichts-Tagebuch (Kraft), Wettkampf-Countdown. Ergänzt plan.js / plan-ui.js / plan-views.js. */

/* ---------------------------------------------------------------------------
   Telegram-Zeiten (werden vom Sync-Workflow ausgewertet, Berliner Zeit)
   --------------------------------------------------------------------------- */

const TG_DEFAULT = {
  morning: { on: true, time: "05:30" },
  evening: { on: true, time: "20:00" },
  weekly: { on: true, day: 6, time: "20:00" },
};
const TG_DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function tgSettings() {
  const t = (dpSettings().telegram) || {};
  return {
    morning: { ...TG_DEFAULT.morning, ...(t.morning || {}) },
    evening: { ...TG_DEFAULT.evening, ...(t.evening || {}) },
    weekly: { ...TG_DEFAULT.weekly, ...(t.weekly || {}) },
  };
}

function telegramSettingsHtml() {
  const t = tgSettings();
  return `
    <div class="card-title" style="margin:14px 0 6px; font-size:13px;">Telegram-Nachrichten</div>
    <div class="card-note" style="margin-bottom:8px;">Uhrzeiten in deutscher Zeit (Sommer-/Winterzeit automatisch). Kommt eine Nachricht verspätet, wird sie bis zu 3 Stunden nachgeholt.</div>
    <div class="grid grid-2" style="gap:10px;">
      <div style="display:flex; gap:8px; align-items:center;"><label class="card-note" style="flex:1;"><input type="checkbox" id="tg-m-on" ${t.morning.on ? "checked" : ""} /> Morgens: was heute ansteht</label><input type="time" id="tg-m-time" class="text-input" value="${escapeHtml(t.morning.time)}" style="max-width:110px;" /></div>
      <div style="display:flex; gap:8px; align-items:center;"><label class="card-note" style="flex:1;"><input type="checkbox" id="tg-e-on" ${t.evening.on ? "checked" : ""} /> Abends: was morgen ansteht</label><input type="time" id="tg-e-time" class="text-input" value="${escapeHtml(t.evening.time)}" style="max-width:110px;" /></div>
      <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
        <label class="card-note" style="flex:1;"><input type="checkbox" id="tg-w-on" ${t.weekly.on ? "checked" : ""} /> Wochenrückblick am</label>
        <select id="tg-w-day" class="move-select">${TG_DAYS.map((d, i) => `<option value="${i}" ${i === t.weekly.day ? "selected" : ""}>${d}</option>`).join("")}</select>
        <input type="time" id="tg-w-time" class="text-input" value="${escapeHtml(t.weekly.time)}" style="max-width:110px;" />
      </div>
    </div>`;
}

function readTelegramSettings() {
  const g = (id) => document.getElementById(id);
  const time = (id, fallback) => (/^\d{2}:\d{2}$/.test(g(id).value) ? g(id).value : fallback);
  return {
    morning: { on: g("tg-m-on").checked, time: time("tg-m-time", "05:30") },
    evening: { on: g("tg-e-on").checked, time: time("tg-e-time", "20:00") },
    weekly: { on: g("tg-w-on").checked, day: Number(g("tg-w-day").value), time: time("tg-w-time", "20:00") },
  };
}

/* ---------------------------------------------------------------------------
   Verletzung / Beschwerden
   --------------------------------------------------------------------------- */

const INJURY_AREAS = [["knie", "Knie"], ["fuss", "Fuß/Achillessehne"], ["wade", "Wade/Schienbein"],
  ["muskelkater", "Muskelkater"], ["ruecken", "Rücken"], ["sonstiges", "Sonstiges"]];

function activeInjury() {
  const inj = planInputs().injury;
  if (!inj || !inj.from) return null;
  if (inj.to && inj.to < isoToday()) return null;
  return inj;
}

function injuryRowHtml() {
  if (!canEdit()) return "";
  const inj = activeInjury();
  const label = (a) => (INJURY_AREAS.find(x => x[0] === a) || [0, "Beschwerden"])[1];
  if (inj) {
    return `
      <div style="margin-top:10px; padding-top:10px; border-top:1px solid var(--line, #ffffff22);">
        <div class="card-note" style="margin-bottom:6px; color:var(--amber);">Beschwerden eingetragen: ${escapeHtml(label(inj.area))} seit ${dpFmtDate(inj.from)}${inj.to ? ` (bis ${dpFmtDate(inj.to)})` : ""}. Der Plan nimmt Lauf/Beine/harte Einheiten raus, soweit nötig.</div>
        <button class="btn-small" type="button" data-inj-act="end">Wieder schmerzfrei</button>
      </div>`;
  }
  return `
    <div style="margin-top:10px; padding-top:10px; border-top:1px solid var(--line, #ffffff22); display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
      <span class="card-note">Tut dir etwas weh?</span>
      <select id="inj-area" class="move-select">${INJURY_AREAS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
      <button class="btn-small" type="button" data-inj-act="start">Eintragen</button>
    </div>`;
}

function setInjury(area) {
  const label = (INJURY_AREAS.find(x => x[0] === area) || [0, "Beschwerden"])[1];
  return applyPlanChange(`${label}: Plan angepasst`, plan => { plan.injury = { area, from: isoToday(), to: null }; });
}

function endInjury() {
  return applyPlanChange("Wieder schmerzfrei – Plan baut langsam wieder auf", plan => {
    if (plan.injury) plan.injury = { ...plan.injury, to: isoToday() };
  });
}

function bindInjury(root) {
  if (!root) return;
  root.querySelectorAll("[data-inj-act]").forEach(btn => btn.addEventListener("click", () => {
    if (btn.dataset.injAct === "start") setInjury(document.getElementById("inj-area").value);
    else endInjury();
  }));
}

/* ---------------------------------------------------------------------------
   Laufschuhe (Kilometer werden im Sync aus Garmin gezählt)
   --------------------------------------------------------------------------- */

function shoesListFromState(data) {
  const mine = planInputs().shoes || [];
  const computed = (data.planState && data.planState.shoes) || [];
  return mine.map(s => ({ ...s, km: (computed.find(c => c.id === s.id) || {}).km }));
}

function shoesCardHtml(data) {
  const shoes = shoesListFromState(data);
  const edit = canEdit();
  if (!shoes.length && !edit) return "";
  const rows = shoes.map(s => {
    const retire = s.retireKm || 700;
    const km = typeof s.km === "number" ? s.km : null;
    const warn = km !== null && km >= 0.9 * retire && !s.retired;
    return `
      <div class="shoe-row" data-id="${escapeHtml(s.id)}" style="${s.retired ? "opacity:.55;" : ""}">
        ${km !== null ? progressBar({ name: `${escapeHtml(s.name)}${s.retired ? " (ausgemustert)" : ""}`, value: km, target: retire, unit: " km", decimals: 0, variant: warn ? "low" : "" })
          : `<div class="bar-top"><span class="name">${escapeHtml(s.name)}</span><span class="value">wird beim nächsten Sync gezählt</span></div>`}
        <div class="card-note" style="margin:2px 0 6px;">seit ${dpFmtDate(s.startDate)} ${escapeHtml(s.startDate.slice(0, 4))}${warn ? ' · <span style="color:var(--amber);">bald ersetzen</span>' : ""}</div>
        ${edit ? `<div style="display:flex; gap:6px; margin-bottom:10px;">
          <button class="btn-small shoe-retire" type="button">${s.retired ? "Wieder aktiv" : "Ausmustern"}</button>
          <button class="btn-small shoe-del" type="button">Löschen</button></div>` : ""}
      </div>`;
  }).join("");
  return `
    <div class="card" id="shoes-card">
      <div class="card-head"><span class="card-title">Laufschuhe</span><span class="card-note">Kilometer aus deinen Garmin-Läufen</span></div>
      ${rows || '<div class="card-note">Noch kein Paar eingetragen.</div>'}
      ${edit ? `
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end; margin-top:6px;">
        <label class="card-note">Schuh<input type="text" id="shoe-name" class="text-input" placeholder="z. B. Brooks Ghost 18" style="min-width:160px;" /></label>
        <label class="card-note">Ab Datum<input type="date" id="shoe-start" class="text-input" value="${isoToday()}" style="max-width:160px;" /></label>
        <label class="card-note">Ersetzen bei (km)<input type="number" id="shoe-retire" class="text-input" value="700" min="100" max="2000" style="max-width:110px;" /></label>
        <label class="card-note">Schon gelaufen (km)<input type="number" id="shoe-startkm" class="text-input" value="0" min="0" style="max-width:110px;" /></label>
        <button class="btn-small" type="button" id="shoe-add">Hinzufügen</button>
      </div>` : ""}
    </div>`;
}

function bindShoes() {
  const card = document.getElementById("shoes-card");
  if (!card || !canEdit()) return;
  const add = document.getElementById("shoe-add");
  if (add) add.addEventListener("click", () => {
    const name = document.getElementById("shoe-name").value.trim();
    const startDate = document.getElementById("shoe-start").value || isoToday();
    if (!name) { planToast("Bitte einen Namen eintragen", "", 3000); return; }
    const shoe = {
      id: "s-" + Date.now().toString(36), name, startDate,
      retireKm: Math.max(100, Number(document.getElementById("shoe-retire").value) || 700),
      startKm: Math.max(0, Number(document.getElementById("shoe-startkm").value) || 0),
    };
    applyPlanChange(`${name} eingetragen`, plan => { plan.shoes = [...(plan.shoes || []), shoe]; });
  });
  card.querySelectorAll(".shoe-row").forEach(row => {
    const id = row.dataset.id;
    const retire = row.querySelector(".shoe-retire"), del = row.querySelector(".shoe-del");
    if (retire) retire.addEventListener("click", () => applyPlanChange("Schuh aktualisiert", plan => {
      const s = (plan.shoes || []).find(x => x.id === id);
      if (s) s.retired = !s.retired;
    }));
    if (del) del.addEventListener("click", () => {
      if (!confirm("Dieses Paar wirklich löschen?")) return;
      applyPlanChange("Schuh gelöscht", plan => { plan.shoes = (plan.shoes || []).filter(x => x.id !== id); });
    });
  });
}

/* ---------------------------------------------------------------------------
   Backup / Wiederherstellen (alle eigenen Eingaben, als Datei)
   --------------------------------------------------------------------------- */

function backupCardHtml() {
  if (!canEdit()) return "";
  return `
    <div class="card">
      <div class="card-head"><span class="card-title">Backup</span><span class="card-note">Dienstplan, Termine, Einstellungen, Übungen, Gewichte, Schuhe</span></div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
        <button class="btn-small" type="button" id="bk-download">Backup herunterladen</button>
        <label class="btn-small" style="cursor:pointer;">Backup einspielen<input type="file" id="bk-upload" accept=".json,application/json" style="display:none;" /></label>
      </div>
      <div class="card-note" style="margin-top:6px;">Die Datei enthält deinen Dienstplan – nicht öffentlich weitergeben.</div>
    </div>`;
}

function downloadBackup() {
  const payload = { app: "willis-dashboard", version: 1, exportedAt: new Date().toISOString(), overrides: loadOverrides() };
  const blob = new Blob([JSON.stringify(payload, null, 1)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `willi-backup-${isoToday()}.json`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  planToast("Backup gespeichert", "Die Datei liegt in deinen Downloads.", 5000);
}

async function restoreBackup(file) {
  let obj;
  try { obj = JSON.parse(await file.text()); } catch { planToast("Datei nicht lesbar", "Das ist keine gültige Backup-Datei.", 6000); return; }
  const ov = obj && obj.app === "willis-dashboard" ? obj.overrides : null;
  if (!ov || typeof ov !== "object" || Array.isArray(ov)) { planToast("Keine Backup-Datei von Willis Dashboard", "", 6000); return; }
  const n = ((ov.__plan || {}).shifts ? Object.keys(ov.__plan.shifts).length : 0);
  if (!confirm(`Backup vom ${(obj.exportedAt || "").slice(0, 10)} einspielen?\n(${n} Schichttage) Deine aktuellen Eingaben werden dadurch ersetzt.`)) return;
  saveOverrides(ov, { push: false });
  await applyPlanChange("Backup eingespielt", () => {});
}

function bindBackup() {
  const dl = document.getElementById("bk-download"), up = document.getElementById("bk-upload");
  if (dl) dl.addEventListener("click", downloadBackup);
  if (up) up.addEventListener("change", (e) => { if (e.target.files[0]) restoreBackup(e.target.files[0]); e.target.value = ""; });
}

/* ---------------------------------------------------------------------------
   Gewichts-Tagebuch (Kraft): Gewicht je Übung, Verlauf als Grafik
   --------------------------------------------------------------------------- */

/** Beim Speichern der Bibliothek: geänderte Gewichte ins Tagebuch schreiben. */
function logWeightChanges(plan, oldEntry, newEntry) {
  plan.weightLog = plan.weightLog || {};
  const today = isoToday();
  const old = Object.fromEntries(((oldEntry && oldEntry.exercises) || []).map(e => [e.name, e]));
  (newEntry.exercises || []).forEach(e => {
    if (!(e.weightKg > 0)) return;
    const prev = old[e.name];
    const list = plan.weightLog[e.name] = plan.weightLog[e.name] || [];
    const last = list[list.length - 1];
    if (last && last.kg === e.weightKg && last.reps === e.reps) return;
    if (!prev || prev.weightKg !== e.weightKg || !last) {
      const same = list.findIndex(x => x.date === today);
      const entry = { date: today, kg: e.weightKg, reps: e.reps, sets: e.sets };
      if (same >= 0) list[same] = entry; else list.push(entry);
    }
  });
}

function kraftWeightLogHtml() {
  const log = planInputs().weightLog || {};
  const names = Object.keys(log).filter(n => (log[n] || []).length);
  if (!names.length) {
    return `<div class="card"><div class="card-head"><span class="card-title">Gewichts-Tagebuch</span></div>
      <div class="card-note">Trag in der Übungsbibliothek (oben aufklappen) bei einer Übung das Gewicht in kg ein – jede Änderung landet hier mit Verlauf.</div></div>`;
  }
  const cards = names.sort().map(n => {
    const list = log[n].slice().sort((a, b) => a.date.localeCompare(b.date));
    const last = list[list.length - 1], first = list[0];
    const diff = last.kg - first.kg;
    return `
      <div class="card">
        <div class="card-head"><span class="card-title" style="text-transform:none; font-size:14px;">${escapeHtml(n)}</span>
          <span class="card-note">${escapeHtml(last.kg)} kg${last.reps ? " · " + escapeHtml(last.sets || "") + "×" + escapeHtml(last.reps) : ""}${list.length > 1 ? ` · ${diff >= 0 ? "+" : ""}${diff.toFixed(1).replace(".0", "")} kg seit ${fmtDateShort(first.date)}` : ""}</span></div>
        ${list.length > 1 ? lineChartSVG(list.map(x => ({ value: x.kg, label: fmtDateShort(x.date) })), { compact: true }) : '<div class="card-note">Erster Eintrag – ab dem zweiten Gewicht gibt es eine Kurve.</div>'}
      </div>`;
  }).join("");
  return `<div><div class="card-title" style="margin-bottom:10px;">Gewichts-Tagebuch</div><div class="grid-auto">${cards}</div></div>`;
}

/* ---------------------------------------------------------------------------
   Wettkampf-Countdown (Heute)
   --------------------------------------------------------------------------- */

function raceCountdownHtml(data) {
  const st = dpSettings();
  const race = st.raceDate;
  if (!race) return "";
  const days = Math.ceil((new Date(race + "T12:00:00") - new Date(isoToday() + "T12:00:00")) / 86400000);
  if (days < 0) return "";
  const weeks = Math.floor(days / 7);
  const label = `${st.raceName || "Wettkampf"}${st.raceDistanceKm ? " " + st.raceDistanceKm + " km" : ""}`;
  return `
    <div class="card" id="race-countdown">
      <div class="card-head"><span class="card-title">Countdown</span><span class="card-note">${escapeHtml(label)} · ${dpFmtDate(race)} ${race.slice(0, 4)}</span></div>
      <div class="stat-row">
        <div class="stat"><span class="stat-value">${days}<span class="unit">Tage</span></span><span class="stat-label">bis zum Wettkampf</span></div>
        <div class="stat"><span class="stat-value">${weeks}<span class="unit">Wochen</span></span><span class="stat-label">${days % 7} Tage extra</span></div>
      </div>
    </div>`;
}
