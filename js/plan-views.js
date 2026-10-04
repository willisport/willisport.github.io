/* Ansichten rund um den Plan: Kraft-Übungsbibliothek + Extra-Einheiten, Woche im Voraus,
   Coach-Vorschlag, Performance-Diagramme. Ergänzt plan-ui.js. */

/* ---------------------------------------------------------------------------
   Kraft: Übungsbibliothek (unabhängig vom Wochentag) + Extra-Einheiten einfügen
   --------------------------------------------------------------------------- */

const LIB_ORDER = ["emom1", "emom2", "heavyLegs", "legStabi", "legSupersets", "core", "armShoulders"];

function currentLibrary(data) {
  const base = JSON.parse(JSON.stringify((data && data.library) || {}));
  const mine = planInputs().library || {};
  Object.entries(mine).forEach(([k, v]) => { base[k] = { ...(base[k] || {}), ...v }; });
  return base;
}

function libKeys(lib) {
  const rest = Object.keys(lib).filter(k => !LIB_ORDER.includes(k)).sort();
  return [...LIB_ORDER.filter(k => lib[k]), ...rest];
}

function libExerciseRowHtml(e) {
  return `
    <div class="lib-ex" style="display:grid; grid-template-columns:minmax(120px,2fr) 60px minmax(70px,1fr) minmax(70px,1fr) 74px auto; gap:6px; align-items:center;">
      <input type="text" class="text-input lx-name" value="${escapeHtml(e.name)}" placeholder="Übung" />
      <input type="number" class="text-input lx-sets" value="${escapeHtml(e.sets)}" min="1" placeholder="Sätze" />
      <input type="text" class="text-input lx-reps" value="${escapeHtml(e.reps)}" placeholder="Wdh." />
      <input type="text" class="text-input lx-rest" value="${escapeHtml(e.rest)}" placeholder="Pause" />
      <input type="number" class="text-input lx-kg" value="${e.weightKg ? escapeHtml(e.weightKg) : ""}" placeholder="kg" step="0.5" min="0" />
      <button class="btn-small lx-del" type="button" title="Übung entfernen">✕</button>
    </div>`;
}

function kraftLibraryHtml(data) {
  const lib = currentLibrary(data);
  const edit = canEdit();
  const cards = libKeys(lib).map(key => {
    const e = lib[key];
    const exs = e.exercises || [];
    const body = edit ? `
      <div class="grid grid-2" style="gap:8px; margin:8px 0;">
        <label class="card-note">Name<input type="text" class="text-input lb-name" value="${escapeHtml(e.name)}" /></label>
        <label class="card-note">Dauer (Min)<input type="number" class="text-input lb-dur" value="${escapeHtml(e.durationMin || 15)}" min="1" /></label>
      </div>
      <label class="card-note" style="display:block; margin-bottom:8px;">Kurztext im Plan<input type="text" class="text-input lb-detail" value="${escapeHtml(e.detail || "")}" /></label>
      <div class="card-note" style="display:grid; grid-template-columns:minmax(120px,2fr) 60px minmax(70px,1fr) minmax(70px,1fr) 74px auto; gap:6px; margin-bottom:4px;"><span>Übung</span><span>Sätze</span><span>Wdh.</span><span>Pause</span><span>Gewicht</span><span></span></div>
      <div class="stack lib-exs" style="gap:6px;">${exs.map(libExerciseRowHtml).join("")}</div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;">
        <button class="btn-small lb-add" type="button">+ Übung</button>
        <button class="btn-small lb-save" type="button">Speichern</button>
        <button class="btn-small lb-reset" type="button" title="Eigene Änderungen verwerfen">Auf Standard</button>
      </div>` : `
      <div class="exercise-list">${exs.map(x => `<div class="exercise-row"><span class="exercise-name">${escapeHtml(x.name)}</span><span class="exercise-spec">${escapeHtml(x.sets)}×${escapeHtml(x.reps)}${x.weightKg ? " · " + escapeHtml(x.weightKg) + " kg" : ""} · ${escapeHtml(x.rest)} Pause</span></div>`).join("")}</div>`;
    return `
      <details class="card lib-card" data-lib-key="${escapeHtml(key)}">
        <summary style="cursor:pointer; display:flex; justify-content:space-between; gap:8px;">
          <span class="card-title" style="text-transform:none; font-size:15px;">${escapeHtml(e.name)}</span>
          <span class="card-note">${exs.length} Übungen · ~${escapeHtml(e.durationMin || "")} min</span>
        </summary>
        <div class="card-note" style="margin-top:6px;">${escapeHtml(e.detail || "")}</div>
        ${body}
      </details>`;
  }).join("");
  return `
    <div>
      <div class="card-title" style="margin-bottom:10px;">Übungsbibliothek</div>
      <div class="card-note" style="margin-bottom:10px;">Unabhängig vom Wochentag. ${edit ? "Aufklappen, Übungen/Sätze/Wiederholungen ändern, speichern – der Plan übernimmt es bei der nächsten Berechnung." : ""}</div>
      <div class="stack" style="gap:8px;">${cards}</div>
      ${edit ? `<div style="margin-top:10px;"><button class="btn-small" type="button" id="lib-new">+ Neue Übungsgruppe</button></div>` : ""}
    </div>`;
}

function kraftExtrasHtml(data) {
  if (!canEdit()) return "";
  const lib = currentLibrary(data);
  const ex = loadOverrides().__extras || {};
  const today = isoToday();
  const list = Object.keys(ex).filter(d => d >= today).sort().flatMap(d => ex[d].map((x, i) => ({ d, i, x })));
  return `
    <div class="card">
      <div class="card-head"><span class="card-title">Einheit in den Plan einfügen</span><span class="card-note">z. B. zusätzliches Bein-Stabi am Samstag</span></div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
        <select id="ex-key" class="move-select">${libKeys(lib).map(k => `<option value="${escapeHtml(k)}">${escapeHtml(lib[k].name)}</option>`).join("")}</select>
        <input type="date" id="ex-date" class="text-input" value="${today}" style="max-width:160px;" />
        <input type="time" id="ex-time" class="text-input" style="max-width:110px;" />
        <button class="btn-small" type="button" id="ex-add">Einfügen</button>
      </div>
      ${list.length ? `<div class="stack" style="gap:6px; margin-top:10px;">${list.map(r => `
        <div class="unit" style="display:flex; gap:8px; align-items:center;">
          <strong style="width:84px;">${dpFmtDate(r.d)}</strong><span style="flex:1;">${escapeHtml((lib[r.x.key] || {}).name || r.x.key)}${r.x.time ? " · " + escapeHtml(r.x.time) + " Uhr" : ""}</span>
          <button class="btn-small ex-del" type="button" data-d="${r.d}" data-i="${r.i}">✕</button>
        </div>`).join("")}</div>` : ""}
    </div>`;
}

function libDetailFromExercises(key, dur, exs) {
  if (/^emom/i.test(key)) {
    return `${dur} min: jede Minute ` + exs.map(x => `${String(x.reps).replace(/\s*pro Minute/i, "")} ${x.name}`).join(" + ");
  }
  return exs.map(x => x.name).join(", ");
}

function bindKraftLibrary() {
  const root = document.getElementById("tab-kraft");
  if (!root || !canEdit()) return;
  const readCard = (card) => {
    const exs = [...card.querySelectorAll(".lib-ex")].map(r => {
      const kg = Number(r.querySelector(".lx-kg").value);
      return {
        name: r.querySelector(".lx-name").value.trim(), sets: Number(r.querySelector(".lx-sets").value) || 1,
        reps: r.querySelector(".lx-reps").value.trim(), rest: r.querySelector(".lx-rest").value.trim(),
        ...(kg > 0 ? { weightKg: kg } : {}),
      };
    }).filter(x => x.name);
    return {
      name: card.querySelector(".lb-name").value.trim() || card.dataset.libKey,
      durationMin: Number(card.querySelector(".lb-dur").value) || 15,
      detail: card.querySelector(".lb-detail").value.trim(), exercises: exs,
    };
  };
  root.querySelectorAll(".lib-card").forEach(card => {
    const key = card.dataset.libKey;
    const add = card.querySelector(".lb-add");
    if (!add) return;
    add.addEventListener("click", () => card.querySelector(".lib-exs").insertAdjacentHTML("beforeend", libExerciseRowHtml({ name: "", sets: 3, reps: "10", rest: "60 s" })));
    card.addEventListener("click", (e) => { const del = e.target.closest(".lx-del"); if (del) del.closest(".lib-ex").remove(); });
    card.querySelector(".lb-save").addEventListener("click", () => {
      const entry = readCard(card);
      const old = currentLibrary(APP_DATA)[key] || {};
      const sig = (list) => JSON.stringify((list || []).map(x => [x.name, x.sets, x.reps, x.rest]));
      const oldEntry = JSON.parse(JSON.stringify(old));
      if (sig(old.exercises) !== sig(entry.exercises) && entry.detail === (old.detail || "")) {
        entry.detail = libDetailFromExercises(key, entry.durationMin, entry.exercises);
      }
      applyPlanChange(`„${entry.name}“ gespeichert`, plan => {
        plan.library = plan.library || {};
        plan.library[key] = entry;
        logWeightChanges(plan, oldEntry, entry);
      });
    });
    card.querySelector(".lb-reset").addEventListener("click", () => {
      applyPlanChange("Auf Standard zurückgesetzt", plan => { if (plan.library) delete plan.library[key]; });
    });
  });
  const nw = document.getElementById("lib-new");
  if (nw) nw.addEventListener("click", () => {
    const name = (prompt("Name der neuen Übungsgruppe (z. B. Rücken):") || "").trim();
    if (!name) return;
    const key = "x_" + name.toLowerCase().replace(/[^a-z0-9äöüß]+/g, "_").slice(0, 24);
    applyPlanChange(`„${name}“ angelegt`, plan => {
      plan.library = plan.library || {};
      plan.library[key] = { name, durationMin: 15, detail: "", exercises: [{ name: "Übung 1", sets: 3, reps: "10", rest: "60 s" }] };
    });
  });
  const exAdd = document.getElementById("ex-add");
  if (exAdd) exAdd.addEventListener("click", () => {
    const key = document.getElementById("ex-key").value, date = document.getElementById("ex-date").value;
    if (!key || !date) return;
    const time = document.getElementById("ex-time").value || null;
    const o = loadOverrides();
    o.__extras = o.__extras || {};
    (o.__extras[date] = o.__extras[date] || []).push({ key, time });
    saveOverrides(o);
    if (PRISTINE_DATA) renderAll();
    planToast("Einheit eingefügt", `${dpFmtDate(date)} – steht jetzt in Woche und Heute.`, 4000);
  });
  root.querySelectorAll(".ex-del").forEach(b => b.addEventListener("click", () => {
    const o = loadOverrides();
    const arr = (o.__extras || {})[b.dataset.d] || [];
    arr.splice(+b.dataset.i, 1);
    if (!arr.length) delete o.__extras[b.dataset.d];
    saveOverrides(o);
    if (PRISTINE_DATA) renderAll();
  }));
}

/** Extra-Einheiten (aus der Kraft-Bibliothek eingefügt) für einen Tag. */
function extraUnitsFor(dateStr, lib) {
  const ex = (loadOverrides().__extras || {})[dateStr] || [];
  return ex.map((x, i) => {
    const e = lib[x.key];
    if (!e) return null;
    return {
      name: `${e.name} (extra${i ? " " + (i + 1) : ""})`, type: /^emom/i.test(x.key) ? "emom" : "kraft", tag: "extra", status: "planned",
      detail: `${e.detail || ""}${x.time ? ` · ${x.time} Uhr` : ""}`, plannedDurationMin: e.durationMin || 15,
      exercises: JSON.parse(JSON.stringify(e.exercises || [])), isExtra: true,
    };
  }).filter(Boolean);
}

function applyExtras(data) {
  const lib = currentLibrary(data);
  data.week.days.forEach(d => { extraUnitsFor(d.date, lib).forEach(u => d.units.push(u)); });
  const todayDay = data.week.days.find(d => d.date === data.today.date);
  if (todayDay) data.today.units = todayDay.units;
}

/* ---------------------------------------------------------------------------
   Woche: Vorschau auf alle kommenden Wochen (Langzeitplan)
   --------------------------------------------------------------------------- */

const WOCHE_VIEW = { monday: null };
const WD_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function futureWeekDays(monday, data) {
  const wk = PLAN_DATA && PLAN_DATA.weeks && PLAN_DATA.weeks[monday];
  if (!wk) return null;
  const lib = currentLibrary(data);
  const days = WD_NAMES.map((wd, i) => {
    const src = (wk.days || {})[wd] || { focus: "", units: [] };
    const units = JSON.parse(JSON.stringify(src.units || [])).map(u => ({ ...u, status: "planned", homeWeekday: wd }));
    return { weekday: wd, date: isoAddDays(monday, i), focus: src.focus || "", units, fallbackNote: src.fallbackNote };
  });
  const moves = loadOverrides().__moves || {};
  Object.entries(moves).forEach(([key, target]) => {
    const [wkStart, home, name] = key.split("|");
    if (wkStart !== monday) return;
    const hd = days.find(d => d.weekday === home), td = days.find(d => d.date === target);
    if (!hd || !td || hd === td) return;
    const idx = hd.units.findIndex(u => u.name === name);
    if (idx < 0) return;
    const [u] = hd.units.splice(idx, 1);
    u.movedFromWeekday = home;
    td.units.push(u);
  });
  days.forEach(d => { extraUnitsFor(d.date, lib).forEach(u => d.units.push(u)); applyTimeOverrides(d.units, d.date); });
  return days;
}

function futureUnitRowHtml(u, dateStr, days, monday) {
  const controls = canEdit() ? `${timeOverrideHtml(u, dateStr)}${u.isExtra ? "" : moveSelectHtml(u, dateStr, days, monday)}` : "";
  return `
    <div class="day-mini-unit">
      <span style="flex:1;">
        ${escapeHtml(u.name)}${u.keySession ? ' <span class="unit-key-badge">Key</span>' : ""}${u.planLabel ? ` <span class="unit-key-badge" style="color:var(--sky-400);">${escapeHtml(u.planLabel)}</span>` : ""}
        ${u.detail ? `<div class="unit-detail" style="margin-top:2px;">${escapeHtml(u.detail)}${u.plannedDurationMin ? ` · ~${u.plannedDurationMin} min` : ""}</div>` : ""}
        ${u.movedFromWeekday ? `<div class="moved-note">verschoben von ${u.movedFromWeekday}</div>` : ""}
      </span>
      ${controls}
    </div>`;
}

/** Laufkilometer einer Woche von Hand setzen (überschreibt die Automatik nur für diese Woche). */
function weekRunControlHtml(monday) {
  const wk = PLAN_DATA && PLAN_DATA.weeks && PLAN_DATA.weeks[monday];
  const km = wk && wk.meta && wk.meta.runKm;
  if (!km || !canEdit()) return "";
  const manual = (planInputs().runOverrides || {})[monday];
  return `
    <div class="run-ctl" data-monday="${monday}" style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:10px;">
      <span class="card-note">Laufen diese Woche${manual ? " (von dir gesetzt)" : ""}:</span>
      <label class="card-note">langer Lauf <input type="number" class="text-input rc-long" step="0.5" min="3" max="99" value="${escapeHtml(km.long)}" style="max-width:84px;" /> km</label>
      <label class="card-note">Z2-Lauf <input type="number" class="text-input rc-z2" step="0.5" min="3" max="99" value="${escapeHtml(km.z2)}" style="max-width:84px;" /> km</label>
      <button class="btn-small rc-save" type="button">Setzen</button>
      ${manual ? '<button class="btn-small rc-reset" type="button">Automatik</button>' : ""}
    </div>`;
}

function bindRunControls(root) {
  if (!root) return;
  root.querySelectorAll(".run-ctl").forEach(el => {
    const monday = el.dataset.monday;
    el.querySelector(".rc-save").addEventListener("click", () => {
      const longKm = Number(el.querySelector(".rc-long").value), z2Km = Number(el.querySelector(".rc-z2").value);
      if (!(longKm > 0) || !(z2Km > 0)) return;
      applyPlanChange("Laufumfang gesetzt", plan => { plan.runOverrides = plan.runOverrides || {}; plan.runOverrides[monday] = { longKm, z2Km }; });
    });
    const reset = el.querySelector(".rc-reset");
    if (reset) reset.addEventListener("click", () => {
      applyPlanChange("Automatik wieder aktiv", plan => { if (plan.runOverrides) delete plan.runOverrides[monday]; });
    });
  });
}

function wochePreviewHtml(data) {
  const thisMonday = data.week.startDate;
  const weeks = PLAN_DATA && PLAN_DATA.weeks;
  if (!weeks) {
    return `<div class="card"><div class="card-head"><span class="card-title">Plan im Voraus</span></div>
      <div class="card-note">Der Langzeitplan bis September 2027 wird beim nächsten Sync erzeugt – dann kannst du hier Woche für Woche vorblättern.</div></div>`;
  }
  const keys = Object.keys(weeks).sort().filter(m => m > thisMonday);
  if (!keys.length) return "";
  const monday = keys.includes(WOCHE_VIEW.monday) ? WOCHE_VIEW.monday : keys[0];
  WOCHE_VIEW.monday = monday;
  const idx = keys.indexOf(monday);
  const wk = weeks[monday], meta = wk.meta || {};
  const days = futureWeekDays(monday, data);
  const agendaByDate = {};
  ((PLAN_DATA && PLAN_DATA.agenda) || []).forEach(a => { agendaByDate[a.date] = a.items; });
  const t = meta.targets || {};
  const cols = days.map(d => `
    <div class="day-col">
      <div class="day-col-head"><span class="day-name">${d.weekday}</span><span class="day-date">${fmtDateShort(d.date)}</span></div>
      ${(agendaByDate[d.date] || []).map(agendaItemHtml).join("")}
      <div style="font-size:11px; color:var(--muted); margin-bottom:2px;">${escapeHtml(d.focus)}</div>
      <div class="stack" style="gap:6px;">${d.units.map(u => futureUnitRowHtml(u, d.date, days, monday)).join("") || '<div class="card-note">Nichts geplant.</div>'}</div>
      ${d.fallbackNote ? `<div class="fallback-note">${escapeHtml(d.fallbackNote)}</div>` : ""}
    </div>`).join("");
  return `
    <div class="card" id="woche-preview">
      <div class="card-head">
        <span class="card-title">Plan im Voraus</span>
        <span class="card-note">${idx + 1} / ${keys.length} · bis ${fmtDateShort(keys[keys.length - 1])}</span>
      </div>
      <div style="display:flex; gap:8px; align-items:center; justify-content:space-between; margin-bottom:6px;">
        <button class="btn-small" type="button" id="wp-prev" ${idx === 0 ? "disabled" : ""}>◀</button>
        <div style="text-align:center;">
          <div style="font-weight:700;">${fmtDateShort(monday)} – ${fmtDateShort(isoAddDays(monday, 6))} · ${escapeHtml(meta.label || "")}</div>
          <div class="card-note">${t.runVolumeKm ? `Ziel: Lauf ${t.runVolumeKm} km · Rad ${t.bikeVolumeKm} km · ${fmtMin(t.timeMin)}` : ""}${wk.note ? ` · ${escapeHtml(wk.note)}` : ""}</div>
        </div>
        <button class="btn-small" type="button" id="wp-next" ${idx === keys.length - 1 ? "disabled" : ""}>▶</button>
      </div>
      ${weekRunControlHtml(monday)}
      <div style="display:flex; gap:8px; align-items:center; margin-bottom:10px;">
        <span class="card-note">Springen zu:</span><input type="date" id="wp-jump" class="text-input" style="max-width:160px;" />
      </div>
      <div class="week-grid">${cols}</div>
    </div>`;
}

function bindWochePreview(data) {
  bindRunControls(document.getElementById("tab-woche"));
  const card = document.getElementById("woche-preview");
  if (!card || !PLAN_DATA) return;
  const keys = Object.keys(PLAN_DATA.weeks).sort().filter(m => m > data.week.startDate);
  const go = (m) => { WOCHE_VIEW.monday = m; renderWoche(APP_DATA); };
  const idx = keys.indexOf(WOCHE_VIEW.monday);
  const prev = document.getElementById("wp-prev"), next = document.getElementById("wp-next");
  if (prev) prev.addEventListener("click", () => { if (idx > 0) go(keys[idx - 1]); });
  if (next) next.addEventListener("click", () => { if (idx < keys.length - 1) go(keys[idx + 1]); });
  document.getElementById("wp-jump").addEventListener("change", (e) => {
    if (!e.target.value) return;
    const m = isoMondayOf(e.target.value);
    if (keys.includes(m)) go(m);
  });
}

/* ---------------------------------------------------------------------------
   Coach: Vorschlag des Planers (wird nie automatisch angewendet)
   --------------------------------------------------------------------------- */

function planHintCardHtml(data) {
  const hint = data.planState && data.planState.hint;
  if (!hint || !canEdit()) return "";
  let dismissed = null;
  try { dismissed = localStorage.getItem("planHintDismissed"); } catch { /* ignore */ }
  if (dismissed === hint.text) return "";
  return `
    <div class="card accent-teal" id="plan-hint-card">
      <div class="card-head"><span class="card-title">Vorschlag zum Plan</span></div>
      <div class="card-note" style="margin-bottom:10px;">${escapeHtml(hint.text)}</div>
      <div style="display:flex; gap:8px;">
        <button class="btn-small" type="button" id="plan-hint-apply" data-type="${escapeHtml(hint.type)}">Übernehmen</button>
        <button class="btn-small" type="button" id="plan-hint-skip">Ignorieren</button>
      </div>
    </div>`;
}

function bindPlanHint(data) {
  const apply = document.getElementById("plan-hint-apply"), skip = document.getElementById("plan-hint-skip");
  if (!apply) return;
  apply.addEventListener("click", () => {
    const delta = apply.dataset.type === "advance" ? 1 : -1;
    applyPlanChange(delta > 0 ? "Fortschritt +1 Woche" : "Fortschritt −1 Woche",
      plan => { plan.progression = { offsetWeeks: ((plan.progression || {}).offsetWeeks || 0) + delta }; });
  });
  skip.addEventListener("click", () => {
    try { localStorage.setItem("planHintDismissed", data.planState.hint.text); } catch { /* ignore */ }
    document.getElementById("plan-hint-card").remove();
  });
}

/* ---------------------------------------------------------------------------
   Performance: Soll/Ist-Diagramme
   --------------------------------------------------------------------------- */

function groupedBarsSVG(items, opts = {}) {
  const w = 640, h = 150, padL = 34, padR = 8, padT = 10, padB = 22;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const max = Math.max(1, ...items.flatMap(i => [i.value || 0, i.target || 0])) * 1.15;
  const slot = innerW / items.length, bw = Math.min(26, slot * 0.34);
  const unit = opts.unit || "";
  let g = "";
  for (let k = 0; k <= 4; k++) {
    const y = padT + innerH * (1 - k / 4);
    g += `<line class="chart-grid-line" x1="${padL}" x2="${w - padR}" y1="${y}" y2="${y}"/><text class="chart-axis-label" x="${padL - 6}" y="${y + 3}" text-anchor="end">${Math.round(max * k / 4)}</text>`;
  }
  const bars = items.map((it, i) => {
    const cx = padL + slot * i + slot / 2;
    const hv = ((it.value || 0) / max) * innerH, ht = ((it.target || 0) / max) * innerH;
    return `
      ${it.target ? `<rect x="${(cx - bw - 1).toFixed(1)}" y="${(padT + innerH - ht).toFixed(1)}" width="${bw}" height="${ht.toFixed(1)}" fill="var(--ocean-600)" opacity=".45" rx="2"><title>Plan ${it.target}${unit}</title></rect>` : ""}
      <rect x="${(cx + 1).toFixed(1)}" y="${(padT + innerH - hv).toFixed(1)}" width="${bw}" height="${hv.toFixed(1)}" fill="${opts.color || "var(--sky-400)"}" rx="2"><title>Ist ${it.value || 0}${unit}</title></rect>
      <text class="chart-axis-label" x="${cx.toFixed(1)}" y="${h - 6}" text-anchor="middle">${escapeHtml(it.label)}</text>`;
  }).join("");
  return `<svg class="chart-svg" viewBox="0 0 ${w} ${h}">${g}${bars}</svg>`;
}

function perfExtrasHtml(data) {
  const weeks = data.performance.weeks || [];
  if (!weeks.length) return "";
  const run = weeks.map(w => ({ label: w.label, value: w.runVolumeKm, target: w.plannedRunKm }));
  const bike = weeks.map(w => ({ label: w.label, value: w.bikeVolumeKm, target: w.plannedBikeKm }));
  const time = weeks.map(w => ({ label: w.label, value: w.timeMin != null ? Math.round(w.timeMin / 6) / 10 : 0 }));
  const elev = weeks.map(w => ({ label: w.label, value: w.elevationGainM || 0 }));
  const legend = run.some(i => i.target) ? "hell = Ist · blass = Plan" : "Ist";
  const total = (k) => weeks.reduce((s, w) => s + (w[k] || 0), 0);
  return `
    <div class="grid grid-2">
      <div class="card"><div class="card-head"><span class="card-title">Laufen: Plan vs. Ist</span><span class="card-note">km / Woche · ${legend}</span></div>${groupedBarsSVG(run, { unit: " km" })}</div>
      <div class="card"><div class="card-head"><span class="card-title">Rad: Plan vs. Ist</span><span class="card-note">km / Woche · ${legend}</span></div>${groupedBarsSVG(bike, { unit: " km", color: "var(--teal)" })}</div>
    </div>
    <div class="grid grid-2">
      <div class="card"><div class="card-head"><span class="card-title">Trainingszeit</span><span class="card-note">Stunden / Woche</span></div>${groupedBarsSVG(time, { unit: " h", color: "var(--ice-300)" })}</div>
      <div class="card"><div class="card-head"><span class="card-title">Höhenmeter</span><span class="card-note">hm / Woche</span></div>${groupedBarsSVG(elev, { unit: " hm", color: "var(--amber)" })}</div>
    </div>
    <div class="card">
      <div class="stat-row">
        <div class="stat"><span class="stat-value">${Math.round(total("runVolumeKm"))}<span class="unit">km</span></span><span class="stat-label">Laufen (${weeks.length} Wochen)</span></div>
        <div class="stat"><span class="stat-value">${Math.round(total("bikeVolumeKm"))}<span class="unit">km</span></span><span class="stat-label">Rad (${weeks.length} Wochen)</span></div>
        <div class="stat"><span class="stat-value">${Math.round(total("timeMin") / 60)}<span class="unit">h</span></span><span class="stat-label">Trainingszeit gesamt</span></div>
        <div class="stat"><span class="stat-value">${Math.round(total("sessions"))}</span><span class="stat-label">Einheiten</span></div>
      </div>
    </div>`;
}

/* ---------------------------------------------------------------------------
   Zauberstab / Verschieben: passende Uhrzeit am Zieltag vorschlagen
   (gleiche Logik wie im Planer, vereinfacht aus Dienstplan & Terminen)
   --------------------------------------------------------------------------- */

function hmToMin(hm) { const [h, m] = hm.split(":").map(Number); return h * 60 + m; }
function minToHm(min) { return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`; }

function agendaItemsFor(dateStr) {
  const pool = (PLAN_DATA && PLAN_DATA.agenda) || (APP_DATA && APP_DATA.agenda) || [];
  const hit = pool.find(a => a.date === dateStr);
  return hit ? hit.items : [];
}

function busyIntervalsFor(dateStr) {
  const st = { travelMin: 75, ...(planInputs().settings || {}) };
  const travel = Number(st.travelMin) || 0, depart = 15;
  const busy = [];
  agendaItemsFor(dateStr).forEach(it => {
    if (it.kind === "arbeit" && it.start && it.end) {
      busy.push([hmToMin(it.start) - travel - depart, hmToMin(it.end) + travel]);
    } else if ((it.kind === "schule" || it.kind === "termin") && it.start) {
      const s = hmToMin(it.start), e = it.end ? hmToMin(it.end) : s + 60;
      const tr = it.kind === "schule" ? travel : 30;
      busy.push([s - tr - depart, e + tr]);
    } else if (it.kind === "schule") {
      busy.push([9 * 60 - travel - depart, 16 * 60 + travel]);
    }
  });
  busy.sort((a, b) => a[0] - b[0]);
  const merged = [];
  busy.forEach(b => { if (merged.length && b[0] <= merged[merged.length - 1][1]) merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], b[1]); else merged.push([...b]); });
  return merged;
}

/** Beste Startzeit ("HH:MM") für eine Einheit an einem Tag - oder null, wenn kein Fenster passt. */
function suggestTimeForDay(dateStr, unit) {
  const dur = unit.plannedDurationMin || 30;
  const DAY_START = 6 * 60, DAY_END = 21 * 60 + 30;
  const busy = busyIntervalsFor(dateStr);
  const windows = [];
  let cursor = DAY_START, afterBlock = false;
  busy.forEach(([s, e]) => {
    if (s > cursor) windows.push([cursor, Math.min(s, DAY_END), afterBlock]);
    cursor = Math.max(cursor, e);
    afterBlock = true;
  });
  if (cursor < DAY_END) windows.push([cursor, DAY_END, afterBlock]);
  // Fenster direkt nach einem Block (Rückkehr): 30 min Puffer
  const usable = windows.map(([s, e, after]) => [after ? s + 30 : s, e]).filter(([s, e]) => e - s >= dur);
  if (!usable.length) return null;
  const round15 = (m) => Math.ceil(m / 15) * 15;
  if (unit.type === "rad") {
    for (const [s, e] of usable) {
      // Morgenfenster: ab 07:00 (nüchtern); sonst direkt am Fensteranfang. Vor einem Block 30 min Puffer bis zur Abfahrt.
      const start = round15(s === DAY_START ? Math.max(s, 7 * 60) : s);
      const need = dur + (e === DAY_END ? 0 : 30);
      if (start + need <= e) return minToHm(start);
      if (s === DAY_START && s + need <= e) return minToHm(s);
    }
    return null;
  }
  const late = usable.find(([s, e]) => Math.max(s, 9 * 60) + dur <= e);
  const [ws, we] = late || usable[0];
  const start = round15(late ? Math.max(ws, 9 * 60) : ws);
  return start + dur <= we ? minToHm(start) : null;
}

function findUnitInfo(weekStart, homeWeekday, unitName) {
  let days = null;
  if (APP_DATA && APP_DATA.week.startDate === weekStart) {
    const d = APP_DATA.week.days.find(x => x.weekday === homeWeekday);
    const u = d && d.units.find(x => x.name === unitName);
    if (u) return u;
    // verschobene Einheit: in allen Tagen suchen
    for (const dd of APP_DATA.week.days) { const f = dd.units.find(x => x.name === unitName); if (f) return f; }
    return null;
  }
  const wk = PLAN_DATA && PLAN_DATA.weeks && PLAN_DATA.weeks[weekStart];
  const d = wk && wk.days && wk.days[homeWeekday];
  return d ? (d.units || []).find(x => x.name === unitName) || null : null;
}

/** Nach einem Verschieben: Uhrzeit am Zieltag passend setzen (oder Zeit-Override entfernen). */
function retimeMovedUnit(weekStart, homeWeekday, unitName, targetDate, isHome) {
  const unit = findUnitInfo(weekStart, homeWeekday, unitName);
  if (!unit) return null;
  if (isHome) { setTimeOverride(targetDate, unitName, ""); return null; }
  const time = suggestTimeForDay(targetDate, unit);
  setTimeOverride(targetDate, unitName, time || "");
  return time;
}

/* ---------------------------------------------------------------------------
   Kalender-Export (.ics) - Import in Google/Apple/Outlook Kalender per Tipp
   --------------------------------------------------------------------------- */

function icsEscape(s) {
  return String(s || "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}
function icsStamp(dateIso, hm) { return dateIso.replace(/-/g, "") + "T" + hm.replace(":", "") + "00"; }

/** Alle Einträge (Arbeit, Termine, optional Training) als iCalendar-Text. */
function buildIcsText(includeTraining) {
  const today = isoToday();
  const events = [];
  const add = (date, start, end, title, desc, uidBase) => {
    if (date < today || !start) return;
    events.push({ date, start, end, title, desc, uid: `${date}-${uidBase}-${start.replace(":", "")}@willisport.github.io` });
  };
  const agenda = (PLAN_DATA && PLAN_DATA.agenda) || (APP_DATA && APP_DATA.agenda) || [];
  agenda.forEach(a => a.items.forEach(it => {
    if (!["arbeit", "schule", "termin"].includes(it.kind) || !it.start) return;
    const label = it.kind === "arbeit" ? "Arbeit" : it.title || "Termin";
    add(a.date, it.start, it.end || minToHm(hmToMin(it.start) + 60), label, it.note || "", it.kind);
  }));
  if (includeTraining) {
    const weeks = {};
    if (PLAN_DATA && PLAN_DATA.weeks) Object.entries(PLAN_DATA.weeks).forEach(([m, w]) => { weeks[m] = w.days; });
    if (APP_DATA) {
      const d = {};
      APP_DATA.week.days.forEach(day => { d[day.weekday] = { units: day.units }; });
      weeks[APP_DATA.week.startDate] = d;
    }
    Object.entries(weeks).forEach(([monday, days]) => {
      WD_NAMES.forEach((wd, i) => {
        const date = isoAddDays(monday, i);
        if (date > isoAddDays(today, 56)) return;   // Training: nur die nächsten 8 Wochen
        ((days[wd] || {}).units || []).forEach((u, k) => {
          if (u.type === "emom") return;
          const m = (u.detail || "").match(/(\d{2}:\d{2}) Uhr/);
          if (!m) return;
          const dur = u.plannedDurationMin || 45;
          add(date, m[1], minToHm(Math.min(23 * 60 + 59, hmToMin(m[1]) + dur)), `Training: ${u.name}`, u.detail || "", "t" + k);
        });
      });
    });
  }
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Willis Dashboard//DE", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Willis Plan"];
  const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  events.sort((a, b) => (a.date + a.start).localeCompare(b.date + b.start)).forEach(e => {
    lines.push("BEGIN:VEVENT", `UID:${e.uid}`, `DTSTAMP:${stamp}`, `DTSTART:${icsStamp(e.date, e.start)}`,
      `DTEND:${icsStamp(e.date, e.end)}`, `SUMMARY:${icsEscape(e.title)}`);
    if (e.desc) lines.push(`DESCRIPTION:${icsEscape(e.desc)}`);
    lines.push("END:VEVENT");
  });
  lines.push("END:VCALENDAR");
  return { text: lines.join("\r\n") + "\r\n", count: events.length };
}

function downloadIcs(includeTraining) {
  const { text, count } = buildIcsText(includeTraining);
  if (!count) { planToast("Nichts zu exportieren", "Es gibt noch keine zukünftigen Schichten oder Termine.", 5000); return; }
  const blob = new Blob([text], { type: "text/calendar;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = includeTraining ? "willi-plan-mit-training.ics" : "willi-schichten-termine.ics";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  planToast("Kalender-Datei erstellt", `${count} Einträge – Datei öffnen/importieren, dann sind sie im Kalender.`, 6000);
}

/* ---------------------------------------------------------------------------
   Performance: FTP & 5-km-Zeit eintragen (Verlauf, W/kg, Test-Erinnerung)
   --------------------------------------------------------------------------- */

function perfFtpCardHtml(data) {
  const st = dpSettings();
  const hist = (planInputs().ftpHistory || []).slice().sort((a, b) => a.date.localeCompare(b.date));
  const tg = data.planState && data.planState.metrics && data.planState.metrics.targets;
  const ftp = st.ftpW || (tg && tg.ftpW) || null;
  const kg = data.today && data.today.body && data.today.body.weightKg;
  const last = hist.length ? hist[hist.length - 1] : null;
  const weeksAgo = last ? Math.floor((Date.now() - new Date(last.date + "T12:00:00")) / 604800000) : null;
  const edit = canEdit();
  const fmt5k = st.ref5kSec ? `${Math.floor(st.ref5kSec / 60)}:${String(Math.round(st.ref5kSec % 60)).padStart(2, "0")}` : "";
  return `
    <div class="card" id="perf-ftp-card">
      <div class="card-head"><span class="card-title">FTP &amp; Testwerte</span><span class="card-note">Zonen und Vorgaben im Plan rechnen damit</span></div>
      <div class="stat-row">
        <div class="stat"><span class="stat-value">${ftp || "–"}<span class="unit">W</span></span><span class="stat-label">FTP${st.ftpW ? " (von dir)" : tg ? " (Garmin)" : ""}</span></div>
        <div class="stat"><span class="stat-value">${ftp && kg ? (ftp / kg).toFixed(2) : "–"}<span class="unit">W/kg</span></span><span class="stat-label">${kg ? `bei ${kg} kg` : "Gewicht fehlt"}</span></div>
        <div class="stat"><span class="stat-value">${tg ? tg.z2Watt : "–"}<span class="unit">W</span></span><span class="stat-label">Zone 2</span></div>
        <div class="stat"><span class="stat-value">${tg ? `${tg.thrLo}–${tg.thrHi}` : "–"}<span class="unit">W</span></span><span class="stat-label">Schwelle (Zone 4)</span></div>
      </div>
      ${hist.length > 1 ? `<div style="margin:10px 0;">${lineChartSVG(hist.map(h => ({ value: h.w, label: fmtDateShort(h.date) })))}</div>` : ""}
      ${weeksAgo !== null && weeksAgo >= 8 ? `<div class="card-note" style="color:var(--amber); margin:8px 0;">Dein letzter FTP-Test ist ${weeksAgo} Wochen her – Zeit für einen neuen (alle 6–8 Wochen).</div>` : ""}
      ${edit ? `
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end; margin-top:10px;">
        <label class="card-note">Neue FTP (Watt)<input type="number" id="pf-ftp" class="text-input" min="80" max="500" value="${st.ftpW || ""}" style="max-width:110px;" /></label>
        <label class="card-note">Test am<input type="date" id="pf-ftp-date" class="text-input" value="${isoToday()}" style="max-width:160px;" /></label>
        <label class="card-note">5-km-Zeit (mm:ss)<input type="text" id="pf-5k" class="text-input" placeholder="auto" value="${escapeHtml(fmt5k)}" style="max-width:110px;" /></label>
        <button class="btn-small" type="button" id="pf-save">Speichern</button>
      </div>
      <div class="card-note" style="margin-top:6px;">FTP-Test (Zwift o. ä.) eintragen – der Plan passt Zone 2 und Schwelle an. 5-km-Zeit leer lassen = Garmin-Prognose.</div>` : ""}
    </div>`;
}

function bindPerfFtp() {
  const btn = document.getElementById("pf-save");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const w = Number(document.getElementById("pf-ftp").value);
    const date = document.getElementById("pf-ftp-date").value || isoToday();
    const m = (document.getElementById("pf-5k").value || "").trim().match(/^(\d{1,2}):(\d{2})$/);
    const ref5kSec = m ? Number(m[1]) * 60 + Number(m[2]) : null;
    if (!(w >= 80 && w <= 500)) { planToast("Bitte eine FTP zwischen 80 und 500 Watt eintragen", "", 4000); return; }
    applyPlanChange(`FTP ${w} W gespeichert`, plan => {
      plan.settings = { ...(plan.settings || {}), ftpW: w, ref5kSec };
      const hist = (plan.ftpHistory || []).filter(h => h.date !== date);
      hist.push({ date, w });
      plan.ftpHistory = hist.sort((a, b) => a.date.localeCompare(b.date));
    });
  });
}
