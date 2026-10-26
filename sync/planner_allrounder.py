"""Allrounder-Wochenplan: Marathon-Aufbau + Kraft (Push / Pull / Beine).

Grundmuster (ohne Schichten, "Woche A"):

    Mo  Rad Z2 locker            + Push
    Di  Rad Schwelle (hart)      + Pull
    Mi  Rad Z2                   + Beine (schwer, alle Ketten)
    Do  Lauf Z2 ganz locker      + Core zu Hause (optional)
    Fr  Lauf VO2max (hart)       + Push
    Sa  Rad Z2 (ab Schritt 4: kurzer lockerer Lauf)  + Pull + Core im Studio (optional)
    So  Langer Lauf

Regeln, nach denen der Plan jede Woche neu zugeschnitten wird (Dienstplan, Termine, Krankheit, Verletzung):
  * hoechstens 2 harte Ausdauer-Einheiten (VO2max, Schwelle) + der lange Lauf, nie zwei harte Tage hintereinander
  * Push 2x, Pull 2x, Beine 1x pro Woche; gleiche Einheit mindestens 3 Tage Abstand (auch ueber den Wochenwechsel)
  * Beine nie am Tag einer harten Einheit und moeglichst nicht am Tag davor
  * Studio-Einheiten nach der Fruehschicht direkt am Arbeitsort, an Spaetschicht-Tagen nie (Einstellung gymOnLateShift)
  * eine Studio-Einheit pro Tag; Core optional (eine im Studio, eine zu Hause)
Gleiche Slot-Logik wie der klassische Planer (Rad nuechtern vor der Schicht, Laeufe nachmittags, ...).
"""

from __future__ import annotations

import itertools
from datetime import timedelta

import planner as pl
from planner import (exercises_for, fmt_km, hint_bike, interval_total_min, min_to_hm, mk_unit, run_minutes,
                     threshold_total_min, vo2_pace_text, vo2_rest_min)

# Wunschtage (0 = Montag) je Einheit, in Reihenfolge der Vorliebe
PREF = {
    "long":   [6, 5, 3, 2, 0, 1, 4],
    "vo2":    [4, 3, 1, 2, 0, 5, 6],
    "thr":    [1, 0, 2, 3, 4, 5, 6],
    "legs":   [2, 3, 1, 0, 4, 5, 6],
    "ezrun":  [3, 5, 0, 1, 2, 4, 6],
    "push":   [0, 4],
    "pull":   [1, 5],
    "core_home": [3, 6, 0, 2, 4, 1, 5],
}
MIN_GAP = 3        # gleiche Kraft-Einheit: mindestens 3 Tage Abstand (2 freie Tage dazwischen)


def pref_bonus(key: str, i: int) -> int:
    order = PREF[key]
    return 25 * (len(order) - order.index(i)) if i in order else 0


class AllrounderPlanner(pl.Planner):
    def plan_week(self, monday, ctxs, params, today, carry=None):
        st, lib = self.st, self.lib
        carry = carry if carry is not None else {}
        n = 7
        dates = [c.date for c in ctxs]
        placed = {i: [] for i in range(n)}
        roles: list[set] = [set() for _ in range(n)]
        missing: list[str] = []

        easy_only = [c.sick_return_level == "easy" for c in ctxs]
        level = [c.sick_return_level if isinstance(c.sick_return_level, float) else 1.0 for c in ctxs]
        pool = [i for i in range(n) if ctxs[i].kind != "krank" and not easy_only[i]]
        key_pool = [i for i in pool if level[i] >= 0.85]
        any_injury = any(c.injury_label for c in ctxs)
        phase = params["phase"]
        last_end = {i: None for i in range(n)}

        def commit(i, unit, start, dur):
            placed[i].append({"unit": unit, "start": start, "dur": dur})
            if start is not None:
                ctxs[i].allocate(start, dur)
                last_end[i] = max(last_end[i] or 0, start + dur)

        def tsuf(start, fasted=False):
            if start is None:
                return ""
            return f" · {min_to_hm(start)} Uhr" + (", nüchtern" if fasted else "")

        def note_missing(label):
            if key_pool and not any_injury:
                missing.append(label)

        # ---------------------------------------------------------------- Studio-Regeln
        late_from = int(st.get("lateShiftFromMin", 12 * 60))
        gym_late_ok = bool(st.get("gymOnLateShift"))

        def is_late(i):
            return ctxs[i].shift_start is not None and ctxs[i].shift_start >= late_from

        def at_work(i):
            return ctxs[i].shift_end is not None and not is_late(i)

        def gym_slot(i, dur):
            """Startzeit einer Studio-Einheit: direkt nach der Fruehschicht am Arbeitsort, sonst nachmittags."""
            c = ctxs[i]
            if at_work(i):
                start = c.shift_end + 20
                return start if start + dur + c.travel <= st["dayEndMin"] + 30 else None
            return self.slot_run(c, dur)

        forced = {}
        for d_iso, kind in (st.get("gymForce") or {}).items():
            try:
                fd = pl.parse_date(d_iso)
            except Exception:
                continue
            if fd in dates and kind in ("Push", "Pull") and ctxs[dates.index(fd)].kind != "krank":
                forced[dates.index(fd)] = kind

        def gym_ok(i, dur=60, min_level=0.7, allow_easy=False):
            usable = i in pool or (allow_easy and i in forced and ctxs[i].kind != "krank")
            return (usable and level[i] >= min_level and (gym_late_ok or not is_late(i) or i in forced)
                    and gym_slot(i, dur) is not None)

        # ---------------------------------------------------------------- Auswahlhelfer
        def choose(key, cands, dur, slot_fn, penalty=None):
            best = None
            for i in cands:
                start = slot_fn(ctxs[i], dur)
                if start is None:
                    continue
                score = ctxs[i].largest_window() + pref_bonus(key, i) - (penalty(i) if penalty else 0)
                if start >= 18 * 60:
                    score -= 200
                if best is None or score > best[0]:
                    best = (score, i)
            return best[1] if best else None

        def carry_gap(kind, i):
            """Tage seit der letzten Einheit dieser Art in der Vorwoche (None = unbekannt)."""
            last = carry.get(kind)
            return None if not last else (dates[i] - pl.parse_date(last)).days

        def adj(i, others, w):
            return sum(w for o in others if o is not None and abs(i - o) == 1)

        def carry_hard_pen(i, w=2500):
            last = carry.get("hardLast")
            return w if last and (dates[i] - pl.parse_date(last)).days == 1 else 0

        # ---------------------------------------------------------------- Kraft: Soll je Phase
        want = {"Push": 2, "Pull": 2, "Legs": 1}
        if phase == "wettkampf":
            want = {"Push": 1, "Pull": 1, "Legs": 0}
        if params.get("skipHeavy"):
            want["Legs"] = 0
        if any(c.sick_return_level is not None for c in ctxs):
            want["Pull"] = min(want["Pull"], 1)       # Wiedereinstieg: Push 2x, Pull nur 1x in dieser Woche
        light_week = params["recovery"] or params["factor"] < 0.85 or phase in ("taper", "erholung", "wettkampf")
        gym_dur = {"Push": int((lib.get("push") or {}).get("durationMin") or 60),
                   "Pull": int((lib.get("pull") or {}).get("durationMin") or 60),
                   "Legs": int((lib.get("heavyLegs") or {}).get("durationMin") or 65)}
        if light_week:
            gym_dur["Push"] = gym_dur["Pull"] = min(gym_dur["Push"], 45)

        # ---------------------------------------------------------------- 1.-4. harte Tage + Beine gemeinsam waehlen
        # Lange Einheit, VO2max, Schwelle und Beintag haengen voneinander ab (Abstand!). Statt nacheinander
        # zu raten, werden alle Kombinationen bewertet und die beste genommen.
        long_km = params["longKm"]
        long_dur = run_minutes(long_km) + 10
        reps = params["intervalReps"]
        thr = params["thresholdMin"]
        iv_dur = interval_total_min(reps, params["vo2Min"]) if reps >= 3 else 0
        want_long, want_vo2, want_thr = phase != "wettkampf", reps >= 3, bool(thr)
        win = [c.largest_window() for c in ctxs]
        MISSING = -6000

        def base_score(key, i, start, extra=0):
            sc = win[i] + pref_bonus(key, i) - extra
            return sc - 200 if start >= 18 * 60 else sc

        def opts(want_it, key, dur, slot_fn, extra_pen, ok):
            out = {}
            if not want_it:
                return out
            for i in key_pool:
                if not ok(ctxs[i]):
                    continue
                st_ = slot_fn(ctxs[i], dur)
                if st_ is not None:
                    out[i] = base_score(key, i, st_, extra_pen(i))
            return out

        long_opts = opts(want_long, "long", long_dur, self.slot_long, lambda i: carry_hard_pen(i, 1500),
                         lambda c: not c.no_run and not c.no_hard)
        vo2_opts = opts(want_vo2, "vo2", iv_dur, self.slot_run, lambda i: carry_hard_pen(i),
                        lambda c: not c.no_run and not c.no_hard)
        thr_opts = opts(want_thr, "thr", threshold_total_min(thr) if thr else 0, self.slot_bike_pm, lambda i: carry_hard_pen(i),
                        lambda c: not c.no_hard)
        legs_opts = {}
        if want["Legs"]:
            for i in key_pool:
                if not ctxs[i].no_legs and gym_ok(i, gym_dur["Legs"], 0.85):
                    legs_opts[i] = base_score("legs", i, gym_slot(i, gym_dur["Legs"]))

        def cyc_adj(a, b):
            return a is not None and b is not None and (a - b) % 7 in (1, 6)

        def legs_penalty(i, L, V, T):
            pen = 0
            hard = [h for h in (L, V, T) if h is not None]
            if any((h - i) % 7 == 1 for h in hard):
                pen += 3000                            # Beine am Tag vor einer harten Einheit
            if L is not None and (i - L) % 7 == 1:
                pen += 800                             # Tag nach dem langen Lauf
            if V is not None and (i - V) % 7 == 1:
                pen += 500
            if T is not None and (i - T) % 7 == 1:
                pen += 100
            gap = carry_gap("Legs", i)
            if gap is not None and gap < 5:
                pen += 300
            return pen

        best = None
        for L in [None] + sorted(long_opts):
            for V in [None] + sorted(vo2_opts):
                if V is not None and V == L:
                    continue
                for T in [None] + sorted(thr_opts):
                    if T is not None and T in (L, V):
                        continue
                    sc = 0
                    sc += long_opts[L] if L is not None else (MISSING if want_long and long_opts else 0)
                    sc += vo2_opts[V] if V is not None else (MISSING if want_vo2 and vo2_opts else 0)
                    sc += thr_opts[T] if T is not None else (MISSING if want_thr and thr_opts else 0)
                    if cyc_adj(V, L):
                        sc -= 3000
                    if cyc_adj(T, V):
                        sc -= 3000
                    if cyc_adj(T, L):
                        sc -= 2500
                    legs_best = None
                    if want["Legs"] and legs_opts:
                        for i, base_sc in legs_opts.items():
                            if i in (L, V, T):
                                continue
                            v = base_sc - legs_penalty(i, L, V, T)
                            if legs_best is None or v > legs_best[0]:
                                legs_best = (v, i)
                        sc += legs_best[0] if legs_best else MISSING
                    if best is None or sc > best[0]:
                        best = (sc, L, V, T, legs_best[1] if legs_best else None)
        li, ii, ti, legs_day = (best[1], best[2], best[3], best[4]) if best else (None, None, None, None)
        if li is not None:
            roles[li].add("long_run")
        elif want_long:
            note_missing("langer Lauf")
        if ii is not None:
            roles[ii].add("intervals")
        elif want_vo2:
            note_missing("VO2max-Intervalle")
        if ti is not None:
            roles[ti].add("threshold")
        elif want_thr:
            note_missing("Schwellentraining")
        if legs_day is not None:
            roles[legs_day].add("heavy_legs")
        elif want["Legs"]:
            note_missing("schweres Beintraining")
        hard_days = {d for d in (li, ii, ti) if d is not None}

        # ---------------------------------------------------------------- 5. Push / Pull
        free_gym = [i for i in range(n) if i != legs_day and gym_ok(i, 45, 0.5, allow_easy=True)]
        forced_push = {i for i, k in forced.items() if k == "Push" and i in free_gym}
        forced_pull = {i for i, k in forced.items() if k == "Pull" and i in free_gym}
        free_pull = [i for i in free_gym if not ctxs[i].no_pull]

        def spaced(days, kind):
            if len(days) == 2 and abs(days[0] - days[1]) < MIN_GAP:
                return False
            for d in days:
                g = carry_gap(kind, d)
                if g is not None and g < MIN_GAP:
                    return False
            return True

        def combos(pool_days, k, kind):
            if k == 0:
                yield ()
                return
            for c in itertools.combinations(pool_days, k):
                if spaced(list(c), kind):
                    yield c

        def pref_cost(days, key):
            targets = PREF[key]
            ds = sorted(days)
            ts = sorted(targets[:len(ds)])
            return sum(abs(a - b) for a, b in zip(ds, ts)) * 12

        best = None
        for attempt in (0, 1):
            if attempt == 1:
                if best is not None or not (forced_push or forced_pull):
                    break
                forced_push, forced_pull = set(), set()      # Wunschtage nicht machbar (Abstand/Belegung) -> normal planen
            for np_, nl in ((want["Push"], want["Pull"]), (want["Push"], max(0, want["Pull"] - 1)),
                            (max(0, want["Push"] - 1), want["Pull"]), (max(0, want["Push"] - 1), max(0, want["Pull"] - 1)),
                            (min(1, want["Push"]), 0), (0, min(1, want["Pull"]))):
                if np_ == 0 and nl == 0:
                    continue
                for pu in combos(free_gym, np_, "Push"):
                    if not forced_push <= set(pu):
                        continue
                    for pl_ in combos([d for d in free_pull if d not in pu], nl, "Pull"):
                        if not forced_pull <= set(pl_):
                            continue
                        cost = pref_cost(pu, "push") + pref_cost(pl_, "pull")
                        # harte Ausdauer am selben Tag ist ok (Oberkoerper), aber Beine-Tag und Folgetag leicht meiden
                        cost += sum(15 for d in pu + pl_ if legs_day is not None and d == legs_day + 1)
                        key = (-(np_ + nl), cost)
                        if best is None or key < best[0]:
                            best = (key, pu, pl_)
                if best is not None and -best[0][0] == want["Push"] + want["Pull"]:
                    break
        push_days, pull_days = (best[1], best[2]) if best else ((), ())
        for d in push_days:
            roles[d].add("push")
        for d in pull_days:
            roles[d].add("pull")
        if len(push_days) < want["Push"] or len(pull_days) < want["Pull"]:
            note_missing("Push/Pull (kein freier Studio-Tag)")

        # ---------------------------------------------------------------- 6. lockere Laeufe
        n_run_target = 1 if phase == "wettkampf" else params["runDays"]
        n_easy = max(0, n_run_target - (1 if li is not None else 0) - (1 if ii is not None else 0))
        z2_km = params["z2Km"]
        easy_days: list[int] = []
        for k in range(n_easy):
            def easy_pen(i):
                pen = 0
                if li is not None and (i - li) % 7 == 1:
                    pen += 1500                        # Back-to-Back nach dem langen Lauf vermeiden (Gelenke)
                if li is not None and i + 1 == li:
                    pen += 150                         # kurzer lockerer Lauf am Tag davor ist ok
                if ii is not None and i - 1 == ii:
                    pen += 200
                if i == legs_day:
                    pen += 400
                if ti is not None and i == ti:
                    pen += 1000
                if easy_days and any(abs(i - e) == 1 for e in easy_days):
                    pen += 60
                if i in push_days or i in pull_days:
                    pen += 20
                return pen
            km_k = z2_km if k == 0 else max(4.0, round(z2_km * 0.7 * 2) / 2)
            cands = [i for i in pool if i not in (li, ii, ti, legs_day) and i not in easy_days
                     and not ctxs[i].no_run and level[i] >= 0.5]
            ci = choose("ezrun", cands, run_minutes(km_k) + 10, self.slot_run, easy_pen)
            if ci is None:
                if key_pool and not any_injury:
                    note_missing("lockerer Lauf")
                break
            easy_days.append(ci)
            roles[ci].add("easy_run")
        easy_km = {easy_days[k]: (z2_km if k == 0 else max(4.0, round(z2_km * 0.7 * 2) / 2)) for k in range(len(easy_days))}

        # ---------------------------------------------------------------- 7. Studio direkt nach der Schicht
        gym_start = {}
        for d in list(push_days) + list(pull_days) + ([legs_day] if legs_day is not None else []):
            kind = "Push" if d in push_days else ("Pull" if d in pull_days else "Legs")
            gym_start[d] = gym_slot(d, gym_dur[kind])
            if at_work(d) and gym_start[d] is not None:
                c = ctxs[d]
                extra = (gym_start[d] + gym_dur[kind] + c.travel) - c.return_
                if extra > 0:
                    c.allocate(c.return_, extra)       # Heimweg verschiebt sich um die Studio-Zeit

        # ---------------------------------------------------------------- Einheiten je Tag
        core_home_day = None
        core_gym_day = None
        want_core = int(st.get("coreSessions", 2) or 0)
        if want_core >= 1 and phase != "wettkampf":
            # Studio-Core: an einem Studio-Tag (Pull bevorzugt), direkt hinter der Einheit
            gym_days = [d for d in list(pull_days) + list(push_days) if not ctxs[d].no_core]
            if gym_days and want_core >= 1:
                core_gym_day = gym_days[0]
            # Core zu Hause: Tag ohne Studio und ohne harte Einheit
            cands = [i for i in pool if i not in gym_start and i not in hard_days and not ctxs[i].no_core and level[i] >= 0.7]
            core_home_day = choose("core_home", cands, 12, self.slot_core)
            if want_core == 1 and core_home_day is not None:
                core_gym_day = None

        for i, ctx in enumerate(ctxs):
            if ctx.kind == "krank":
                continue
            lvl = level[i]
            if easy_only[i]:
                start = self.slot_fasted(ctx, 30) or self.slot_bike_pm(ctx, 30)
                commit(i, mk_unit("Rad Zone 1 (locker)", "rad", "pflicht",
                                  f"30 min, ganz entspannt – Wiedereinstieg nach der Krankheit{tsuf(start)}", 30,
                                  matchHint=hint_bike()), start, 30)
            r = roles[i]          # Wiedereinstiegstag: nur Rad Zone 1 - plus Push/Pull, wenn ausdruecklich gewuenscht (gymForce)

            # ---- Ausdauer
            if "long_run" in r:
                km = long_km if lvl >= 1 else max(6.0, round(long_km * lvl * 2) / 2)
                dur = run_minutes(km) + 10
                start = self.slot_long(ctx, dur)
                commit(i, mk_unit("Langer Lauf", "lauf", "pflicht",
                                  f"{fmt_km(km)} km · Zone 2 (130–140 bpm){tsuf(start)}, nach dem Frühstück", run_minutes(km),
                                  keySession=True,
                                  matchHint={"activityTypes": ["running"], "minDistanceKm": int(max(4, round(km * 0.8)))}),
                       start, dur)
            elif "threshold" in r:
                w = thr if lvl >= 0.85 else max(8, int(round(thr * 0.7)))
                dur = threshold_total_min(w)
                start = self.slot_bike_pm(ctx, dur) or self.slot_fasted(ctx, dur)
                commit(i, mk_unit("Schwellentraining Rad", "rad", "pflicht",
                                  f"15 min einrollen · 2×{w} min Zone 4 (Schwelle): {self.tg['thrLo']}–{self.tg['thrHi']} W "
                                  f"({int(round(self.tg['thrLo'] / self.tg['ftpW'] * 100))}–100 % deiner FTP von {self.tg['ftpW']} W"
                                  + (f", HF ca. {self.tg['thrHr'][0]}–{self.tg['thrHr'][1]} bpm" if self.tg["thrHr"] else "")
                                  + f", „kontrolliert unbequem“) · 5 min locker dazwischen · 10 min ausrollen{tsuf(start)}, nicht nüchtern",
                                  dur, keySession=True, matchHint=hint_bike()), start, dur)
            elif "intervals" not in r and "easy_run" not in r and not easy_only[i]:
                # taegliches Rad: nuechtern am Morgen, sonst nach Feierabend
                if ctx.bike_easy:
                    dur = 30 if ctx.kind != "free" else 40
                    start = self.slot_fasted(ctx, dur) or self.slot_bike_pm(ctx, dur)
                    commit(i, mk_unit("Rad Zone 1 (locker)", "rad", "ergaenzung",
                                      f"{dur} min, ganz entspannt (nur wenn schmerzfrei){tsuf(start, start is not None and start < 11 * 60)}", dur,
                                      matchHint=hint_bike()), start, dur)
                else:
                    dur = params["bikeMin"] if lvl >= 0.7 else min(45, params["bikeMin"])
                    start = self.slot_fasted(ctx, dur)
                    fasted = start is not None
                    if start is None:
                        start = self.slot_bike_pm(ctx, dur)
                    if start is not None:
                        commit(i, mk_unit("Rad Zone 2", "rad", "pflicht",
                                          f"{self.tg['z2Watt']} W · {dur} min{tsuf(start, fasted)}", dur, matchHint=hint_bike()), start, dur)
            if "intervals" in r:
                rp = reps if lvl >= 0.85 else max(3, reps - 1)
                vm = params["vo2Min"]
                dur = interval_total_min(rp, vm)
                start = self.slot_run(ctx, dur, after=(last_end[i] + 10) if last_end[i] else None)
                commit(i, mk_unit("VO2max-Intervalle", "lauf", "pflicht",
                                  f"{rp}×{vm} min ALL OUT" + (f" · {vo2_pace_text(self.tg, vm)}" if vo2_pace_text(self.tg, vm) else " (deutlich schneller als dein Schwellentempo)")
                                  + f" · je {vo2_rest_min(vm)} min locker traben · davor 15 min einlaufen, danach 10 min auslaufen{tsuf(start)}, nicht nüchtern",
                                  dur - 10, keySession=True, matchHint={"activityTypes": ["running"]}), start, dur)
            if "easy_run" in r:
                km = easy_km[i] if lvl >= 1 else max(4.0, round(easy_km[i] * lvl * 2) / 2)
                dur = run_minutes(km) + 10
                start = self.slot_run(ctx, dur, after=(last_end[i] + 10) if last_end[i] else None)
                if start is not None:
                    commit(i, mk_unit("Zone-2-Lauf", "lauf", "pflicht",
                                      f"{fmt_km(km)} km · ganz locker, 130–140 bpm{tsuf(start)}", run_minutes(km),
                                      matchHint={"activityTypes": ["running"], "minDistanceKm": int(max(3, round(km * 0.7)))}),
                           start, dur)

            # ---- Kraft (Studio)
            for kind, libkey, name in (("Push", "push", "Push"), ("Pull", "pull", "Pull"), ("Legs", "heavyLegs", "Schweres Beintraining")):
                is_mine = (kind == "Push" and i in push_days) or (kind == "Pull" and i in pull_days) or (kind == "Legs" and i == legs_day)
                if not is_mine:
                    continue
                dur = gym_dur[kind]
                if at_work(i):
                    start = gym_start.get(i)           # direkt nach der Schicht am Arbeitsort
                else:                                  # sonst hinter die schon geplanten Einheiten des Tages
                    start = self.slot_run(ctx, dur, after=(last_end[i] + 10) if last_end[i] else None)
                if start is None:
                    note_missing(name)
                    continue
                entry = lib.get(libkey) or {}
                detail = entry.get("detail") or name
                lighter = light_week or lvl < 0.85 or easy_only[i]
                if lighter:
                    detail += " · leichter: 1 Satz weniger je Übung, Gewicht etwas runter"
                where = " · im Studio direkt nach der Schicht" if at_work(i) else ""
                commit(i, mk_unit(name, "kraft", "pflicht", f"{detail}{where}{tsuf(start)}", dur,
                                  exercises=exercises_for(lib, libkey), matchHint={"activityTypes": ["strength_training"]}),
                       start, dur)
                if i == core_gym_day:
                    cg = lib.get("coreGym") or {}
                    cdur = int(cg.get("durationMin") or 15)
                    commit(i, mk_unit("Core (Studio)", "core", "bonus", f"{cg.get('detail') or '15 min'} · optional{' · im Studio direkt nach der Schicht' if at_work(i) else ''}{tsuf(start + dur + 5)}", cdur,
                                      exercises=exercises_for(lib, "coreGym"),
                                      matchHint={"activityTypes": ["strength_training", "cardio"]}), start + dur + 5, cdur)
            if i == core_home_day:
                ch = lib.get("core") or {}
                cdur = int(ch.get("durationMin") or 12)
                start = self.slot_core(ctx, cdur, after=(last_end[i] + 10) if last_end[i] else None)
                commit(i, mk_unit("Core (zu Hause)", "core", "bonus", f"{ch.get('detail') or '12 min'} · optional{tsuf(start)}", cdur,
                                  exercises=exercises_for(lib, "core"),
                                  matchHint={"activityTypes": ["strength_training", "cardio"]}), start, cdur)

        # Uebergabe an die naechste Woche
        for kind, days in (("Push", push_days), ("Pull", pull_days), ("Legs", [legs_day] if legs_day is not None else [])):
            if days:
                carry[kind] = pl.iso(dates[max(days)])
        if hard_days:
            carry["hardLast"] = pl.iso(dates[max(hard_days)])
        else:
            carry.pop("hardLast", None)
        return placed, roles, missing
