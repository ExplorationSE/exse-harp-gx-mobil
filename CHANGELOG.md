# Änderungsprotokoll – ExSE Harp GX Mobil

## 1.1.0 – 16.10.2026

Veröffentlichung des Rust-Rechenkerns (getestet als 1.1.0-dev, unter Windows mit Python 3.11–3.13).

- **Zählraten T2:** Der Sync-Eingang ist in T2 ein normaler Datenkanal K0 mit eigener Kachel „K0“.
  - Enthält die T2-Datei keine K0-Ereignisse, entfällt K0 ganz: keine Kachel „Sync 0“ mehr
    (z. B. bei `Demo_Synthetisch_T2_Einzelphotonen_cw_Antibunching_4s.ptu`).
  - Info-Zeile „Modus“ in T2 ohne Sync-Rate („T2, 4 Kanäle“ bzw. „T2, 2 Kanäle + K0“).
  - T3 unverändert: Kachel „Sync“ und „Sync … cps“ in der Info-Zeile.
- Version 1.1.0 in Python-Paket, Rust-Kern (Cargo/pyproject), App-Fußzeile und Anleitung (PDF);
  Service-Worker-Cache `exse-harp-gx-mobil-1.1.0-r1`.
- Das Release enthält im Programm-Zip das Windows-Wheel unter `wheels\`; `install_windows.bat` installiert es
  automatisch, sonst rechnet Numba. Die Anleitung (Abschnitt 4) beschreibt das.

Rust-Rechenkern (seit 1.1.0-dev):

- **Rust-Rechenkern `harp_gx_core`** (PyO3 + maturin, rayon, mehrkernig), Quellen unter `rust/harp_gx_core`:
  - g²/g³/g⁴-Histogramme, Fensterzählungen, zusammengefasste Kachelsummen (Zentral- und Seitenpeaks in einem Lauf)
    und die Kanalaufteilung der Zeitmarken.
  - Blockweise über die Start-Marken parallel; jeder Block hat eigene Histogramme, die Fenster überlappen die
    Blockgrenzen. Ganzzahlige Summen, daher bitgleich zu Numba/NumPy und unabhängig von Block- und Thread-Zahl.
  - Ungültige Geometrie oder Feldgrößen lösen `ValueError` aus statt eines Absturzes.
- **Reihenfolge Rust > Numba > NumPy** mit automatischem Rückfall:
  - beim Import, wenn ein Paket fehlt, und zur Laufzeit, wenn ein Rust-Aufruf fehlschlägt;
  - der Grund steht in der Info-Zeile.
  - Umgebungsvariablen: `HARP_GX_ENGINE=rust|numba|numpy` (erzwingen), `HARP_GX_THREADS=n`,
    `HARP_GX_NO_RUST`, `HARP_GX_NO_NUMBA`.
- Info-Zeile „Rechenkern“: aktiver Kern, Threads, Mtags/s, z. B. „Rust (rayon) · 4 Threads · …“.
- Rechenkern-Schicht: Kachelsummen je Start-Kanal in einem Aufruf (vorher eine Fensterzählung je Schlüssel).
  Ergebnisse auf allen 9 Demodateien unverändert (Vergleich alt/neu, Numba/Rust).
- Tests `tests/test_gx_rust.py`:
  - Gleichheit Rust = Numba = NumPy für Kernel, Kachelsummen, Kanalaufteilung und alle Demodateien;
  - Invarianz gegen Chunkgröße und Threadzahl;
  - Engine-Reihenfolge, Erzwingen, Rückfall beim Import und zur Laufzeit.
- `tools/bench_engines.py`: Mtags/s und Frame-Zeit je Datei, Engine und Threadzahl.
- Windows-Verteilung vorbereitet:
  - `.github/workflows/wheels.yml` baut ein abi3-Wheel (cp311-abi3, gilt für Python 3.11–3.13) für Windows,
    Linux und macOS;
  - es testet auf 3.11/3.12/3.13 und hängt die Wheels bei einem Tag `v*` an das Release.
  - `install_windows.bat` installiert ein Wheel aus `wheels\`, falls vorhanden. Sonst rechnet Numba wie bisher,
    ein Compiler ist nicht nötig.
  - `tests.yml` baut den Rust-Kern mit, damit die Gleichheitstests in CI laufen.
- Service-Worker-Cache `exse-harp-gx-mobil-1.1.0-dev-r1`.

## 1.0.1 – 16.10.2026

- g³/g⁴-Karten: Die Farbskala reicht jetzt bis 4 Dekaden unter das Maximum (vorher 3).
  - Ist der Datenbereich kleiner, gilt weiter der Datenbereich (adaptiv: min(4 Dekaden, Datenbereich)).
  - Schwächere Strukturen werden sichtbar, z. B. die g³-Linien (≈ 4·10³ je Bin) neben dem Tripel-Peak (≈ 2·10⁷).
  - Die 1-2-5-Teilung bleibt, ebenso die hervorgehobene 1.
- Vergleich am gleichen Datenstand (3 und 4 Dekaden), Ansichten g³-Karte und g⁴-Schnitt:
  - Laser, thermisch cw und alle g⁴-Schnitte: unverändert, weil ihr Datenbereich kleiner als 3 Dekaden ist.
  - Thermisch gepulst g³: zusätzlich die Dekade 10⁻³ (seltene Nebenstrukturen), sonst gleich.
  - Tripel und Paare: Linien deutlich sichtbarer.
- Skalenbeschriftung kurz gehalten: Werte unter 0,01 als „5e-3“. „0.005“ wurde am rechten Rand abgeschnitten.
- README: g³-Screenshot der Tripel-Datei neu.
- Service-Worker-Cache `exse-harp-gx-mobil-1.0.1-r1`. Daten-Zips unverändert (Inhalt wie 1.0.0).

## 1.0.0 – 16.10.2026

Erste veröffentlichte Version von **ExSE Harp GX Mobil**. Sie fasst die Entwicklungsstände 0.1.0 bis 0.2.7 zusammen;
deren Einzelheiten stehen unten. Weiterhin eine Simulation mit synthetischen PTU-Dateien, noch ohne Schnittstelle zu
einer echten Harp.
- **Korrelationen g²/g³/g⁴ live** aus T2-Zeitmarken (0.2.0):
  - Rechenkern `harp/gx` mit Numba im eigenen Worker-Prozess und NumPy-Rückfall (bitgleich).
  - Gleitendes Koinzidenzfenster; Normierung für cw auf Zufallskoinzidenzen, für gepulste Quellen auf Seitenpeaks.
  - Heralded g²ₕ mit K0 als Herald; kompakte Binär-Frames.
- **Automatik:** Kabel-Laufzeiten werden aus den g²-Kurven kalibriert. Bei cw werden Fenster und Bereich aus der
  g²-Breite oder nach Statistik gewählt (0.2.1). Kacheln mit wenig Daten zeigen „sammelt Daten …“.
- **Oberfläche (0.2.2–0.2.7):**
  - Ansichten Histo | Zeit | g² | g³ | g⁴, alle mit gleicher Diagrammhöhe.
  - Große Kachel g²(0) / g³(0,0) / g⁴(0,0,0) mit n und Fehler, Kachelliste und graue Hinweise, in allen
    Ansichten gleich aufgebaut.
  - Log. 1-2-5-Farbskala der Karten; τ₃-Regler unter der g⁴-Karte; Messwertzeile auch in g⁴.
  - Lesbare g-Exponenten; einzeilige Steuerung bei 360/390 px.
- **Neun synthetische Demodateien** mit analytisch bekannten Sollwerten (0.1.0, 0.2.1, 0.2.7):
  thermisch cw und gepulst, kohärenter Laser, Einzelphotonen cw und gepulst, Heralded (K0), HOM-Dip,
  Photonenpaare (SPDC) und Photonentripel.
  Dazu Generator, Prüfwerkzeug und Validierungstests (`tools/generate_gx.py`, `tools/validate_gx.py`,
  `tests/test_gn_validation.py`).
- **Allgemeine Bezeichnung „Harp“** (z. B. HydraHarp 500, MultiHarp, PicoHarp 330, TimeHarp 260; 0.2.5/0.2.6).
  Hinweistext: „Simulation mit synthetischen PTU-Dateien – diese Version enthält noch keine Schnittstelle zu einer
  echten Harp.“
- Veröffentlichung auf GitHub:
  - MIT-Lizenz, CI (pytest auf Python 3.11 und 3.13), Screenshots im README.
  - Release mit Programm-Zip, Daten-Zips 1–8 (je < 25 MB) und Anleitung als PDF.
  - Die PTU-Daten liegen nicht im Git-Repository.
- Service-Worker-Cache `exse-harp-gx-mobil-1.0.0-r1`.

## 0.2.7 – 15.10.2026

- g⁴-Ansicht: neben der großen Kachel g⁴(0,0,0) steht jetzt die vollständige Messwertzeile wie in g³.
  - Inhalt: „Quadrupel … · Messzeit · Bin …“, gleiche Angaben und dasselbe Format wie „Tripel … · … s · Bin …“.
  - Der τ₃-Regler bleibt an Stelle der Messwertzeile; alle y-Positionen bleiben gleich.
  - Die Zeile darf zweizeilig werden (360 px). Gemeinsame Funktion `gnReadout`.
- Zwei neue synthetische T2-Demodateien (Poisson-Cluster-Prozess, cw, 4 Detektoren, Standardfenster 2 ns):
  - `Demo_Synthetisch_T2_Photonenpaare_SPDC_cw_3s.ptu` (19,6 MB, Daten-Zip 7): sehr gute Zwei-Photonen-Quelle.
    1 MHz Paare, η = 0,8 je Arm, Signal → K1/K3, Idler → K2/K4.
    Ideal: g²(K1,K2) = 501, g²(K1,K3) = 1, g³ = 1001, g⁴ = 502 001.
  - `Demo_Synthetisch_T2_Photonentripel_cw_5s.ptu` (18,6 MB, Daten-Zip 8): gute Drei-Photonen-Quelle.
    600 kHz Tripel, η = 0,5, K1/K2/(K3|K4).
    Ideal: g² = 834, g²(K3,K4) = 1, g³(K1,K2,K3) = 6,97·10⁵, g³(K1,K3,K4) = 1668, g⁴ = 2,78·10⁶.
  - Sollwerte analytisch in `tools/generate_gx.py` (`cluster_g`, `multi_expected`), einschließlich des
    Jitter-Randverlusts. Prüfung in `tools/validate_gx.py`, `tests/test_gn_validation.py` und `tools/gx_live_bench.py`.
- Behoben: Das Binär-Frame kodierte g nur bis 10⁴, größere Werte wurden in den g³/g⁴-Karten abgeschnitten.
  Die Karte war dann einfarbig, die Farbskala hatte nur eine Beschriftung.
  Jetzt 10⁻⁴ bis 10⁸ (`log_span` 12, relative Auflösung < 0,05 %). Die App liest den Bereich aus dem Frame-Kopf.
- Kacheln: g ≥ 10⁶ wird als „2.78e6“ angezeigt, damit die Werte in die Kacheln passen.
- Service-Worker-Cache `exse-harp-gx-mobil-0.2.7-r1`. Die Daten-Zips 1–6 von 0.2.1 gelten weiter, neu sind daten-7 und daten-8.

## 0.2.6 – 15.10.2026

- Steuerung: Beschriftungen „Referenzkanal (g²)“, „Binbreite g²“ und „Bereich g³/g⁴ (±)“ bleiben einzeilig (360/390 px).
  - Ursache: `label` ist ein Flex-Container mit `flex-direction:column`. Seit 0.2.2 stehen die g-Symbole als
    `<span class="gx">` im Label; damit wurden Text, Symbol und Klammer/Schrägstrich je ein eigenes
    Flex-Element und untereinander gestapelt (bis zu fünf Zeilen bei „Bereich g³/g⁴ (±)“).
    Die Breite der Auswahlfelder war nicht die Ursache.
  - Lösung: Beschriftungen haben eine eigene Hülle `<span class="lt">` (einzeilig, `nowrap`, sonst „…“).
    Die Rasterspalten sind `minmax(0,1fr)`, damit lange Optionstexte das Raster nicht verbreitern.
- Startleiste: „⏮ Von vorn“ brach bei 360 px in zwei Zeilen um. Die Knöpfe sind jetzt einzeilig, unter 370 px mit 12,5 px Schrift.
- Hinweistext grammatisch korrigiert („die Harp“): „… keine Schnittstelle zu einer echten Harp.“ in App,
  README, Anleitung und PDF, LIESMICH und Tests. Auch „eine echte Harp“, „einer simulierten Harp“, „der Harp“
  in Manifest, README, Anleitung, `config.toml`, Paketbeschreibung und `hh500`-Platzhalter.
- g⁴-Ansicht (Ausnahme): Die Quadrupel-Zahl „Quadrupel n …“ steht im freien Platz neben der großen Kachel
  g⁴(0,0,0). Die Messwertzeile wird dort ja vom τ₃-Regler ersetzt.
- Ansichtsumschalter wieder in der Reihenfolge Histo | Zeit | g² | g³ | g⁴. Weiterschalten folgt dieser Reihenfolge.
- README: Installationspfad `C:\ExSE\exse-harp-gx-mobil` statt des alten `C:\HarpGXMobil\v1`.
- Service-Worker-Cache `exse-harp-gx-mobil-0.2.6-r1`. Die Daten-Zips von 0.2.1 gelten weiter.

## 0.2.5 – 15.10.2026

- g⁴-Karte wieder genau so groß wie die g³-Karte: 276 px bei 360 px Breite, 306 px bei 390 px.
  - Der τ₃-Regler sitzt jetzt außerhalb der Diagrammhöhe, an Stelle der Messwertzeile und gleich hoch (18 px).
  - Messwertzeile, Leiste und Steuerung liegen damit weiter in allen Ansichten auf derselben Höhe.
  - Im g⁴-Schnitt erscheint ein angetippter Messwert stattdessen in der grauen Hinweiszeile.
  - Die Kennzahl „Quadrupel … · Bin …“ entfällt dort; die Anzahl steht weiter in der großen Kachel.
- Zeitverlauf mit derselben Zeichenfläche wie Histo: gleiche Ränder links und rechts, gleiche x-Achsenhöhe.
  Die Einheit steht jetzt in der x-Beschriftung („t / s · Zählrate / kcps“).
- Allgemeine Bezeichnung „Harp“ statt „HydraHarp“ in Oberfläche, App-Info, Manifest, README, Anleitung und LIESMICH.
  - Neuer Hinweistext: „Simulation mit synthetischen PTU-Dateien – diese Version enthält noch keine Schnittstelle
    zu einem echten Harp.“
  - Technische Namen bleiben und werden als Beispiel beschrieben: Quelle `hh500`, `HH500LiveSource`.
  - snAPI unterstützt laut öffentlicher Doku HydraHarp 500/400, MultiHarp 150/160, PicoHarp 330 und
    TimeHarp 260, nicht PicoHarp 300.
  - Markenhinweis im README um MultiHarp, PicoHarp und TimeHarp ergänzt.
- Anleitung aktualisiert: Paketname, Ordner `C:\ExSE\exse-harp-gx-mobil`, Demodateien in `data\`.
  Das PDF `docs/Anleitung_Windows_Online.pdf` wird neu aus der Anleitung erzeugt (`tools/make_anleitung_pdf.py`);
  vorher lag dort noch die alte PDF von Harp Mobil V1.
- `tools/layout_check_gx.py` misst jetzt auch Kartengröße und Zeichenflächen. Service-Worker-Cache r9.

## 0.2.4 – 15.10.2026

- Alle Ansichten haben jetzt dieselbe Diagrammhöhe: Histo, g², g³, g⁴ und Zeit.
  - Maßgeblich ist die Höhe der quadratischen g³/g⁴-Karte: Breite − 2·Rand plus Achsen, höchstens die bisherige Höhe.
  - Beim g⁴-Schnitt zählt der τ₃-Regler zur Diagrammhöhe; die Karte wird dafür etwas kleiner.
  - Damit beginnen Messwertzeile, Leiste und Steuerung in allen Ansichten auf derselben Höhe.
  - Gemessen bei 360 px: Leiste bei y = 461, Diagramm 324 px. Bei 390 px: y = 491, Diagramm 354 px.
  - Auf breiten oder quer liegenden Bildschirmen begrenzt weiter die Fensterhöhe; dort ändert sich nichts.
- Kachelliste mit fester Zeilenhöhe von 24 px, damit die Leiste in g², g³ und g⁴ gleich hoch ist (208 px).
- Neues Prüfwerkzeug `tools/layout_check_gx.py` und neuer Test für die gemeinsame Diagrammhöhe. Service-Worker-Cache r8.

## 0.2.3 – 15.10.2026

- g²-Ansicht: große Kachel g²(0) wie g³(0,0)/g⁴(0,0,0), für das gewählte Kanalpaar (Auswahl wird gespeichert).
  Mit n, Fehler, Zustand „sammelt Daten …“, cw- bzw. Seitenpeak-Normierung und g²ₕ bei K0 als Herald.
  Die Werte kommen aus dem GX-Rechenkern. Ohne GX-Daten (z. B. snAPI-Quelle) bleibt die Leiste ausgeblendet.
- Leiste unter g², g³ und g⁴ einheitlich aufgebaut:
  - Reihenfolge: Kanalauswahl (feste Breite) und Darstellung, dann große Kachel (feste Größe 124 × 80 px)
    mit Kachelliste, dann graue Hinweiszeile.
  - Die Hinweiszeile enthält Fenster, Normierung, Messzeit, automatisches Fenster/Bereich und Kalibrierung.
  - Gleiche Abstände; der τ₃-Regler sitzt jetzt im g⁴-Diagrammbereich.
- Test für den Aufbau der Leiste. Service-Worker-Cache r7.

## 0.2.2 – 15.10.2026

- Farbskala neben den g³/g⁴-Karten: logarithmische 1-2-5-Teilung (0,1 · 0,2 · 0,5 · 1 · 2 · 5 · 10 · 20 …) über
  den sichtbaren Bereich, immer mehrere Beschriftungen. 1 ist als Bezug hervorgehoben (hell, fett, längerer Strich).
  Bei engem Bereich wird feiner unterteilt, bei sehr großem ausgedünnt.
- g mit Exponent überall einheitlich gesetzt (Ansichtsumschalter, Steuerung, Kacheln, Hinweise, Info):
  g etwas größer, Exponent ≈ 70 % der g-Größe und angehoben, g²ₕ entsprechend.
- Informative Hinweise sind jetzt grau statt gelb: automatisches Fenster/Bereich, Kalibrierhinweise,
  „Sammelt Daten …“. Gelb bleibt echten Problemen vorbehalten (z. B. Verbindungsverlust, Zuschauer-Modus).
- Test `tests/test_web_ticks.py` (Teilung der Farbskala, mit Node). Service-Worker-Cache r6.

## 0.2.1 – 14.10.2026

- Thermisch cw live (g³/g⁴ = 0, keine Kalibrierung): kein Rechenfehler, sondern Statistik bzw. Einstellung.
  Mit den cw-Standardwerten (±25 ns, Fenster 2 ns) fallen bei 100 kHz/Kanal nur ≈ 0,02 Tripel/s und ≈ 10⁻⁵
  Quadrupel/s an. τc = 50 µs ist breiter als der Kalibrierbereich (±20 ns), daher hat g² dort kein Merkmal.
  Mit Fenster 0,5 µs und Bereich ±2 µs ergibt dieselbe Datei 1,99 / 6 / 23,5.
- Kacheln mit weniger als 10 Koinzidenzen zeigen „sammelt Daten …“ mit der Anzahl n statt g = 0.
  Leere Karten zeigen den Hinweis „Sammelt Daten …“.
- Kalibrierung ohne Merkmal (z. B. kohärenter Laser) rechnet ohne Offsets weiter und zeigt einen Hinweis.
  Eine unvollständige Kalibrierung nennt die Kanäle ohne Offset. Neue Felder `cal_status` und `cal_missing`.
- Tests: Laser-Rückfall ohne Offsets, Markierung bei zu wenig Koinzidenzen.
- Automatische Wahl von Fenster und Bereich bei cw, einmalig nach 0,5 s. Grundlage ist eine grobe g²-Kurve
  (±5 µs, 10 ns). Bei breitem Merkmal gilt Fenster = FWHM/6 und Bereich = ±3·FWHM. Ohne Merkmal wird das
  Fenster nach Statistik gewählt (≈ 100 Quadrupel/s). Schmale Merkmale behalten die Standardwerte.
  Sobald Sie Fenster oder Bereich selbst setzen, ist die Automatik aus. Die App zeigt einen Hinweis.
- Kalibrierstatus „unnötig“: Die g²-Korrelation ist viel breiter als der Kabelversatz.
- Kalibrierung ohne geänderte Laufzeiten setzt die Summen nicht mehr zurück.
- Worker-Ergebnisse tragen eine Epoche. Veraltete Ergebnisse, z. B. der vorigen Datei, werden verworfen.
  Behoben: Nach dem Dateiwechsel zeigte die App das Fenster der vorigen Datei.
- Neue Demodaten: `Demo_Synthetisch_T2_Thermisch_cw_g2g3g4_3s.ptu` (τc 400 ns, 450 kHz/Kanal, 22 MB) und
  `Demo_Synthetisch_T2_Laser_kohaerent_Referenz_3s.ptu` (450 kHz/Kanal, 22 MB). Sie ersetzen die 8-s-Dateien.
  Sollwerte für thermisch cw kommen aus dem Fenstermittel der Permanente, siehe `thermal_cw_expected`.
- Beim Dateidurchlauf werden die Werte weiterhin zurückgesetzt (wie gewünscht).
- `tools/gx_live_bench.py` misst die Zeit, bis g³/g⁴ stabil sind. `tools/screenshot_gx.py` hat
  Parameter für Datei, Präfix, Tempo und Mindestmesszeit. Service-Worker-Cache r5.

## 0.2.0 – 14.10.2026

- Live-Rechenkern `harp/gx` (Numba, parallel; NumPy-Rückfall mit identischen Ergebnissen, erzwingbar mit
  `HARP_GX_NO_NUMBA=1`): gleitendes Fenster, blockweise Überlappung, alle Kanalpaare/-tripel/-quadrupel,
  cw-Zufallsnormierung und gepulste Seitenpeak-Normierung, Kabellaufzeiten mit Auto-Kalibrierung (nach 2 s).
- Rechnung in eigenem Worker-Prozess; komprimierte Binär-Frames (`GXF1`, zlib, log-quantisiert) mit ca. 2 Hz.
- Neue Ansichten: Histo | g² | g³ | g⁴ | Zeit. g³: Log-Heatmap (τ1,τ2) mit Schnitten Diagonale, τ1=0, τ2=0.
  g⁴: τ3-Schieberegler (2D-Schnitt), Diagonalkurve, große Kachel g⁴(0,0,0). Kanalkombinations-Auswahl.
- Neue Einstellungen `gn_range_ps`, `gn_win_ps`, `combo3`, `combo4`; Befehl „Neu kalibrieren“.
- Tests `tests/test_gx_engine.py` (Kerne, Blockinvarianz, Abgleich mit `harp/gn.py`, Normierung, Kalibrierung,
  Binärformat, Worker, Server). Service-Worker-Cache r2.

## 0.1.0 – 14.10.2026

Neues Projekt **ExSE Harp GX Mobil**, abgeleitet von ExSE Harp Mobil 1.0.6 (Commit `ffec0b3`, frische Git-Historie).
Mobil bleibt unverändert.
- Umbenennung in „ExSE Harp GX Mobil“, Version 0.1.0 (Hinweis in der App unverändert).
- Sieben synthetische T2-Demodateien mit analytisch bekannten g⁽²⁾/g⁽³⁾/g⁽⁴⁾: thermisch cw und gepulst
  (2/6/24), kohärenter Laser (1/1/1), Einzelphotonen cw (Antibunching) und gepulst (g²(0)=0,05), Heralded mit
  K0 als Herald (g²_h≈0,008), Hong-Ou-Mandel-Dip mit Verzögerungs-Scan (V=0,9). Generator `tools/generate_gx.py`.
- Referenz-Auswertung `harp/gn.py` (g²/g³/g⁴, cw- und Seitenpeak-Normierung) und Prüfwerkzeug `tools/validate_gx.py`.
- Validierungstests `tests/test_gn_validation.py` (gemessene g(n) gegen Sollwerte).
- Standard-Datei: `Demo_Synthetisch_T2_Thermisch_cw_g2g3g4_8s.ptu`.

### Vorgeschichte (ExSE Harp Mobil)

#### Mobil 1.0.6 – 13.10.2026

Stabiler Betrieb mit mehreren Handys gleichzeitig.
- Server: Jede Verbindung hat eine eigene Sende-Warteschlange (Frame und Status nur jeweils der neueste,
  Quittungen in Reihenfolge). Ein hängendes Handy (Bildschirm aus, Hintergrund, Funkloch) blockiert weder
  andere Handys noch die Befehlsverarbeitung.
- Server: Hängt das Senden an ein Handy länger als 5 s, wird dessen Verbindung aktiv geschlossen (vorher blieb
  sie als „Zombie“ offen: eingefrorene Anzeige ohne Wiederverbindung); eine gehaltene Steuerung wird freigegeben.
- App: Verbindungsprüfung per Ping alle 5 s; kommt 10 s lang keine Antwort, wird neu verbunden. Beim
  Zurückkehren in den Vordergrund wird die Verbindung sofort geprüft. Hinweis „Verbindung wird wiederhergestellt …“.
- App: Zuschauer-Modus deutlich gekennzeichnet („Nur Anzeige“); Hinweis nach Wiederverbindung, wenn die
  Steuerung bei der Unterbrechung verloren ging.
- Tests mit zwei gleichzeitigen Clients, einer davon hängend.

#### Mobil 1.0.5 – 13.10.2026

- `install_windows.bat`: Python-Suche robuster (py -3.13, -3.12, -3.11, -3, py, python; jeder Kandidat wird
  ausgeführt und geprüft, mind. 3.10, 64 Bit). Behebt Fehlstart mit dem neuen Python-Installationsmanager
  („No runtime installed that matches 3.13“). Klare Meldung mit Hinweis `py install 3.13`; Abbruch vor
  venv/pip, wenn kein Python gefunden wird oder die venv nicht angelegt werden kann.

#### Mobil 1.0.4 – 13.10.2026

Textänderung, keine Funktionsänderung.
- Infobereich-Hinweis in der App gekürzt: „Simulation mit synthetischen PTU-Dateien – diese Version enthält noch keine
  Schnittstelle zu einer echten HydraHarp.“ (Herkunftshinweis bleibt im README).
- Service-Worker-Cache neu (`exse-harp-mobil-1.0.4-r15`).

#### Mobil 1.0.3 – 13.10.2026

Umbenennung, keine Funktionsänderung.
- Neuer Name **ExSE Harp Mobil** (vorher „ExSE Harp Mobil“): Seitentitel, App-Name (Kurzname „Harp Mobil“),
  Infobereich, Anmeldeseite, `/api/health`, Skripte, README, Anleitung und PDF.
- GitHub-Repository umbenannt in `ExplorationSE/exse-harp-mobil` (alte Adresse leitet weiter);
  Download-Dateien heißen jetzt `exse-harp-mobil-…zip`.
- Service-Worker-Cache neu (`exse-harp-mobil-1.0.3-…`); ggf. die alte installierte App vom Startbildschirm entfernen
  und neu hinzufügen, damit der neue Name erscheint.

#### Mobil 1.0.2 – 13.10.2026

Hinweise zu Status und Herkunft, keine Funktionsänderung.
- README: Hinweiskasten oben – noch keine Anbindung an eine echte HydraHarp (nur Simulation aus PTU-Dateien,
  snAPI-Quelle unter Windows ungetestet, Gerätequelle Platzhalter); erstellt ausschließlich aus öffentlich
  verfügbaren Informationen, keine PicoQuant-Dateien enthalten; kein Produkt der PicoQuant GmbH, Marken,
  keine Gewährleistung, nicht für sicherheitskritische Anwendungen.
- App: kurzer Hinweis und Kennzeichen „Simulation“ im Infobereich; Manifest-Beschreibung angepasst.
- Repository-Beschreibung: „Simulation, noch ohne Geräteanbindung“.
- Demodateien umbenannt, damit sie klar als synthetisch erkennbar sind (Inhalt unverändert):
  `Demo_Synthetisch_T3_Fluoreszenz_4Kanal_5min.ptu`, `Demo_Synthetisch_T2_Einzelphotonen_HBT_90s.ptu`,
  `Demo_Synthetisch_T2_Heralded_K0_HBT_60s.ptu`; Standarddatei in `config.toml` angepasst.
  Die alten Dateien `data\Demo_T3_…`, `data\Demo_T2_…` können gelöscht werden.

#### Mobil 1.0.1 – 13.10.2026

Nur Dokumentation und Projektpflege, keine Funktionsänderung.
- MIT-Lizenz (`LICENSE`); Hinweis auf uPlot (MIT) bleibt in `web/vendor/LICENSE-uPlot.txt`.
- GitHub Actions: pytest bei jedem Push (Python 3.11 und 3.13), Test-Badge im README.
- README: neuer Kopf mit Zweck, Download-Link zur aktuellen Version, Abschnitt „Funktionen“,
  Screenshots, Kapitel „Lizenz“; Kapitelreihenfolge 4/4a korrigiert; „V1“ → „1.0“.
- Version 1.0.1, Service-Worker-Cache erneuert.

#### Mobil 1.0.0 – 13.10.2026

Erste Version. Live-Anzeige von Messdaten einer PicoQuant HydraHarp 500 im Browser/Handy,
in dieser Version als Simulation durch Wiedergabe von PTU-Dateien.

### Server
- FastAPI + WebSocket, Frames mit Histogramm, Korrelation und Zählraten (wenige kB pro Bild).
- PTU-Leser für T2 und T3 (u. a. Generic T2/T3, HydraHarp V1/V2), Gegenprobe mit `ptufile`.
- Wiedergabe in Echtzeit oder schneller/langsamer, Akkumulieren oder gleitendes Fenster, Datei wiederholen.
- Steuerung durch genau einen Client (Übernahme/Freigabe), Zuschauer sehen live mit.
- Zugangscode mit Cookie, Origin-Prüfung, Befehlsprotokoll.
- Einzige Versionsquelle `harp/__init__.py`, abrufbar über `/api/health`.

### Messansichten
- **Histogramm** (log): T3 Mikrozeit nach Sync; T2 Zeit seit dem letzten Ereignis auf dem Referenzkanal.
- **Korrelation (g²)** (log): τ = t(Kn) − t(Kref) für T2 und T3 (T3 mit absoluter Zeit), alle Paare im
  symmetrischen Fenster, auch über Frame-Grenzen hinweg; Referenzkanal und Binbreite wählbar.
- **Zeitverlauf**: Zählraten (kcps) über der Dateizeit.
- T2: Sync-Eingang als eigener Datenkanal **K0** (wenn die Datei Sync-Ereignisse enthält).
- Startwerte für Binbreite/Fenster je nach Datei (Sync-Periode bzw. Herald-Koinzidenzen im ns-Bereich).

### Oberfläche (PWA)
- Handy-optimiert: einzeilige Kopfzeile mit Ansichtsumschalter „Histo | g² | Zeit“ und Kanaltasten K0–K4.
- Diagramme symmetrisch in der Karte zentriert; Zählratenkacheln in einer Zeile.
- Fortschrittsbalken direkt unter den Start-Tasten; Versionsanzeige im Infobereich.
- Jede PTU-Datei erscheint genau einmal in der Auswahl (Windows: keine Doppelten mehr).

### Windows-Betrieb
- `install_windows.bat`, `start_server.bat` (lokales Netz), `start_online.bat`/`stop_online.bat`
  (Internetzugriff über Cloudflare Quick Tunnel, mit QR-Code und Zugangscode), Anleitung als PDF.

### Demodaten
- `Demo_T3_Fluoreszenz_4Kanal_5min.ptu`: 4 Kanäle, Fluoreszenzabklingen, 5 min.
- `Demo_T2_Einzelphotonen_HBT_90s.ptu`: Einzelphotonenquelle, HBT, Antibunching.
- `Demo_T2_Heralded_K0_HBT_60s.ptu`: Herald-Einzelphotonen, K0 = Herald, Koinzidenzen bei +12/+15 ns.
