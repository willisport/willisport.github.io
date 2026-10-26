# Trainingsregeln des Planers (Stand 26.10.2026)

Der Planer (`sync/planner.py`, `sync/planner_allrounder.py`) richtet sich nach diesen Regeln. Jede Regel hat eine Begründung aus der Studienlage und steht als automatischer Test in `sync/test_allrounder.py`. Wo die Studienlage dünn ist, steht das dabei – es gibt keinen „perfekten“ Plan, nur einen begründeten.

## 1. Kraft und Ausdauer zusammen

| Regel | Begründung | Im Planer |
|---|---|---|
| Kraft und Ausdauer an **getrennten Tagen**, sonst **mindestens 6 Stunden Abstand**; am selben Tag zuerst Kraft | Interferenzeffekt: v. a. Schnellkraft und Beinkraft leiden, wenn beides direkt hintereinander kommt ([Meta-Analyse zur Reihenfolge](https://pmc.ncbi.nlm.nih.gov/articles/PMC5752732/), [Übersicht 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11359207/)). Die 6 Stunden sind eine Faustregel, kein gemessener Grenzwert. | Beintraining nie am Tag einer harten Einheit oder des langen Laufs; Läufe und Beine möglichst an verschiedenen Tagen |
| **Push 2×, Pull 2×, Beine 1×** pro Woche | Bei gleichem Gesamtvolumen sind 2× und 3× pro Muskelgruppe etwa gleich wirksam ([Schoenfeld 2019](https://mennohenselmans.com/training-frequency-2018-meta-analysis-review/), [Schoenfeld 2016](https://pubmed.ncbi.nlm.nih.gov/27102172/)). Die Beine bekommen durch das Laufen zusätzlich Reize. | `want = Push 2, Pull 2, Legs 1` |
| **3 freie Tage** zwischen gleichen Einheiten (Push Di → Sa) | Willis Regel für volle Erholung; liegt auf der sicheren Seite. Die Studien verlangen es nicht streng. | `MIN_GAP = 4`, gilt auch über den Wochenwechsel |
| Push und Pull **wechseln sich ab** | Gleichmäßige Belastung des Oberkörpers, keine zwei gleichen Einheiten hintereinander | Kostenfunktion in der Planung |
| Schwere Beine (Kniebeuge, Kreuzheben) bleiben im Plan, **schwer statt nur viele Wiederholungen** | Schweres Krafttraining und Sprungtraining verbessern die Laufökonomie um etwa 2–8 % ([Blagrove 2018](https://repository.lboro.ac.uk/articles/journal_contribution/Effects_of_strength_training_on_the_physiological_determinants_of_middle-_and_long-distance_running_performance_a_systematic_review/9619553), [Update 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11052887)). | Übungsbibliothek: Kniebeuge/Kreuzheben, keine einbeinigen Übungen (Willi mag sie nicht) |

## 2. Laufen und Rad

| Regel | Begründung | Im Planer |
|---|---|---|
| Etwa **80 % locker, 20 % hart** (polarisiert) | Beste Datenlage für Ausdauersportler ([Seiler](https://pmc.ncbi.nlm.nih.gov/articles/PMC4621419/)); die Zahlen sind eine Beschreibung von Spitzenathleten, kein Gesetz. | 1× VO2max, 1× Schwelle (Rad), 1× langer Lauf pro Woche, alles andere Zone 2 |
| **Laufen und Rad abwechselnd**, keine Laufserien an Folgetagen | Sehnen und Gelenke passen sich langsamer an als das Herz-Kreislauf-System ([Runner's Connect](https://runnersconnect.net/return-to-running/)); der Wechsel hält den Ausdauerreiz bei weniger Stoßbelastung. | Kombinationssuche, auch über den Wochenwechsel |
| Harte Einheiten nie hintereinander, Beine nicht direkt vor/nach einer harten Einheit | Erholung zwischen harten Reizen | Planer + Tests |
| **Kein starres 10-%-Gesetz.** Wichtiger: ein einzelner Lauf nicht mehr als etwa 10 % länger als der längste Lauf der letzten 30 Tage | Das 10-%-Wochenlimit ist schlecht belegt ([Marathon Handbook](https://marathonhandbook.com/the-10-rule-new-study-suggests-weve-been-doing-it-wrong-this-whole-time/), [Outside](https://www.outsideonline.com/health/running/training-advice/running-101/myth-of-the-10-percent-rule/)); ein Kohortenbericht (BJSM) sah mehr Verletzungen bei Einzelläufen, die deutlich länger waren als der längste der letzten 30 Tage. Nur Beobachtungsdaten. | Einzelläufe bleiben kurz (Backyard: 6 km pro Runde) statt eines einzigen langen Laufs; Wochenumfang nach Krankheit steigt schneller als bei Neulingen, weil Willi vorher 49 km pro Woche lief |

## 3. Wiedereinstieg nach Krankheit

| Regel | Begründung | Im Planer |
|---|---|---|
| Erst wieder trainieren, wenn **fieberfrei und Symptome nur oberhalb des Halses**; bei Fieber, Husten, Atemnot sofort stoppen | Übliche sportmedizinische Empfehlung ([Tabelle in PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7176256/table/Tab4)) | Hinweise im Coach |
| Die ersten Tage **locker**, harte Einheiten **frühestens nach etwa einer Woche** | Coaching-Empfehlungen ([Runner's Connect](https://runnersconnect.net/how-to-return-to-running-after-the-flu-or-a-fever/)) | `returnRamp`, `hardFrom` (bei Willi: harte Einheiten ab 9.11.) |
| Rückkehr zum alten Umfang etwa **in so vielen Tagen, wie man ausgefallen ist**; Herz-Kreislauf kehrt schneller zurück als Sehnen | Mehrere Coaching-Quellen, uneinheitlich (zwei bis sechs Wochen). Keine harte Studienlage. | Umfang steigt von 12 → 20 → 34 km (Willi 49 km vor der Krankheit) |

## 4. Tapering vor einem Wettkampf

| Regel | Begründung | Im Planer |
|---|---|---|
| **Umfang um etwa 40–60 % senken, Intensität und Häufigkeit beibehalten**, ein bis drei Wochen | Meta-Analysen: [Wang 2023](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10171681/), [Bosquet 2007](https://coachsci.sdsu.edu/csa/vol131/bosquet.htm) | Rennwoche: Faktor 0,6, noch ein kurzer Reiz (Schwelle) früh in der Woche, **keine harten Einheiten in den letzten 3 Tagen** |
| Danach ein ruhiger Tag + eine ruhige Woche | Erholung | Regeneration am Tag danach, Erholungswoche |

## 5. Backyard-Lauf (jede volle Stunde 6 km)

| Regel | Begründung | Im Planer |
|---|---|---|
| **Rennspezifisch** üben: mehrere Runden mit Pause | Ein einziger langer Lauf trainiert etwas anderes als wiederholte 6-km-Runden mit Pausen ([inov8-Plan](https://www.inov8.com/blog/post/backyard-ultra-training-plan)) | „Backyard-Simulation“: 3 Runden in der Vorvorwoche, 2 Runden eine Woche davor |
| **Langsamer starten, als es sich gut anfühlt**, keine Zeit „sparen“ | Häufigster Anfängerfehler ([Tailwind](https://tailwindnutrition.com/blogs/tw/what-is-a-backyard-ultra-and-how-do-you-fuel-for-one)) | Renntag-Text |
| In der Pause **sofort essen**, etwa 30–60 g Kohlenhydrate pro Stunde, 300–600 ml trinken nach Durst, Koffein später, nur Bekanntes essen | Verpflegungsempfehlungen der Hersteller und Läuferportale ([Multiday Running](https://multidayrunning.com/nutrition/backyard-ultra-nutrition)); Werte schwanken, **im Training testen** | Renntag-Text, Simulation: „essen/trinken wie am Renntag“ |

## 6. Mini-Einheiten (5–15 Minuten, optional)

Kleine Zusatzreize statt zusätzlicher voller Einheiten. Sie sind begrenzt (maximal ca. 90 Minuten pro Woche), immer optional und in den Einstellungen abschaltbar (`miniSessions`).

| Einheit | Wann | Belegt? |
|---|---|---|
| **Wandsitzen** 2× 45–60 s (+ 2× 15 langsame Wadenheben an den ersten zwei Lauftagen) | direkt nach jedem Lauf, nicht am schweren Beintag | Isometrische Übungen lindern kurzfristig Knieschmerzen (kleine Studien zum Patellarsehnenschmerz, [BJSM 2015](https://bjsm.bmj.com/content/49/19/1277.abstract)); für die Laufökonomie sind isometrische Übungen laut Meta-Analyse eher weniger wirksam; Wadenheben mit langsamem Absenken stärkt die Achillessehne (Übersichtsarbeit, überwiegend Beobachtung/Reha). Dass es die Laufökonomie verbessert, ist nicht belegt. |
| **Sprungübungen** 5 min (Pogo-Sprünge, Skippings) | 2×/Woche nach einem lockeren Lauf, erst wenn harte Einheiten erlaubt sind; nicht in der Rennwoche | Meta-Analyse 2024 ([Sports Medicine](https://pmc.ncbi.nlm.nih.gov/articles/PMC11052887)): Plyometrie verbessert die Laufökonomie vor allem bei **niedrigen Tempi (bis ca. 12 km/h)**, über alle Tempi hinweg nicht signifikant; schweres Krafttraining wirkt eher auch bei höherem Tempo. Passt zu deinen lockeren Läufen. Strides allein: nur Trainerwissen, keine Studie. |
| **Rückwärtsgehen am Berg** 10 min (Laufband, 5 % Steigung, 3–4 km/h) | bis zu 3×/Woche hinter Push/Pull | Belegt vor allem bei Kniearthrose ([Meta-Analyse zu Rückwärtsgehen bei Kniearthrose](https://journals.sagepub.com/doi/abs/10.1177/0269215518801430)); für Läufer/Laufleistung nicht belegt – hier eine knieschonende Zusatzbelastung. |
| **Stairmaster** 15 min locker bis mittel | bis zu 2×/Woche hinter Push/Pull, nicht in der Rennwoche | Gelenkschonendes Ausdauer-Cross-Training; verbessert Laufzeit/VO2 etwas weniger als Laufen selbst (eine ältere Studie, nur Sekundärquelle). |

Nicht belegt, deshalb nicht im Plan: Strides als eigener Baustein, Hüft-Clamshells.

## Grenzen

- Viele Quellen sind Läuferportale oder Hersteller. Die Meta-Analysen sind belastbarer, sagen aber oft nur „Richtung“, keine exakten Zahlen.
- Der Planer kennt keine Tagesform. Garmin-HRV, Schlaf und Ruhepuls fließen nur in die Coach-Einschätzung ein, nicht in die Wochenplanung.
- Bei Beschwerden (Knie, Waden, Fuß) im Coach-Tab eintragen, dann nimmt der Plan Läufe und schwere Einheiten heraus.
