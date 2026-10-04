/* Oberfläche für die Plan-Eingaben: Dienstplan-Tab (PDF-Upload, Termine, ICS,
   Einstellungen, Krank/Fortschritt). Alle Änderungen landen in den Overrides
   unter "__plan"; "Speichern" löst die Neuberechnung des Plans aus. */

const DPUI = { parsed: null, ics: null, dirty: false, status: "" };
const DP_KIND_LABEL = { arbeit: "Arbeit", schule: "Schule/Uni", termin: "Termin", uni: "Uni", frei: "Frei", urlaub: "Urlaub", krank: "Krank" };
const DP_EVENT_KINDS = [["schule", "Schule/Seminar"], ["termin", "Termin"], ["frei", "Frei/Ruhetag (ganztägig)"]];

function dpFmtDate(iso) {
  const d = new Date(iso + "T12:00:00");
  return `${["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"][d.getDay()]} ${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`;
}

function dpSettings() {
  const p = planInputs();
  return {
    travelMin: 75, kuerzel: "WL", raceDate: "2027-08-28", raceName: "Ultramarathon", raceDistanceKm: 100,
    runScalePct: 100, longRunMaxKm: 36, includeLongRide: false, includeLegStabi: false, includeLegSupersets: false, ...(p.settings || {}),
  };
}

/** Änderung nur lokal vormerken (Tippen in Listen) - gespeichert wird per Button. */
function dpStage(mutator) {
  const o = loadOverrides();
  o.__plan = o.__plan || { version: 1 };
  mutator(o.__plan);
  saveOverrides(o, { push: false });
  DPUI.dirty = true;
  const bar = document.getElementById("dp-dirty-bar");
  if (bar) bar.hidden = false;
}

async function dpCommit(label) {
  DPUI.dirty = false;
  const ok = await applyPlanChange(label, () => {});
  return ok;
}

function dpTimeInput(cls, value, extra = "") {
  return `<input type="time" class="text-input ${cls}" value="${escapeHtml(value || "")}" style="max-width:110px;" ${extra} />`;
}

/* ---------------------------------------------------------------------------
   Prüf-Ansicht nach dem PDF-Lesen
   --------------------------------------------------------------------------- */

function dpParsedHtml() {
  const days = DPUI.parsed;
  if (!days) return "";
  const nShifts = days.reduce((n, d) => n + d.shifts.length, 0);
  const nEv = days.reduce((n, d) => n + d.events.length, 0);
  const nSt = days.filter(d => d.status).length;
  const rows = days.map(d => {
    const shiftRows = (d.shifts.length ? d.shifts : [{ start: "", end: "" }]).map(s => `
      <div class="dp-shift" style="display:flex; gap:6px; align-items:center;">
        <span class="card-note" style="width:52px;">Arbeit</span>${dpTimeInput("dp-s", s.start)}<span class="card-note">bis</span>${dpTimeInput("dp-e", s.end)}
      </div>`).join("");
    const evRows = d.events.map(ev => `
      <div class="dp-ev" style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
        <input type="checkbox" class="dp-eok" checked title="übernehmen" />
        <input type="text" class="text-input dp-et" value="${escapeHtml(ev.title)}" style="flex:1; min-width:140px;" />
        ${dpTimeInput("dp-es", ev.start)}<span class="card-note">bis</span>${dpTimeInput("dp-ee", ev.end)}
        <select class="move-select dp-ek">${DP_EVENT_KINDS.map(([k, l]) => `<option value="${k}" ${k === ev.kind ? "selected" : ""}>${l}</option>`).join("")}</select>
      </div>`).join("");
    return `
      <div class="dp-day unit" data-date="${d.date}" style="display:block;">
        <div style="display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; margin-bottom:6px;">
          <strong>${dpFmtDate(d.date)}</strong>
          <select class="move-select dp-status">
            ${[["", "kein Sonderstatus"], ["uni", "Uni / Schule"], ["frei", "Frei"], ["urlaub", "Urlaub"]].map(([k, l]) => `<option value="${k}" ${k === (d.status || "") ? "selected" : ""}>${l}</option>`).join("")}
          </select>
        </div>
        <div class="stack" style="gap:6px;">${shiftRows}${evRows}</div>
        ${d.notes && d.notes.length ? `<details style="margin-top:6px;"><summary class="card-note" style="cursor:pointer;">Notizen aus dem PDF</summary><div class="card-note">${d.notes.map(escapeHtml).join("<br>")}</div></details>` : ""}
      </div>`;
  }).join("");
  return `
    <div class="card accent-teal" id="dp-review">
      <div class="card-head"><span class="card-title">Erkannt – bitte kurz prüfen</span>
        <span class="card-note">${days.length} Tage · ${nShifts} Schichten · ${nEv} Termine · ${nSt} Sonderstatus</span></div>
      <div class="stack" style="gap:8px;">${rows}</div>
      <div style="display:flex; gap:8px; margin-top:12px; flex-wrap:wrap;">
        <button class="btn-small" type="button" id="dp-accept">Übernehmen &amp; Plan neu berechnen</button>
        <button class="btn-small" type="button" id="dp-discard">Verwerfen</button>
      </div>
    </div>`;
}

function dpReadReview() {
  const out = [];
  document.querySelectorAll("#dp-review .dp-day").forEach(el => {
    const shifts = [];
    el.querySelectorAll(".dp-shift").forEach(r => {
      const s = r.querySelector(".dp-s").value, e = r.querySelector(".dp-e").value;
      if (s && e) shifts.push({ start: s, end: e });
    });
    const events = [];
    el.querySelectorAll(".dp-ev").forEach(r => {
      if (!r.querySelector(".dp-eok").checked) return;
      const start = r.querySelector(".dp-es").value;
      events.push({
        title: r.querySelector(".dp-et").value.trim() || "Termin", start, end: r.querySelector(".dp-ee").value,
        kind: r.querySelector(".dp-ek").value,
      });
    });
    out.push({ date: el.dataset.date, shifts, events, notes: [], status: el.querySelector(".dp-status").value || null });
  });
  return out;
}

/* ---------------------------------------------------------------------------
   ICS-Import (Prüfliste)
   --------------------------------------------------------------------------- */

function dpIcsHtml() {
  const list = DPUI.ics;
  if (!list) return "";
  if (!list.length) return `<div class="card-note" style="margin-top:8px;">Keine Termine mit Uhrzeit in der Datei gefunden.</div>`;
  return `
    <div id="dp-ics-review" style="margin-top:10px;">
      <div class="card-note" style="margin-bottom:6px;">${list.length} Termine gefunden – Häkchen entfernen, was nicht rein soll.</div>
      <div class="stack" style="gap:6px; max-height:360px; overflow:auto;">
        ${list.map((e, i) => `
          <label class="unit" style="display:flex; gap:8px; align-items:center;">
            <input type="checkbox" class="dp-ics-ok" data-i="${i}" ${e.checked ? "checked" : ""} />
            <span style="flex:1; min-width:0;"><strong>${dpFmtDate(e.date)} ${escapeHtml(e.start)}${e.end ? "–" + escapeHtml(e.end) : ""}</strong> ${escapeHtml(e.title)}
              ${e.recurring ? '<span class="card-note"> · wiederkehrend (nur 1. Termin)</span>' : ""}${e.dup ? '<span class="card-note"> · schon vorhanden</span>' : ""}</span>
          </label>`).join("")}
      </div>
      <button class="btn-small" type="button" id="dp-ics-accept" style="margin-top:10px;">Ausgewählte übernehmen &amp; Plan neu berechnen</button>
    </div>`;
}

function dpGuessKind(title) {
  return /schul|seminar|ausbildung|unterricht|prüfung|klausur|uni\b|vorlesung|lehrgang|schulung/i.test(title) ? "schule" : "termin";
}

/* ---------------------------------------------------------------------------
   Übersicht der gespeicherten Eingaben
   --------------------------------------------------------------------------- */

function dpOverviewHtml() {
  const p = planInputs();
  const from = isoAddDays(isoToday(), -1);
  const shiftRows = Object.keys(p.shifts || {}).filter(d => d >= from).sort().flatMap(d =>
    (p.shifts[d] || []).map((s, i) => ({ type: "shift", date: d, i, s })));
  const evRows = (p.events || []).map((e, i) => ({ type: "ev", date: e.date, i, e })).filter(r => r.date >= from);
  const stRows = Object.keys(p.dayStatus || {}).filter(d => d >= from).sort().map(d => ({ type: "st", date: d, k: p.dayStatus[d].kind }));
  const all = [...shiftRows, ...evRows, ...stRows].sort((a, b) => a.date.localeCompare(b.date));
  if (!all.length) return `<div class="card-note">Noch nichts eingetragen.</div>`;
  const rows = all.map(r => {
    if (r.type === "shift") return `
      <div class="unit dp-row" data-type="shift" data-date="${r.date}" data-i="${r.i}" style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
        <strong style="width:84px;">${dpFmtDate(r.date)}</strong><span class="card-note" style="width:52px;">Arbeit</span>
        ${dpTimeInput("dp-ls", r.s.start)}<span class="card-note">bis</span>${dpTimeInput("dp-le", r.s.end)}
        <button class="btn-small dp-del" type="button" style="margin-left:auto;">✕</button>
      </div>`;
    if (r.type === "ev") return `
      <div class="unit dp-row" data-type="ev" data-i="${r.i}" style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
        <strong style="width:84px;">${dpFmtDate(r.date)}</strong>
        <input type="text" class="text-input dp-lt" value="${escapeHtml(r.e.title)}" style="flex:1; min-width:140px;" />
        ${dpTimeInput("dp-ls", r.e.start)}<span class="card-note">bis</span>${dpTimeInput("dp-le", r.e.end)}
        <span class="card-note">${escapeHtml(DP_KIND_LABEL[r.e.kind] || r.e.kind)}</span>
        <button class="btn-small dp-del" type="button" style="margin-left:auto;">✕</button>
      </div>`;
    return `
      <div class="unit dp-row" data-type="st" data-date="${r.date}" style="display:flex; gap:6px; align-items:center;">
        <strong style="width:84px;">${dpFmtDate(r.date)}</strong><span>${escapeHtml(DP_KIND_LABEL[r.k] || r.k)}</span>
        <button class="btn-small dp-del" type="button" style="margin-left:auto;">✕</button>
      </div>`;
  }).join("");
  return `<div class="stack" style="gap:6px; max-height:520px; overflow:auto;">${rows}</div>`;
}

/* ---------------------------------------------------------------------------
   Tab
   --------------------------------------------------------------------------- */

function planStateCardHtml() {
  const ps = (typeof APP_DATA !== "undefined" && APP_DATA && APP_DATA.planState) || null;
  const p = planInputs();
  const sick = p.sick || {};
  const offset = (p.progression && p.progression.offsetWeeks) || 0;
  const stateTxt = sick.from && !sick.to ? `krank seit ${dpFmtDate(sick.from)} – Plan pausiert`
    : sick.from && sick.to && sick.to >= isoAddDays(isoToday(), -7) ? `wieder gesund seit ${dpFmtDate(sick.to)} – Plan baut langsam wieder auf`
      : "gesund, Plan läuft normal";
  const phase = ps && ps.progression ? ps.progression.phase : null;
  return `
    <div class="card">
      <div class="card-head"><span class="card-title">Plan-Status</span><span class="card-note">${escapeHtml(phase || "")}</span></div>
      <div class="card-note" style="margin-bottom:8px;">${escapeHtml(stateTxt)} · Fortschritt ${offset === 0 ? "wie geplant" : (offset > 0 ? "+" : "") + offset + " Wochen"}</div>
      <div class="card-note" style="margin-bottom:8px;">${escapeHtml(dpSettings().raceName)} ${escapeHtml(dpSettings().raceDistanceKm)} km am ${dpFmtDate(dpSettings().raceDate)} ${dpSettings().raceDate.slice(0, 4)} – noch ${Math.max(0, Math.ceil((new Date(dpSettings().raceDate + "T12:00:00") - new Date()) / 604800000))} Wochen · Laufumfang ${escapeHtml(dpSettings().runScalePct)} %</div>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        ${sick.from && !sick.to
          ? '<button class="btn-small" type="button" data-plan-act="healthy">Ich bin wieder gesund</button>'
          : '<button class="btn-small" type="button" data-plan-act="sick">Ich bin krank</button>'}
        <button class="btn-small" type="button" data-plan-act="advance">Fortschritt +1 Woche</button>
        <button class="btn-small" type="button" data-plan-act="hold">Fortschritt −1 Woche</button>
      </div>
      <div class="card-note" style="margin-top:8px;">Oder einfach unten ins Coach-Feld schreiben: „ich bin krank“, „bin wieder gesund“, „fühlt sich gut, wir können hoch“, „stagniert, wir bleiben so“.</div>
    </div>`;
}

function renderDienstplan() {
  const panel = document.getElementById("tab-dienstplan");
  if (!panel || typeof CURRENT_ROLE === "undefined" || CURRENT_ROLE !== "owner") return;
  const st = dpSettings();
  const p = planInputs();
  const nSh = Object.keys(p.shifts || {}).length, nEv = (p.events || []).length;

  panel.innerHTML = `
    <div class="page-head">
      <div class="page-eyebrow">Dienstplan &amp; Termine</div>
      <div class="page-title">Alles eintragen – der Plan passt sich an</div>
      <div class="page-sub">PDF hochladen oder Termine eintippen. Daraus berechnet der Planer den ganzen Trainingsplan bis September 2027 (Rad nüchtern vor der Schicht, Läufe/Kraft in freien Fenstern). Aktuell gespeichert: ${nSh} Schichttage, ${nEv} Termine.</div>
    </div>
    <div class="stack">
      <div id="dp-dirty-bar" class="card accent-amber" ${DPUI.dirty ? "" : "hidden"}>
        <div class="card-head"><span class="card-title">Ungespeicherte Änderungen</span></div>
        <button class="btn-small" type="button" id="dp-save-all">Speichern &amp; Plan neu berechnen</button>
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Dienstplan hochladen (PDF)</span><span class="card-note">Schichten (${escapeHtml(st.kuerzel)}) &amp; Notizen werden automatisch gelesen</span></div>
        <input type="file" id="dp-upload" accept=".pdf" class="text-input" style="padding:8px;" />
        <div class="card-note" id="dp-upload-status" style="margin-top:8px;">${escapeHtml(DPUI.status)}</div>
      </div>
      ${dpParsedHtml()}

      <div class="card">
        <div class="card-head"><span class="card-title">Termin hinzufügen</span><span class="card-note">Schule, Arzt, Uni … – Fahrzeit leer lassen = Standard</span></div>
        <div class="grid grid-2" style="gap:10px;">
          <input type="text" id="dp-ev-title" class="text-input" placeholder="Titel (z. B. Berufsschule)" />
          <input type="date" id="dp-ev-date" class="text-input" />
          <div style="display:flex; gap:6px; align-items:center;"><input type="time" id="dp-ev-start" class="text-input" /><span class="card-note">bis</span><input type="time" id="dp-ev-end" class="text-input" /></div>
          <div style="display:flex; gap:6px;">
            <select id="dp-ev-kind" class="move-select">${DP_EVENT_KINDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
            <input type="number" id="dp-ev-travel" class="text-input" placeholder="Fahrt min" min="0" max="240" style="max-width:110px;" />
          </div>
        </div>
        <button class="btn-small" type="button" id="dp-ev-add" style="margin-top:10px;">Termin speichern</button>
        <hr style="border:0; border-top:1px solid var(--line, #ffffff22); margin:14px 0;" />
        <div class="card-head" style="margin-bottom:6px;"><span class="card-title">Kalender-Datei importieren (.ics)</span><span class="card-note">Google / Apple / Outlook Export</span></div>
        <input type="file" id="dp-ics-file" accept=".ics,text/calendar" class="text-input" style="padding:8px;" />
        ${dpIcsHtml()}
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Kalender</span><span class="card-note">Plan in dein Handy-/Google-Kalender bringen</span></div>
        <div class="card-note" style="margin-bottom:8px;">${(APP_DATA && APP_DATA.planState && APP_DATA.planState.externalEvents) ? `${APP_DATA.planState.externalEvents} Termine kommen automatisch aus deinem Google-Kalender.` : "Google-Kalender-Anbindung: noch nicht eingerichtet (geheime iCal-Adresse fehlt) – dann übernimmt die Seite deine Termine automatisch."}</div>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <button class="btn-small" type="button" id="dp-ics-export">Schichten &amp; Termine als .ics</button>
          <button class="btn-small" type="button" id="dp-ics-export-train">… mit Training als .ics</button>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Gespeicherte Schichten &amp; Termine</span><span class="card-note">Zeiten direkt ändern, dann speichern</span></div>
        ${dpOverviewHtml()}
      </div>

      <div class="card">
        <div class="card-head"><span class="card-title">Einstellungen</span></div>
        <div class="grid grid-2" style="gap:10px;">
          <label class="card-note">Fahrzeit je Strecke (Min)<input type="number" id="dp-set-travel" class="text-input" min="0" max="240" value="${st.travelMin}" /></label>
          <label class="card-note">Kürzel im Dienstplan<input type="text" id="dp-set-kz" class="text-input" maxlength="4" value="${escapeHtml(st.kuerzel)}" /></label>
          <label class="card-note">Wettkampf-/Zieltermin<input type="date" id="dp-set-race" class="text-input" value="${escapeHtml(st.raceDate)}" /></label>
          <label class="card-note">Wettkampf (Name)<input type="text" id="dp-set-rname" class="text-input" maxlength="40" value="${escapeHtml(st.raceName)}" /></label>
          <label class="card-note">Wettkampfstrecke (km)<input type="number" id="dp-set-rdist" class="text-input" min="1" max="500" value="${escapeHtml(st.raceDistanceKm)}" /></label>
          <label class="card-note">Laufumfang insgesamt: <b id="dp-set-scale-val">${escapeHtml(st.runScalePct)}</b> %<input type="range" id="dp-set-scale" min="50" max="130" step="5" value="${escapeHtml(st.runScalePct)}" style="width:100%;" /></label>
          <label class="card-note">Langer Lauf maximal (km)<input type="number" id="dp-set-longmax" class="text-input" min="10" max="60" value="${escapeHtml(st.longRunMaxKm)}" /></label>
          <div class="stack" style="gap:6px;">
            <label class="card-note"><input type="checkbox" id="dp-set-longride" ${st.includeLongRide ? "checked" : ""} /> Langes Rad einplanen (1× pro Woche)</label>
            <label class="card-note"><input type="checkbox" id="dp-set-stabi" ${st.includeLegStabi ? "checked" : ""} /> Bein-Stabi wieder einplanen</label>
            <label class="card-note"><input type="checkbox" id="dp-set-super" ${st.includeLegSupersets ? "checked" : ""} /> Bein-Supersätze wieder einplanen</label>
          </div>
        </div>
        <button class="btn-small" type="button" id="dp-set-save" style="margin-top:10px;">Einstellungen speichern</button>
      </div>
    </div>`;

  dpBindDienstplan(panel);
}

function dpBindDienstplan(panel) {
  const $ = (id) => document.getElementById(id);

  $("dp-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const statusEl = $("dp-upload-status");
    statusEl.textContent = "Lese PDF…";
    try {
      const pages = await dpExtractPdfPages(file);
      const days = dpParseDienstplanItems(pages, dpSettings().kuerzel || "WL");
      if (!days.length) {
        DPUI.parsed = null;
        statusEl.textContent = "In dieser PDF wurde kein Dienstplan-Layout erkannt (Tagesblöcke mit Datum). Trag Schichten/Termine bitte unten von Hand ein.";
        return;
      }
      DPUI.parsed = days;
      DPUI.status = `${days.length} Tage gelesen.`;
      renderDienstplan();
      const rev = document.getElementById("dp-review");
      if (rev) rev.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      statusEl.textContent = "Konnte die PDF nicht lesen: " + (err && err.message ? err.message : err);
    }
  });

  const accept = $("dp-accept");
  if (accept) accept.addEventListener("click", async () => {
    const days = dpReadReview();
    const travel = dpSettings().travelMin;
    DPUI.parsed = null;
    DPUI.status = "";
    await applyPlanChange("Dienstplan übernommen", plan => dpMergeParsedDays(plan, days, travel));
  });
  const discard = $("dp-discard");
  if (discard) discard.addEventListener("click", () => { DPUI.parsed = null; DPUI.status = ""; renderDienstplan(); });

  $("dp-ics-export").addEventListener("click", () => downloadIcs(false));
  $("dp-ics-export-train").addEventListener("click", () => downloadIcs(true));
  $("dp-ev-add").addEventListener("click", async () => {
    const date = $("dp-ev-date").value, title = $("dp-ev-title").value.trim();
    if (!date || !title) { planToast("Bitte Titel und Datum angeben", ""); return; }
    const ev = eventFromForm({
      date, title, start: $("dp-ev-start").value, end: $("dp-ev-end").value,
      kind: $("dp-ev-kind").value, travelMin: $("dp-ev-travel").value,
    });
    await applyPlanChange("Termin gespeichert", plan => { plan.events = plan.events || []; plan.events.push(ev); });
  });

  $("dp-ics-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const list = parseIcsEvents(await file.text());
    const p = planInputs();
    const today = isoToday();
    DPUI.ics = list.filter(x => x.date >= today).map(x => {
      const dup = (p.events || []).some(o => o.date === x.date && o.start === x.start && o.title === x.title);
      return { ...x, dup, checked: !dup };
    });
    renderDienstplan();
  });
  const icsAccept = $("dp-ics-accept");
  if (icsAccept) icsAccept.addEventListener("click", async () => {
    const chosen = [];
    document.querySelectorAll(".dp-ics-ok").forEach(cb => { if (cb.checked) chosen.push(DPUI.ics[+cb.dataset.i]); });
    DPUI.ics = null;
    if (!chosen.length) { renderDienstplan(); return; }
    await applyPlanChange(`${chosen.length} Termine importiert`, plan => {
      plan.events = plan.events || [];
      chosen.forEach(x => {
        plan.events.push({
          id: `ics-${x.date}-${x.start.replace(":", "")}-${plan.events.length}`, date: x.date, title: x.title,
          kind: dpGuessKind(x.title), start: x.start, end: x.end, travelMin: /online|digital|zoom|teams/i.test(x.location + " " + x.title) ? 0 : null,
          note: x.location || "",
        });
      });
    });
  });

  // Liste: Zeiten ändern / löschen
  panel.querySelectorAll(".dp-row").forEach(row => {
    const type = row.dataset.type;
    const find = (plan) => type === "shift" ? (plan.shifts[row.dataset.date] || [])[+row.dataset.i]
      : type === "ev" ? plan.events[+row.dataset.i] : null;
    row.querySelectorAll("input").forEach(inp => inp.addEventListener("change", () => {
      dpStage(plan => {
        const obj = find(plan);
        if (!obj) return;
        if (inp.classList.contains("dp-ls")) obj.start = inp.value || null;
        if (inp.classList.contains("dp-le")) obj.end = inp.value || null;
        if (inp.classList.contains("dp-lt")) obj.title = inp.value.trim() || obj.title;
      });
    }));
    row.querySelector(".dp-del").addEventListener("click", async () => {
      await applyPlanChange("Eintrag gelöscht", plan => {
        if (type === "shift") {
          plan.shifts[row.dataset.date].splice(+row.dataset.i, 1);
          if (!plan.shifts[row.dataset.date].length) delete plan.shifts[row.dataset.date];
        } else if (type === "ev") plan.events.splice(+row.dataset.i, 1);
        else delete plan.dayStatus[row.dataset.date];
      });
    });
  });

  const saveAll = $("dp-save-all");
  if (saveAll) saveAll.addEventListener("click", () => dpCommit("Änderungen gespeichert"));

  $("dp-set-scale").addEventListener("input", (e) => { $("dp-set-scale-val").textContent = e.target.value; });
  $("dp-set-save").addEventListener("click", async () => {
    const settings = {
      travelMin: Math.max(0, parseInt($("dp-set-travel").value, 10) || 0),
      kuerzel: ($("dp-set-kz").value || "WL").trim().toUpperCase(),
      raceDate: $("dp-set-race").value || "2027-08-28",
      raceName: ($("dp-set-rname").value || "Wettkampf").trim(),
      raceDistanceKm: Math.max(1, Number($("dp-set-rdist").value) || 100),
      runScalePct: Math.min(130, Math.max(50, Number($("dp-set-scale").value) || 100)),
      longRunMaxKm: Math.min(60, Math.max(10, Number($("dp-set-longmax").value) || 36)),
      includeLongRide: $("dp-set-longride").checked, includeLegStabi: $("dp-set-stabi").checked, includeLegSupersets: $("dp-set-super").checked,
    };
    await applyPlanChange("Einstellungen gespeichert", plan => { plan.settings = { ...(plan.settings || {}), ...settings }; });
  });

}

/** Buttons der Plan-Status-Karte (steht im Coach-Tab). */
function bindPlanStatus(root) {
  if (!root) return;
  root.querySelectorAll("[data-plan-act]").forEach(btn => btn.addEventListener("click", () => {
    const act = btn.dataset.planAct;
    const mut = {
      sick: plan => { plan.sick = { from: isoToday(), to: null }; },
      healthy: plan => { const s = plan.sick || {}; plan.sick = { from: s.from || isoToday(), to: isoToday() }; },
      advance: plan => { plan.progression = { offsetWeeks: ((plan.progression || {}).offsetWeeks || 0) + 1 }; },
      hold: plan => { plan.progression = { offsetWeeks: ((plan.progression || {}).offsetWeeks || 0) - 1 }; },
    }[act];
    const label = { sick: "Krank gemeldet", healthy: "Wieder gesund", advance: "Fortschritt +1 Woche", hold: "Fortschritt −1 Woche" }[act];
    applyPlanChange(label, mut);
  }));
}
