# Änderungsprotokoll – ExSE Harp GX Mobil

## 0.2.1-dev – 14.10.2026

- Thermisch cw live (g³/g⁴ = 0, keine Kalibrierung): kein Rechenfehler, sondern Statistik bzw. Einstellung.
  Mit den cw-Standardwerten (±25 ns, Fenster 2 ns) fallen bei 100 kHz/Kanal nur ≈ 0,02 Tripel/s und ≈ 10⁻⁵
  Quadrupel/s an. τc = 50 µs ist breiter als der Kalibrierbereich (±20 ns), daher hat g² dort kein Merkmal.
  Mit Fenster 0,5 µs und Bereich ±2 µs ergibt dieselbe Datei 1,99 / 6 / 23,5.
- Kacheln mit weniger als 10 Koinzidenzen zeigen „sammelt Daten …“ mit der Anzahl n statt g = 0.
  Leere Karten zeigen den Hinweis „Sammelt Daten …“.
- Kalibrierung ohne Merkmal (z. B. kohärenter Laser) rechnet ohne Offsets weiter und zeigt einen Hinweis.
  Eine unvollständige Kalibrierung nennt die Kanäle ohne Offset. Neue Felder `cal_status` und `cal_missing`.
- Tests: Laser-Rückfall ohne Offsets, Markierung bei zu wenig Koinzidenzen. Service-Worker-Cache r3.

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
