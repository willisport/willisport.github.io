/* ---------------------------------------------------------------------------
   Plan per Text aendern: "Mittwoch Pull", "Freitag frei", "Samstag Lauf 8 km",
   "morgen kein Kraft", "Donnerstag Beine". Der Text wird in Planer-Einstellungen
   uebersetzt (gymForce, legsForce, runKmDay, restDays ...); der Planer rechnet den Rest
   neu - z. B. rueckt die naechste Pull-Einheit automatisch nach hinten (Mindestabstand).
   --------------------------------------------------------------------------- */

const PCMD_WEEKDAYS = { montag: 0, dienstag: 1, mittwoch: 2, donnerstag: 3, freitag: 4, samstag: 5, sonntag: 6 };
const PCMD_WD_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const PCMD_KIND_LABEL = { Pull: "Pull", Push: "Push", Legs: "schwere Beine", Run: "Lauf", Rest: "Ruhetag", NoGym: "kein Kraft" };

function pcmdNorm(s) {
  return String(s || "").toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss").replace(/\s+/g, " ").trim();
}

function pcmdWeekdayIndex(iso) { return (new Date(iso + "T12:00:00").getDay() + 6) % 7; }

/** Datum aus einem Textstueck: heute / morgen / uebermorgen / Wochentag (naechstes Vorkommen) / 10.11. / 10.11.2026 */
function pcmdFindDate(seg, todayIso) {
  let m = seg.match(/\b(\d{1,2})\.\s?(\d{1,2})\.?(\d{4})?(?!\s*km|\d)/);
  if (m) {
    const day = +m[1], mon = +m[2];
    if (day >= 1 && day <= 31 && mon >= 1 && mon <= 12) {
      let year = m[3] ? +m[3] : +todayIso.slice(0, 4);
      let iso = `${year}-${String(mon).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      if (!m[3] && iso < isoAddDays(todayIso, -60)) iso = `${year + 1}${iso.slice(4)}`;
      return { date: iso, rest: seg.replace(m[0], " ") };
    }
  }
  if (/\buebermorgen\b/.test(seg)) return { date: isoAddDays(todayIso, 2), rest: seg.replace(/\buebermorgen\b/, " ") };
  if (/\bmorgen\b/.test(seg)) return { date: isoAddDays(todayIso, 1), rest: seg.replace(/\bmorgen\b/, " ") };
  if (/\bheute\b/.test(seg)) return { date: todayIso, rest: seg.replace(/\bheute\b/, " ") };
  m = seg.match(/\b(?:(naechsten|naechste|kommenden)\s+)?(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b/);
  if (m) {
    const target = PCMD_WEEKDAYS[m[2]];
    let diff = (target - pcmdWeekdayIndex(todayIso) + 7) % 7;
    if (diff === 0 && m[1]) diff = 7;
    return { date: isoAddDays(todayIso, diff), rest: seg.replace(m[0], " ") };
  }
  return null;
}

/** Aktionen eines Textstuecks (ohne Datum): Pull, Push, Beine, Lauf [km], frei/Ruhetag, kein Kraft */
function pcmdFindKinds(rest) {
  const kinds = [];
  if (/\b(kein|keine|ohne)\s+(kraft|krafttraining|studio|gym)\b/.test(rest)) return [{ kind: "NoGym" }];
  if (/\b(frei|ruhetag|ruhe|pause|restday|rest day|rest-day)\b/.test(rest)) return [{ kind: "Rest" }];
  if (/\bpull\b/.test(rest)) kinds.push({ kind: "Pull" });
  if (/\bpush\b/.test(rest)) kinds.push({ kind: "Push" });
  if (/\b(beine|beintraining|schwere beine|legs)\b/.test(rest)) kinds.push({ kind: "Legs" });
  if (/\b(lauf|laufen|laufe|joggen|zone ?2)\b/.test(rest) || /\d\s*km\b/.test(rest)) {
    const km = rest.match(/(\d+(?:[.,]\d+)?)\s*km/);
    kinds.push({ kind: "Run", km: km ? Math.min(60, Math.max(2, parseFloat(km[1].replace(",", ".")))) : null });
  }
  return kinds;
}

/** Text -> { actions: [{date, kind, km}], errors: [Textstueck, ...] } */
function parsePlanCommand(text, todayIso) {
  const actions = [], errors = [];
  let lastDate = null;
  pcmdNorm(text).replace(/(\d),(\d)/g, "$1.$2").split(/[;\n,+]| und /).map(s => s.trim()).filter(Boolean).forEach(seg => {
    const found = pcmdFindDate(seg, todayIso);
    const date = found ? found.date : lastDate;
    const kinds = pcmdFindKinds(found ? found.rest : seg);
    if (found) lastDate = found.date;
    if (!date || !kinds.length) {
      if (found && !kinds.length) return;          // nur ein Datum ("Mittwoch") - Datum merken fuer das naechste Stueck
      errors.push(kinds.length ? `${seg} (welcher Tag?)` : seg);
      return;
    }
    kinds.forEach(k => actions.push({ date, ...k }));
  });
  return { actions, errors };
}

function pcmdDescribe(a) {
  const d = `${PCMD_WD_SHORT[pcmdWeekdayIndex(a.date)]} ${fmtDateShort(a.date)}`;
  return `${d}: ${PCMD_KIND_LABEL[a.kind]}${a.kind === "Run" && a.km ? ` ${String(a.km).replace(".", ",")} km` : ""}`;
}

/** Aktionen in die Plan-Einstellungen schreiben (Widersprueche am selben Tag werden aufgeraeumt). */
function pcmdApply(plan, actions) {
  const st = plan.settings = plan.settings || {};
  const list = k => (st[k] = Array.isArray(st[k]) ? st[k] : []);
  const map = k => (st[k] = st[k] && typeof st[k] === "object" && !Array.isArray(st[k]) ? st[k] : {});
  const add = (k, d) => { const l = list(k); if (!l.includes(d)) l.push(d); l.sort(); };
  const rm = (k, d) => { st[k] = list(k).filter(x => x !== d); };
  actions.forEach(a => {
    const d = a.date;
    if (a.kind === "Pull" || a.kind === "Push") { map("gymForce")[d] = a.kind; rm("noGymDays", d); rm("restDays", d); rm("legsForce", d); }
    else if (a.kind === "Legs") { add("legsForce", d); delete map("gymForce")[d]; rm("noGymDays", d); rm("restDays", d); }
    else if (a.kind === "Run") {
      if (a.km) { map("runKmDay")[d] = a.km; rm("runForceDays", d); } else { add("runForceDays", d); }
      rm("restDays", d);
    }
    else if (a.kind === "Rest") {
      add("restDays", d);
      delete map("gymForce")[d]; delete map("runKmDay")[d]; rm("runForceDays", d); rm("legsForce", d); rm("noGymDays", d);
    }
    else if (a.kind === "NoGym") { add("noGymDays", d); delete map("gymForce")[d]; rm("legsForce", d); }
  });
  // Eintraege, die laenger als 30 Tage zurueckliegen, aufraeumen
  const cutoff = isoAddDays(isoToday(), -30);
  ["restDays", "legsForce", "runForceDays", "noGymDays"].forEach(k => { st[k] = list(k).filter(x => x >= cutoff); });
  ["gymForce", "runKmDay"].forEach(k => { Object.keys(map(k)).forEach(x => { if (x < cutoff) delete st[k][x]; }); });
}

/** Steht der Wunsch nach dem Sync wirklich im Plan? */
function pcmdCheck(a) {
  const wk = PLAN_DATA && PLAN_DATA.weeks && PLAN_DATA.weeks[isoMondayOf(a.date)];
  const day = wk && wk.days && wk.days[weekdayNameOf(a.date)];
  if (!day) return null;
  const names = (day.units || []).map(u => u.name);
  if (a.kind === "Pull" || a.kind === "Push") return names.includes(a.kind);
  if (a.kind === "Legs") return names.includes("Schweres Beintraining");
  if (a.kind === "Run") return names.some(n => /^(Zone-2-Lauf|Langer Lauf|VO2max-Intervalle|Backyard-Simulation)/.test(n));
  if (a.kind === "Rest") return names.length === 0;
  if (a.kind === "NoGym") return !names.some(n => n === "Push" || n === "Pull" || n === "Schweres Beintraining");
  return null;
}

function planCommandCardHtml() {
  if (!canEdit()) return "";
  return `
    <div class="card pcmd-card">
      <div class="card-head"><span class="card-title">Plan per Text ändern</span><span class="card-note">z. B. „Mittwoch Pull“ · „Freitag frei“ · „Samstag Lauf 8 km“ · „morgen kein Kraft“</span></div>
      <div class="pcmd-row"><input id="pcmd-input" class="text-input" type="text" autocomplete="off" autocapitalize="sentences" placeholder="Was soll sich ändern?" /><button class="btn-small" id="pcmd-go" type="button">Ändern</button></div>
      <div id="pcmd-feedback" class="pcmd-feedback card-note"></div>
    </div>`;
}

function pcmdSetFeedback(html, tone) {
  const el = document.getElementById("pcmd-feedback");
  if (!el) return;
  el.innerHTML = html;
  el.dataset.tone = tone || "";
}

function pcmdPreview() {
  const input = document.getElementById("pcmd-input");
  if (!input) return null;
  const text = input.value.trim();
  if (!text) { pcmdSetFeedback("", ""); return null; }
  const { actions, errors } = parsePlanCommand(text, isoToday());
  if (errors.length) {
    pcmdSetFeedback(`Nicht verstanden: „${escapeHtml(errors.join(", "))}“. Beispiel: „Mittwoch Pull“.`, "warn");
    return null;
  }
  if (!actions.length) { pcmdSetFeedback("", ""); return null; }
  pcmdSetFeedback(actions.map(a => `<span class="pcmd-chip">${escapeHtml(pcmdDescribe(a))}</span>`).join(" "), "ok");
  return actions;
}

let PCMD_BUSY = false;
async function pcmdRun() {
  if (PCMD_BUSY) return;
  const input = document.getElementById("pcmd-input");
  const actions = pcmdPreview();
  if (!input || !actions) { if (input && !input.value.trim()) pcmdSetFeedback("Schreib z. B. „Mittwoch Pull“.", "warn"); return; }
  PCMD_BUSY = true;
  const btn = document.getElementById("pcmd-go");
  if (btn) btn.disabled = true;
  try {
    pcmdSetFeedback(`<span class="pcmd-chip">${actions.map(pcmdDescribe).map(escapeHtml).join(" · ")}</span> · wird gespeichert, der Planer rechnet neu (ca. 1–2 Minuten) …`, "ok");
    const ok = await applyPlanChange(actions.map(pcmdDescribe).join(" · "), plan => pcmdApply(plan, actions));
    input.value = "";
    if (ok === false) { pcmdSetFeedback("Speichern hat nicht geklappt – bitte nochmal versuchen.", "warn"); return; }
    const failed = actions.filter(a => pcmdCheck(a) === false);
    if (failed.length) {
      pcmdSetFeedback(`Gespeichert, aber nicht umsetzbar (Termine, Abstand oder Schicht): ${failed.map(a => escapeHtml(pcmdDescribe(a))).join(" · ")}. Der Planer hat den Rest regelkonform neu verteilt.`, "warn");
    } else {
      pcmdSetFeedback(`Fertig: ${actions.map(a => escapeHtml(pcmdDescribe(a))).join(" · ")}. Folge-Einheiten wurden automatisch angepasst (Mindestabstände).`, "ok");
    }
  } catch (err) {
    pcmdSetFeedback(`Fehler: ${escapeHtml(String(err && err.message || err))}`, "warn");
  } finally {
    PCMD_BUSY = false;
    const b = document.getElementById("pcmd-go");
    if (b) b.disabled = false;
  }
}

document.addEventListener("input", (e) => { if (e.target && e.target.id === "pcmd-input") pcmdPreview(); });
document.addEventListener("keydown", (e) => { if (e.target && e.target.id === "pcmd-input" && e.key === "Enter") { e.preventDefault(); pcmdRun(); } });
document.addEventListener("click", (e) => { if (e.target && e.target.id === "pcmd-go") pcmdRun(); });
