/* Plan-Steuerung: Eingaben (Dienstplan, Termine, Einstellungen, Krankheit,
   Fortschritt, Übungsbibliothek) werden verschlüsselt in den Overrides unter
   "__plan" gespeichert. Der Planer im Sync (sync/planner.py) erzeugt daraus den
   kompletten Plan bis September 2027 - die Website liefert nur die Eingaben und
   zeigt das Ergebnis. Kein Claude, keine KI, keine Kosten. */

let PLAN_DATA = null;          // entschlüsselter Langzeitplan (data/plan.enc.json)
let PLAN_BUSY = false;
let PLAN_PENDING = false;

function setPlanData(plan) {
  PLAN_DATA = plan;
  if (typeof APP_DATA !== "undefined" && APP_DATA) {
    try { renderWoche(APP_DATA); } catch (e) { console.error(e); }
    try { renderDienstplan(); } catch (e) { console.error(e); }
  }
}

function planInputs() {
  const o = loadOverrides();
  return o.__plan || {};
}

function isoToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function isoAddDays(iso, n) {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function isoMondayOf(iso) {
  const d = new Date(iso + "T12:00:00");
  const wd = (d.getDay() + 6) % 7;
  return isoAddDays(iso, -wd);
}
function weekdayNameOf(iso) {
  return ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"][new Date(iso + "T12:00:00").getDay()];
}

/* ---------------------------------------------------------------------------
   Speichern -> Sync -> neuer Plan
   --------------------------------------------------------------------------- */

async function pushOverridesNow(overrides) {
  if (typeof IS_HOSTED === "undefined" || !IS_HOSTED || !CURRENT_DEK || !canEdit()) return null;
  if (!OVERRIDES_SERVER_LOADED) throw new Error("Der gespeicherte Stand konnte noch nicht geladen werden – bitte Seite neu laden und nochmal versuchen.");
  clearTimeout(overridesPushTimer);
  const encrypted = await encryptJson(CURRENT_DEK, overrides);
  const res = await fetch(HOSTED_SYNC_WORKER_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "save-overrides", payload: encrypted }),
  });
  const out = await res.json().catch(() => ({}));
  if (!res.ok || out.ok === false) throw new Error(out.error || `Speichern fehlgeschlagen (${res.status})`);
  return encrypted;
}

async function waitForOverridesOnServer(iv, maxMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    await new Promise(r => setTimeout(r, 6000));
    try {
      const file = await fetchFreshFile("data/overrides.enc.json");
      if (file && file.iv === iv) return true;
    } catch { /* weiter versuchen */ }
  }
  return false;
}

function planToast(title, text, ms = 8000) {
  showToast(`<div class="title">${escapeHtml(title)}</div>${text ? `<div>${escapeHtml(text)}</div>` : ""}`, ms);
}

async function queuePlanSync(label) {
  if (PLAN_BUSY) { PLAN_PENDING = true; return true; }
  PLAN_BUSY = true;
  try {
    do {
      PLAN_PENDING = false;
      planToast(label, "Wird gespeichert, danach rechnet der Planer neu (ca. 1–2 Minuten)…", 180000);
      const encrypted = await pushOverridesNow(loadOverrides());
      if (!encrypted) return true;
      const onServer = await waitForOverridesOnServer(encrypted.iv);
      if (!onServer) throw new Error("Speichern hat zu lange gedauert – bitte „Sync auslösen“ drücken.");
      const ok = await runHostedSync(renderAll, (t, x) => planToast(t, x, 180000));
      if (ok) planToast("Plan aktualisiert", "Der neue Plan ist jetzt in Heute, Woche und Telegram sichtbar.", 6000);
    } while (PLAN_PENDING);
    return true;
  } catch (err) {
    planToast("Plan konnte nicht aktualisiert werden", String(err.message || err), 12000);
    return false;
  } finally {
    PLAN_BUSY = false;
  }
}

/** Ändert die Plan-Eingaben (__plan) und stößt die Neuberechnung an. */
async function applyPlanChange(label, mutator) {
  if (!canEdit()) return false;
  const o = loadOverrides();
  o.__plan = o.__plan || { version: 1 };
  mutator(o.__plan);
  saveOverrides(o, { push: false });
  try {
    if (typeof PRISTINE_DATA !== "undefined" && PRISTINE_DATA) renderAll();
    else renderDienstplan();
  } catch (e) { console.error(e); }
  if (typeof IS_HOSTED === "undefined" || !IS_HOSTED) {
    planToast(label, "Lokal gespeichert (ohne gehostete Version wird kein Plan neu berechnet).");
    return true;
  }
  return queuePlanSync(label);
}

/* ---------------------------------------------------------------------------
   Dienstplan-PDF lesen (Layout: ein Block pro Tag, Stunden-Spalten mit je zwei
   Halbstunden-Zellen, Kürzel in den Zellen, rechts eine Notizen-Spalte)
   --------------------------------------------------------------------------- */

const DP_WEEKDAY_RE = /Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag/;

function dpPad(n) { return String(n).padStart(2, "0"); }
function dpMinToHm(min) { min = Math.round(min); return `${dpPad(Math.floor(min / 60) % 24)}:${dpPad(min % 60)}`; }

/** pages: Array von Seiten, jede Seite = Array von {str, x, y} (y von oben nach unten). */
function dpParseDienstplanItems(pages, kuerzel = "WL") {
  const days = [];
  const kz = kuerzel.trim().toUpperCase();
  pages.forEach(rawItems => {
    const its = rawItems.map(i => ({ t: (i.str || "").trim(), x: i.x, y: i.y })).filter(i => i.t);
    const headers = [];
    its.forEach(it => {
      const m = it.t.match(/(\d{2})\.(\d{2})\.(\d{4})/);
      if (!m) return;
      const hasWeekday = DP_WEEKDAY_RE.test(it.t) || its.some(o => Math.abs(o.y - it.y) < 3 && DP_WEEKDAY_RE.test(o.t));
      if (hasWeekday) headers.push({ y: it.y, date: `${m[3]}-${m[2]}-${m[1]}` });
    });
    headers.sort((a, b) => a.y - b.y);

    headers.forEach((h, hi) => {
      const yTop = h.y - 3;
      const yBot = hi + 1 < headers.length ? headers[hi + 1].y - 3 : Infinity;
      const block = its.filter(o => o.y >= yTop && o.y < yBot);
      const labels = block.filter(o => /^\d{2}:00$/.test(o.t) && o.y > h.y && o.y < h.y + 30)
        .filter(o => parseInt(o.t, 10) <= 21).sort((a, b) => a.x - b.x);
      if (labels.length < 3) return;
      const first = labels[0], last = labels[labels.length - 1];
      const h0 = parseInt(first.t, 10), h1 = parseInt(last.t, 10);
      const perHour = (last.x - first.x) / (h1 - h0);
      if (!(perHour > 5)) return;
      const notizen = block.find(o => o.t === "Notizen");
      const notesX = notizen ? notizen.x - 6 : Infinity;
      const toMin = x => Math.round((h0 + (x - first.x - 1.0) / perHour) * 2) / 2 * 60;

      const wl = block.filter(o => o.t.toUpperCase() === kz && o.x < notesX && o.y > h.y + 20);
      const rows = {};
      wl.forEach(o => { (rows[Math.round(o.y / 3)] = rows[Math.round(o.y / 3)] || []).push(o); });
      const shifts = [];
      Object.values(rows).forEach(ws => {
        ws.sort((a, b) => a.x - b.x);
        let run = [ws[0]];
        const flush = () => {
          const start = toMin(run[0].x);
          shifts.push({ start: dpMinToHm(start), end: dpMinToHm(start + 30 * run.length) });
        };
        for (let i = 1; i < ws.length; i++) {
          if (ws[i].x - run[run.length - 1].x <= perHour / 2 * 1.6) run.push(ws[i]);
          else { flush(); run = [ws[i]]; }
        }
        flush();
      });

      const noteItems = block.filter(o => o.x >= notesX && o.y > h.y + 14 && o.t !== "Notizen");
      const lineMap = {};
      noteItems.forEach(o => { (lineMap[Math.round(o.y / 4)] = lineMap[Math.round(o.y / 4)] || []).push(o); });
      const notes = Object.keys(lineMap).map(Number).sort((a, b) => a - b)
        .map(k => lineMap[k].sort((a, b) => a.x - b.x).map(o => o.t).join(" "));

      days.push({ date: h.date, shifts, notes, ...dpInterpretNotes(notes, kz) });
    });
  });
  days.sort((a, b) => a.date.localeCompare(b.date));
  return days;
}

/** Notizen der Spalte rechts auswerten - nur Zeilen, die das eigene Kürzel enthalten. */
function dpInterpretNotes(lines, kz) {
  const kzRe = new RegExp(`(^|[^A-ZÄÖÜa-zäöü])${kz}([^A-ZÄÖÜa-zäöü]|$)`, "i");
  const timeRe = /(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})/;
  const kuerzelOnly = /^([A-ZÄÖÜ]{2,3}[\s,\-/]*)+$/;
  const events = [];
  let status = null;
  lines.forEach((line, k) => {
    if (!kzRe.test(line)) return;
    if (/frei/i.test(line)) { status = status || "frei"; return; }
    if (/urlaub|\burl\b/i.test(line)) { status = "urlaub"; return; }
    if (/\buni\b/i.test(line)) { if (status !== "urlaub") status = "uni"; return; }
    // Kürzel-Zeile eines Termin-Blocks: davor steht ggf. die Zeitspanne, davor der Titel
    let timeIdx = -1;
    for (let j = k - 1; j >= Math.max(0, k - 3); j--) {
      if (timeRe.test(lines[j])) { timeIdx = j; break; }
    }
    const titleLines = [];
    for (let j = (timeIdx >= 0 ? timeIdx : k) - 1; j >= Math.max(0, (timeIdx >= 0 ? timeIdx : k) - 3); j--) {
      if (kuerzelOnly.test(lines[j]) || timeRe.test(lines[j])) break;
      titleLines.unshift(lines[j]);
    }
    const title = titleLines.join(" ").replace(/\s+/g, " ").trim();
    if (timeIdx >= 0) {
      const m = lines[timeIdx].match(timeRe);
      events.push({
        title: title || "Termin laut Dienstplan", kind: /schul|seminar|uni/i.test(title) ? "schule" : "termin",
        start: `${dpPad(+m[1])}:${m[2]}`, end: `${dpPad(+m[3])}:${m[4]}`,
      });
    } else if (/schul|seminar/i.test(title)) {
      if (status !== "urlaub") status = "uni";
    }
  });
  return { events, status };
}

async function dpExtractPdfPages(file) {
  if (typeof pdfjsLib === "undefined") throw new Error("PDF-Bibliothek nicht geladen (Internetverbindung prüfen)");
  const buf = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
  const pages = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const height = page.view[3];
    const content = await page.getTextContent();
    pages.push(content.items.filter(it => it.transform).map(it => ({ str: it.str, x: it.transform[4], y: height - it.transform[5] })));
  }
  return pages;
}

/** Ergebnis der PDF-Auswertung in die Eingaben einmischen (ersetzt nur Tage, die im PDF stehen). */
function dpMergeParsedDays(plan, days, travelMin) {
  plan.shifts = plan.shifts || {};
  plan.events = plan.events || [];
  plan.dayStatus = plan.dayStatus || {};
  const covered = new Set(days.map(d => d.date));
  plan.events = plan.events.filter(e => !(String(e.id || "").startsWith("dp-") && covered.has(e.date)));
  days.forEach(d => {
    if (d.shifts.length) plan.shifts[d.date] = d.shifts.map(s => ({ start: s.start, end: s.end, label: "Arbeit" }));
    else delete plan.shifts[d.date];
    delete plan.dayStatus[d.date];
    if (d.status) plan.dayStatus[d.date] = { kind: d.status };
    d.events.forEach(ev => {
      const dup = plan.events.some(o => o.date === d.date && o.start === ev.start);
      if (dup) return;
      plan.events.push({
        id: `dp-${d.date}-${ev.start.replace(":", "")}`, date: d.date, title: ev.title, kind: ev.kind,
        start: ev.start, end: ev.end, travelMin: travelMin, note: "aus Dienstplan",
      });
    });
  });
}

/* ---------------------------------------------------------------------------
   Termine: ICS-Datei lesen (Google/Apple/Outlook-Export)
   --------------------------------------------------------------------------- */

function icsToLocalParts(value, tzid, isUtc) {
  // value: 20261007T090000(Z) oder 20261007
  const m = value.match(/^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?(Z)?$/);
  if (!m) return null;
  if (!m[4]) return { date: `${m[1]}-${m[2]}-${m[3]}`, time: null };
  if (isUtc || m[7]) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)));
    const parts = new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(d).reduce((a, p) => { a[p.type] = p.value; return a; }, {});
    return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour === "24" ? "00" : parts.hour}:${parts.minute}` };
  }
  return { date: `${m[1]}-${m[2]}-${m[3]}`, time: `${m[4]}:${m[5]}` };
}

function parseIcsEvents(text) {
  const unfolded = text.replace(/\r?\n[ \t]/g, "");
  const out = [];
  const blocks = unfolded.split(/BEGIN:VEVENT/).slice(1);
  blocks.forEach(b => {
    const body = b.split(/END:VEVENT/)[0];
    const get = (name) => {
      const re = new RegExp(`^${name}((?:;[^:\\n]*)?):(.*)$`, "mi");
      const m = body.match(re);
      return m ? { params: m[1] || "", value: m[2].trim() } : null;
    };
    const ds = get("DTSTART"), de = get("DTEND"), su = get("SUMMARY"), lo = get("LOCATION");
    if (!ds || !su) return;
    const s = icsToLocalParts(ds.value, null, ds.value.endsWith("Z"));
    const e = de ? icsToLocalParts(de.value, null, de.value.endsWith("Z")) : null;
    if (!s || !s.time) return;   // ganztägige Einträge überspringen
    out.push({
      date: s.date, start: s.time, end: e && e.date === s.date ? e.time : null,
      title: su.value.replace(/\\,/g, ",").replace(/\\n/g, " ").replace(/\s+/g, " ").slice(0, 90),
      location: lo ? lo.value.replace(/\\,/g, ",") : "",
      recurring: /^RRULE:/mi.test(body),
    });
  });
  return out.sort((a, b) => (a.date + a.start).localeCompare(b.date + b.start));
}

function eventFromForm({ date, start, end, title, kind, travelMin }) {
  return {
    id: `m-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
    date, start: start || null, end: end || null, title: (title || "Termin").slice(0, 90),
    kind: kind || "termin", travelMin: travelMin === "" || travelMin == null ? null : Number(travelMin), note: "",
  };
}
