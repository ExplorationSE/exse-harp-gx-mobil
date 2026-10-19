# ExplorationSE Harp GX Mobil

[![Tests](https://github.com/ExplorationSE/harp-gx-mobil/actions/workflows/tests.yml/badge.svg)](https://github.com/ExplorationSE/harp-gx-mobil/actions/workflows/tests.yml)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-blue.svg)](LICENSE)

Live-Histogramme, Korrelationen g²/g³/g⁴ und Zählraten für eine PicoQuant **Harp** (z. B. HydraHarp 500, MultiHarp,
PicoHarp 330, TimeHarp 260) auf dem Smartphone – mit
Steuerung im Browser (PWA); derzeit **Simulation aus PTU-Dateien, noch ohne Geräteanbindung**.

> [!IMPORTANT]
> **Hinweis – bitte zuerst lesen**
> - **Noch keine Anbindung an eine echte Harp.** Diese Version spielt ausschließlich **PTU-Dateien als
>   Simulation** ab. Die snAPI-Quelle (PTU-Wiedergabe über snAPI) ist unter Windows **ungetestet**, die
>   Live-Quelle für eine echte Harp ist nur ein **Platzhalter** (Codename `hh500` nach dem Beispielgerät
>   HydraHarp 500; snAPI unterstützt laut Doku HydraHarp 500/400, MultiHarp 150/160, PicoHarp 330, TimeHarp 260).
> - **Erstellt ausschließlich aus öffentlich verfügbaren Informationen:** öffentliche Handbücher und Downloads
>   von PicoQuant, das öffentliche GitHub-Repository [PicoQuant/snAPI](https://github.com/PicoQuant/snAPI) und die
>   [PTU-Format-Demos](https://github.com/PicoQuant/PicoQuant-Time-Tagged-File-Format-Demos). Dieses Repository
>   enthält **keine Dateien von PicoQuant** (keine DLLs, Header, Demo-Code oder snAPI-Wheels); die Demodaten sind
>   synthetisch erzeugt.
> - **Kein Produkt der PicoQuant GmbH**, nicht mit ihr verbunden und nicht von ihr unterstützt oder geprüft.
>   PicoQuant, HydraHarp, MultiHarp, PicoHarp, TimeHarp, snAPI und SymPhoTime sind Marken ihrer jeweiligen Inhaber.
> - **Ohne Gewährleistung** (MIT-Lizenz); nicht für sicherheitskritische Anwendungen bestimmt.

**Download:** [aktuelle Version (Programm, Demodaten, Anleitung als PDF)](https://github.com/ExplorationSE/harp-gx-mobil/releases/latest)
· Änderungen: [`CHANGELOG.md`](CHANGELOG.md) · Lizenz: [MIT](#13-lizenz)

<p>
  <img src="docs/screenshot-gx-g2-paare.png" alt="g²-Ansicht: Photonenpaare, scharfer Peak g²(0) ≈ 500 mit Kachel und Kanalpaaren" width="190">
  <img src="docs/screenshot-gx-g3-tripel.png" alt="g³-Karte: Photonentripel, starker Peak g³(0,0) ≈ 7·10⁵" width="190">
  <img src="docs/screenshot-gx-g4-thermisch.png" alt="g⁴-Schnitt bei τ₃ = 0: thermisch gepulst, g⁴(0,0,0) ≈ 24, τ₃-Regler und Messwertzeile" width="190">
  <img src="docs/screenshot-gx-histo.png" alt="Histogramm-Ansicht mit Kanaltasten K1–K4" width="190">
</p>

## ExplorationSE Harp GX Mobil – Ziel und Stand

**ExplorationSE Harp GX Mobil** ist der Leistungszweig von [ExplorationSE Harp Mobil](https://github.com/ExplorationSE/harp-mobil)
(Ausgangsbasis: Mobil 1.0.6, Commit `ffec0b3`; Mobil selbst bleibt unverändert). Ziel: Korrelationen höherer Ordnung
**g⁽²⁾, g⁽³⁾, g⁽⁴⁾** aus T2-Zeitmarken in Echtzeit, mit schnellem Rechenkern und Anzeige auf dem Handy.

**Version 1.3.1 (dieser Stand):** Umbenennung von „ExSE Harp GX Mobil“ in **ExplorationSE Harp GX Mobil**, neue
Repository-Adresse <https://github.com/ExplorationSE/harp-gx-mobil> (die alte Adresse leitet weiter); Funktionen wie 1.3.0:
- Fünf Ansichten **Histo | Zeit | g² | g³ | g⁴** mit großer Kachel g²(0) / g³(0,0) / g⁴(0,0,0), Kachelliste aller
  Kanal-Kombinationen, Heralded g²ₕ (K0 als Herald) und grauen Hinweisen. Die g³/g⁴-Karten haben eine log. Farbskala.
- Rechenkern `harp_gx_core` in Rust (CPU, rayon) mit GPU-Pfad (wgpu); Rückfall auf Numba bzw. NumPy, alle bitgleich.
- Server-Schleife (Dekodieren, Histogramm, g²-Korrelation, Zählraten) im Rust-Kern: auf dem Laptop von Herrn Eilers
  88 → 12,8 ms je Frame.
- g³/g⁴ per Push nach jedem Frame: Latenz ≈ 35 ms + Netz statt ≈ 300 ms, ≈ 6 Aktualisierungen pro Sekunde,
  Bandbreite je Gerät begrenzt (`HARP_GX_KBPS`).
- Automatische Kalibrierung der Kabel-Laufzeiten aus den g²-Kurven; bei cw automatische Wahl von Fenster und Bereich.
- Neun synthetische T2-Demodateien mit **analytisch bekannten** g⁽²⁾/g⁽³⁾/g⁽⁴⁾ (s. Tabelle), als Daten-Zips im Release.
- Referenz-Implementierung `harp/gn.py` (NumPy, exakt): Koinzidenzzählung mit Fenster, Normierung für
  Dauerstrich (Zufallskoinzidenzen) und gepulst (Seitenpeaks). Validierung: `tests/test_gn_validation.py`,
  `tools/validate_gx.py`.

| Datei (`data/`) | Szenario | Sollwerte | gemessen (Demodatei) |
|---|---|---|---|
| `Demo_Synthetisch_T2_Thermisch_cw_g2g3g4_3s.ptu` (22,0 MB) | pseudo-thermisch cw, τc = 400 ns, 450 kHz je Kanal K1–K4, Fenster 50 ns (automatisch) | ideal 2/6/24; über 50 ns gemittelt 1,94 / 5,61 / 21,6 | 1,94 / 5,73 / 22,6 |
| `Demo_Synthetisch_T2_Thermisch_gepulst_1MHz_4s.ptu` (16,5 MB) | thermisch gepulst 1 MHz, eine Mode/Puls, Seitenpeak-Normierung | g²=2, g³=6, g⁴=24 | 2,00 / 6,00 / 24,0 |
| `Demo_Synthetisch_T2_Laser_kohaerent_Referenz_3s.ptu` (22,0 MB) | kohärent (Poisson), 450 kHz je Kanal, Fenster 140 ns | g²=g³=g⁴=1 | 1,00 / 1,00 / 0,91 |
| `Demo_Synthetisch_T2_Einzelphotonen_cw_Antibunching_4s.ptu` (16,5 MB) | Einzelemitter cw, g²(τ)=1−e^(−\|τ\|/4 ns) | g²(0)=0 ideal; Mittel über ±2 ns: 0,213; g³=g⁴=0 | 0,224 / 0 / 0 |
| `Demo_Synthetisch_T2_Einzelphotonen_gepulst_40MHz_4s.ptu` (13,5 MB) | Einzelphotonenquelle gepulst 40 MHz | g²(0)=0,05, g³=g⁴=0 | 0,046 / 0 / 0 |
| `Demo_Synthetisch_T2_Heralded_K0_g2h_8s.ptu` (12,2 MB) | SPDC-Paare 1 MHz, **K0 = Herald**, K1/K2 (+12/+15 ns) | heralded g²(0)=2·R·w=0,008 (w=4 ns); ohne Herald 1 | 0,0075 / 1,00 |
| `Demo_Synthetisch_T2_HOM_Dip_Scan_20s.ptu` (14,4 MB) | Hong-Ou-Mandel, Verzögerung −1…+1 ps über die Messzeit, V=0,9 | Koinzidenzen K1–K2 (+8 ns) fallen auf 10 % (Mittel je 1/20 Scan: 0,133) | 0,129 |
| `Demo_Synthetisch_T2_Photonenpaare_SPDC_cw_3s.ptu` (19,6 MB) | sehr gute Zwei-Photonen-Quelle: SPDC-Paare cw 1 MHz, η = 0,8 je Arm, Signal → K1/K3, Idler → K2/K4, Fenster 2 ns (x = R·w = 0,002) | g²(K1,K2) = 1+1/x = 501, g²(K1,K3) = g²(K2,K4) = 1; g³(K1,K2,K3) = 1+2/x = 1001, g⁴ = 1+4/x+2/x² = 502 001 (ideal); mit 40 ps Jitter-Randverlust 990 / 4,91·10⁵ | 502 / 1,02 / 1004 / 5,21·10⁵ |
| `Demo_Synthetisch_T2_Photonentripel_cw_5s.ptu` (18,6 MB) | gute Drei-Photonen-Quelle: Tripel cw 600 kHz, η = 0,5, a → K1, b → K2, c → K3/K4, Fenster 2 ns (x = 0,0012) | g² = 1+1/x = 834 (g²(K3,K4) = 1); g³(K1,K2,K3) = 1+3/x+1/x² = 6,97·10⁵, g³(K1,K3,K4) = 1+2/x = 1668; g⁴ = 1+5/x+4/x² = 2,78·10⁶ (mit Jitter 2,75·10⁶) | 833 / 1,01 / 6,97·10⁵ / 1637 / 2,70·10⁶ |

Kabel-Laufzeiten: K2/K3/K4 sind in den 4-Detektor-Dateien um 1,5/3,0/4,5 ns verzögert (wie bei echten Kabeln);
die Auswertung korrigiert sie. Alle Dateien: Generic T2, 1 ps, mit Detektor-Jitter (25–40 ps) und Dunkelzählungen.

**Paar- und Tripel-Quelle (ab 0.2.7):** Poisson-Strom von Clustern (Paare bzw. Tripel, Photonen eines Clusters
gleichzeitig). Dann gilt unabhängig von den Effizienzen g⁽ⁿ⁾(0) = Σ x^(b−n), summiert über alle Zerlegungen der n Kanäle
in b Blöcke, die je aus einem Cluster stammen können; x = R·w (Clusterrate × Fenster). Blöcke ohne das Start-Photon
verlieren am Fensterrand den Anteil E[Jitter-Spannweite]/w (≈ 2,3 % bei 40 ps, w = 2 ns). Die Sollwerte stehen in
`tools/generate_gx.py` (`multi_expected`). Das Standardfenster 2 ns bleibt, weil der Peak schmal ist.
Die Werte werden live in ≈ 1 s Messzeit nach der Kalibrierung (2 s) stabil.

```bat
python tools\generate_gx.py --all        REM alle neun Demodateien nach data\
python tools\validate_gx.py              REM g(n) berechnen und mit den Sollwerten vergleichen
```

**Normierung:** cw: g⁽ⁿ⁾ = N_Tupel / (N_a · Π_j N_j·w/T). Gepulst: g⁽ⁿ⁾(0) = N(0,…,0) / ⟨N(k₁P, k₂P, …)⟩ mit
paarweise verschiedenen Pulsabständen k_j ≠ 0 (Seitenpeaks). Heralded: g²_h = N_h · N_h12 / (N_h1 · N_h2).

## Live g²/g³/g⁴ – Rechenkerne, Latenz, Bandbreite

### Rechenkerne

Die g³/g⁴-Histogramme rechnet ein eigener GX-Prozess (`harp/gx`), damit die Server-Schleife nie wartet. Reihenfolge
**Rust > Numba > NumPy** mit automatischem Rückfall; der aktive Kern steht in der Infozeile „Rechenkern“.
Alle Kerne liefern bitgleiche Ergebnisse (Tests gegen `harp/gn.py`, alle 9 Demodateien).

- **Rust-Kern `harp_gx_core`** (PyO3/rayon, `rust/harp_gx_core`, seit 1.1). Unter Windows liegt das fertige Wheel
  `harp_gx_core-1.3.1-cp311-abi3-win_amd64.whl` im Programm-Zip unter `wheels\`; `install_windows.bat` installiert es.
  Ein Compiler ist nicht nötig. Ohne Wheel rechnet Numba.
- **Server-Pfad im Rust-Kern** (seit 1.3, `src/stream.rs`): PTU-Dekodierung, T2-Start-Stopp-Histogramm,
  g²-Kreuzkorrelation und Zählraten je Frame in einem Durchlauf, bit-identisch zu den NumPy-Fassungen (Rückfall
  ohne Kern oder mit `HARP_STREAM_NUMPY=1`). „Server … ms“ in der Infozeile ist die Zeit dieser Schleife je Frame,
  nicht die der g³/g⁴-Kerne. Box, `Thermisch_cw` bei 1×: 35,5 → 5,6 ms; Laptop von Herrn Eilers: 88 → 12,8 ms.
  Aufschlüsselung: `python tools/profile_frame.py [Datei] [--refresh-ms 150] [--corr-binning 9]`.
- **GPU-Pfad (wgpu, seit 1.2):** Compute-Shader (WGSL) für die g²/g³/g⁴-Histogramme über DirectX 12, Vulkan oder
  Metal. Gleiche Rechenvorschrift wie die CPU: Blöcke zu ≤ 256 Start-Marken mit Überlapp ±W, 32-bit-Relativzeiten je
  Block, Bins als atomare u32-Paare mit Übertrag (exakt bis 2⁶⁴); bit-identisch zur CPU (`tests/test_gx_gpu.py`).
  - Automatik: Beim Start wird die GPU in einem eigenen Prüfprozess samt Selbsttest geöffnet. Danach misst die Engine
    je Rechenart und Geometrie GPU gegen CPU und nimmt die GPU nur, wenn sie ≥ 10 % schneller ist; Nachprüfung alle
    200 Aufrufe. Jeder GPU-Fehler → Rückfall auf die CPU mit Hinweis in der Infozeile.
  - **Ehrlich gesagt:** Auf der bisher gemessenen integrierten Grafik (AMD Radeon, DirectX 12) rechnet die GPU exakt,
    ist aber nur 0,13–0,67× so schnell wie der Rust-Kern mit 8 Threads. Die Automatik behält dort die CPU, die
    Infozeile zeigt „GPU … vorhanden, CPU schneller“. Lohnend erst mit einer deutlich stärkeren (diskreten) Grafik;
    das ist noch nicht gemessen.
- Selbst bauen (Rust ≥ 1.80): `pip install maturin` und `maturin build --release -m rust/harp_gx_core/Cargo.toml -o wheelhouse`,
  danach `pip install wheelhouse/*.whl`; ohne GPU-Pfad mit `--no-default-features`.
- Vergleich: `python tools/bench_engines.py --threads 1,2,4,8 [--engines rust,gpu,auto]`, `python tools/bench_gpu.py`.

### Latenz und Bandbreite

- Der GX-Prozess liefert nach jedem Frame ein Ergebnis (Karten schon dort kodiert), ein Lese-Thread reicht es sofort
  an den Server weiter, der es ohne Wartetakt an die Clients schickt.
- Je Gerät geht nur, was die Ansicht zeigt: g³ nur die g³-Karte, g⁴ nur den g⁴-Würfel, g² bei jedem Ergebnis die
  Kacheln (≈ 1,5 kB), Histo/Zeit den Kopf ≈ 2 Hz für die Infozeile. In g³, g⁴ und Zeitverlauf kommen die
  Histogramm-Frames ohne Kurven (≈ 0,5 kB statt ≈ 25 kB).
- **Bandbreiten-Budget:** höchstens `HARP_GX_KBPS` kB/s (Standard 200) g³/g⁴-Daten je Gerät. Was darüber liegt, wird
  übersprungen, nicht verzögert: Die Latenz bleibt kurz, nur die Bildrate sinkt. Für mobile Daten z. B.
  `set HARP_GX_KBPS=100` vor `start_server.bat` bzw. `start_online.bat`.
- **„Latenz“ in der Infozeile** = Ende der Messzeit des neuesten Frames bis zur Übergabe an die Sende-Warteschlange
  dieses Geräts; dahinter „+ Netz ≈ … ms“ (halbe Ping-Laufzeit) und in g³/g⁴ die empfangene Bildrate in Hz.
  Nicht enthalten: Zeichnen im Browser und die Frame-Dauer selbst (Ereignisse am Frame-Anfang sind bis zu 150 ms älter).
- Gemessen (Box, `Thermisch_cw`, Ansicht g⁴, Median): Ende der Messzeit → Client 306 → 22 ms, 1,6 → 5,8 Hz, bei
  etwa gleicher Bandbreite (≈ 210 kB/s; Ansicht g³ ≈ 126 kB/s). Laptop von Herrn Eilers: ≈ 35 ms + Netz, ≈ 6 Hz.
  Messung: `python tools/latency_gx.py [Datei] [--view g4] [--clients 3]`.

### Umgebungsvariablen

Setzen Sie sie in einer Eingabeaufforderung im Programmordner vor `start_server.bat` bzw. `start_online.bat`
(z. B. `set HARP_GX_KBPS=100`). Ohne Variablen wählt das Programm alles selbst.

| Variable | Wirkung |
|---|---|
| `HARP_GX_KBPS=200` | Budget für g³/g⁴-Daten je Gerät in kB/s |
| `HARP_GX_ENGINE=gpu\|rust\|numba\|numpy` | g³/g⁴-Kern erzwingen |
| `HARP_GX_THREADS=n` | Zahl der Threads begrenzen |
| `HARP_GX_NO_GPU=1`, `HARP_GX_NO_RUST=1`, `HARP_GX_NO_NUMBA=1` | GPU, Rust bzw. Numba überspringen (`NO_RUST` gilt auch für den Server-Pfad) |
| `HARP_GX_GPU_BACKEND=dx12\|vulkan` | Grafikschnittstelle festlegen |
| `HARP_GX_GPU_ALLOW_CPU=1` | Software-Adapter (WARP, lavapipe) zulassen – nur für Tests |
| `HARP_STREAM_NUMPY=1` | Server-Pfad (Dekodieren, Histogramm, g²) mit NumPy statt Rust |
| `HARP_GX_DISABLE=1` | GX-Prozess (g³/g⁴) ganz aus |
| `HARP_TOKEN=…` | fester Zugangscode statt eines zufälligen |
| `HARP_TUNNEL_PROTOCOL=http2` | Cloudflare-Tunnel über HTTP/2, falls QUIC/UDP gesperrt ist |

### Automatische Wahl von Fenster und Bereich (cw)

Fenster und Bereich werden bei cw nach 0,5 s automatisch gewählt. Bei einem breiten Merkmal im g² (FWHM ≥ 50 ns)
gilt Fenster = FWHM/6 und Bereich = ±3·FWHM. Ohne Merkmal (Laser) wird das Fenster nach Statistik gewählt
(≈ 100 Quadrupel/s). Bei schmalen Merkmalen (Antibunching, Heralded, HOM) bleiben ±25 ns / 2 ns. Setzen Sie Fenster
oder Bereich selbst, ist die Automatik aus. Bei jedem Dateidurchlauf werden die Werte neu gesammelt. Zeit bis g³ und
g⁴ stabil sind (n ≥ 10, ±10 % vom Sollwert), live bei 1×: thermisch cw ≈ 2,3 s, Laser ≈ 1,3 s, thermisch gepulst ≈ 0,6 s.

Einschränkungen: Karten werden nur aufsummiert (kein Abklingen); g³/g⁴ sind die vollen (nicht verbundenen)
Korrelationen, Fehlerbalken gibt es nur für die Kacheln; snAPI-Quelle liefert keine Einzelereignisse (kein g³/g⁴);
Binär-Frames brauchen `DecompressionStream` (iOS ≥ 16.4); Kalibrierung braucht ein Merkmal im g² (beim kohärenten
Laser keine); Kacheln nutzen ein festes, bei τ=0 zentriertes Fenster; GPU-Pfad auf integrierter Grafik langsamer als
die CPU – dort rechnet automatisch die CPU.

## Funktionen

- **Fünf Ansichten:** Histogramm (Zeit nach Sync bzw. nach Referenzkanal), Zählraten-Zeitverlauf, Korrelation g²
  (τ = t(Kn) − t(Kref), T2 und T3), g³ (Karte, Diagonale, Schnitte) und g⁴ (τ₃-Schnitt, Diagonale);
  Kanäle einzeln ein-/ausblendbar.
- **T2 und T3**, Sync bei T2 als eigener Datenkanal **K0** (z. B. Herald-Detektor), Referenzkanal wählbar.
- **Steuerung vom Handy:** Start/Stopp/Reset, Binbreite, Länge, Tempo, Akkumulieren oder gleitendes Fenster;
  ein Client steuert, weitere sehen live mit.
- **Windows-Betrieb** mit Skripten; Zugriff im LAN oder über das Internet (Cloudflare Quick Tunnel, Zugangscode, QR-Code).
- **Simulation** (noch ohne Geräteanbindung) durch Wiedergabe von `.ptu`-Dateien in Echtzeit; neun synthetische Demodateien (Daten-Zips im Release).
- Server: Python/FastAPI/WebSocket, Oberfläche: uPlot, getestet mit pytest.

Version: einzige Quelle `harp/__init__.py` (`__version__`), abrufbar über `/api/health`.

Auch in Version 1.3.1 kommen die Daten **nicht von einer echten Harp**, sondern aus einer
**Messsimulation mit einer `.ptu`-Datei**, die in Echtzeit abgespielt wird.

> Status: funktionsfähiger Prototyp. Die reine Python-Quelle ist vollständig getestet. Die snAPI-Quelle
> wurde unter **Linux** mit dem offiziellen snAPI-Wheel 1.2.5 (File-Device) getestet, **unter Windows
> noch nicht**. Die Quelle für eine echte Harp ist nur ein **Platzhalter**.

---

## 1. Architektur

```
 Messrechner (Windows)                                             Smartphone / Tablet / PC
┌───────────────────────────────────────────────────────────┐     ┌─────────────────────────┐
│  Datenquelle (wählbar in config.toml)                     │     │ Browser (PWA-fähig)     │
│   ├─ PurePythonPtuSource  PTU lesen + NumPy-Histogramm     │     │  index.html + app.js    │
│   ├─ SnapiPtuSource       snAPI File-Device + Histogram   │     │  uPlot (lokal, kein CDN)│
│   │                       (eigener Worker-Prozess)        │     │                         │
│   └─ HH500LiveSource      Platzhalter für echtes Gerät    │     │  • Histogramm (log)     │
│              │ Frame (Histogramm-Inkrement, Zählungen)    │     │  • Zählraten            │
│              ▼                                            │     │  • Zählraten-Verlauf    │
│  HarpService (FastAPI/uvicorn)                            │ WS  │  • Steuerung            │
│   • Akkumulieren / gleitendes Fenster                     │◄───►│                         │
│   • Rebinning für die Anzeige (≤ display_points)          │JSON │                         │
│   • Validierung, Steuer-Sperre, Befehlsprotokoll          │     │                         │
└───────────────────────────────────────────────────────────┘     └─────────────────────────┘
```

* **GX-Prozess** (seit 1.0): Die Ereignisse jedes Frames gehen zusätzlich an einen eigenen Prozess (`harp/gx`), der
  g²/g³/g⁴ rechnet und Ergebnisse sofort zurückschickt (Push, seit 1.3); zum Handy gehen sie als komprimierte
  Binär-Frames, nur für die sichtbare Ansicht und im Bandbreiten-Budget.
* **Kein TTTR-Rohdatenstrom zum Handy**: Histogrammiert wird ausschließlich auf dem Messrechner. Zum Client
  gehen nur die (ggf. zusammengefassten) Histogramm-Arrays, Zählraten und Statusinformationen mit 5–10 Hz.
* **Takt**: Der Server liest pro Frame `Frame-Intervall × Tempo` Messzeit aus der Quelle (z. B. 150 ms × 1 = 150 ms)
  und wartet dann bis zum nächsten Frame. Die aufgezeichnete Zeitbasis der PTU-Datei wird damit eingehalten.
* **Protokoll**: WebSocket `/ws`, JSON-Nachrichten
  * Server → Client: `status` (Einstellungen, Quelle, Dateien, Steuer-Status), `frame` (Histogramme, Raten),
    `trace` (bisheriger Zählratenverlauf bei Verbindungsaufbau), `ack` (Antwort auf Befehle)
  * Client → Server: `{"type":"command","cmd":"set","params":{"binning":4},"id":1}`
* REST: `GET /api/health`, `GET /api/status`, `GET /api/files`.

### Verzeichnisstruktur

| Pfad | Inhalt |
|---|---|
| `run_server.py` | Startskript (uvicorn) |
| `config.toml` | Konfiguration (Port, Quelle, Datenordner, Token, Standardwerte) |
| `harp/ptu.py` | PTU-Reader/-Writer (Header-Tags, T2/T3-Records, Overflow-Korrektur) |
| `harp/histogram.py` | Histogrammierung T3/T2, Akkumulator, Rebinning |
| `harp/sources/` | Datenquellen: `pure_ptu.py`, `snapi_ptu.py`, `hh500_live.py` (Stub) |
| `harp/control.py` | Einstellungen + Wertebereiche, Steuer-Sperre, Befehlsprotokoll |
| `harp/server.py` | FastAPI-App, WebSocket, Messschleife |
| `harp/auth.py` | Zugangscode, Anmeldeseite, Sitzungs-Cookie, Fehlversuch-Sperre, Origin-Prüfung |
| `web/` | Web-App (HTML/CSS/JS, `vendor/uPlot` lokal, Manifest, Service Worker) |
| `data/` | PTU-Dateien (neun GX-Demodateien `Demo_Synthetisch_T2_*.ptu`, s. oben) |
| `tools/generate_ptu.py` | Generator für synthetische PTU-Dateien |
| `tools/crosscheck.py` | Gegenprobe des Readers mit `ptufile` und `phconvert` |
| `tools/ws_client_check.py` | End-to-End-Test gegen den laufenden Server |
| `tools/screenshot.py` | Headless-Screenshots (Playwright) |
| `tools/print_online_info.py` | Ausgabe von Adresse, Code und QR-Code beim Online-Start |
| `install_windows.bat` | Einmalige Installation (Python-venv + Pakete) |
| `start_server.bat` | Start für diesen PC / lokales Netz (ohne Tunnel) |
| `start_online.bat` + `start_online.ps1` | Start mit Zugangscode + Cloudflare Quick Tunnel (Internet) |
| `stop_online.bat` + `stop_online.ps1` | Beendet Server und Tunnel des Online-Starts |
| `stop_online.sh` | Linux-Gegenstück zum Beenden (Entwicklungsrechner) |
| `ANLEITUNG_WINDOWS.md` | Schritt-für-Schritt-Anleitung für den Online-Betrieb unter Windows |
| `tests/` | pytest-Tests |
| `logs/commands.jsonl` | Protokoll aller Steuerbefehle (Zeit, Client, Adresse, Befehl, Ergebnis) |

---

## 2. Installation unter Windows

Voraussetzungen: Windows 10/11 (64 Bit), Internet für die einmalige Installation.

1. **Python 3.13 (64 Bit)** von <https://www.python.org/downloads/> installieren („Add python.exe to PATH“ ankreuzen).
   PicoQuant empfiehlt in der snAPI-Installationsanleitung Python 3.13; snAPI selbst verlangt Python ≥ 3.10.
2. Programm-Zip entpacken, z. B. nach `C:\HarpGXMobil\` (ergibt `C:\HarpGXMobil\harp-gx-mobil`).
3. Doppelklick auf **`install_windows.bat`** (sucht Python, legt `.venv` an, installiert `requirements.txt`) –
   oder manuell in der Eingabeaufforderung:
   ```bat
   cd C:\HarpGXMobil\harp-gx-mobil
   py -3.13 -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
   `requirements.txt` enthält nur Pakete, für die fertige Windows-Wheels (win_amd64, Python 3.12–3.14) existieren
   (FastAPI, uvicorn[standard], NumPy, qrcode, pytest, httpx) – es wird kein C-Compiler benötigt (geprüft mit
   `pip download --platform win_amd64 --only-binary=:all:`). Optionale Werkzeuge stehen in
   `requirements-optional.txt` (ptufile, phconvert, playwright, snAPI).
4. **Nur für die snAPI-Quelle bzw. später das echte Gerät** (laut snAPI-Doku *Installation*):
   * Microsoft Visual C++ Redistributable (x64) installieren, falls nicht vorhanden:
     <https://aka.ms/vs/17/release/vc_redist.x64.exe>
   * `pip install snAPI`
   * Für eine echte Harp zusätzlich deren Softwarepaket (Treiber) von <https://www.picoquant.com/downloads/>
     installieren (Beispiel HydraHarp 500:
     <https://downloads.picoquant.com/software/HydraHarp500/Hydraharp_500_Release_v1.0.0.0.zip>)
     und die Harp einmal mit der PicoQuant-Software prüfen.
   * Kontrolle: `python -c "import snAPI"` darf keinen Fehler melden.

## 3. Starten

**Über das Internet (Handy mit mobilen Daten):** `start_online.bat` – siehe Abschnitt 4a und die ausführliche
[ANLEITUNG_WINDOWS.md](ANLEITUNG_WINDOWS.md).

**Nur an diesem PC bzw. im lokalen Netz:**
```bat
start_server.bat
```
oder
```bat
.venv\Scripts\activate
python run_server.py                 REM Einstellungen aus config.toml
python run_server.py --port 9000     REM anderer Port
python run_server.py --source snapi  REM snAPI-Quelle statt reinem Python
```

Am Messrechner selbst: <http://localhost:8765/>.
Beim Start wird `default_file` geöffnet und (bei `autostart = true`) sofort abgespielt.

## 4. Öffnen auf dem Smartphone im LAN

1. Handy und Messrechner müssen im **selben (vertrauenswürdigen) Netz** sein.
2. IP-Adresse des Messrechners ermitteln: `ipconfig` → „IPv4-Adresse“, z. B. `192.168.1.50`.
3. Windows-Firewall für den Port öffnen (Eingabeaufforderung **als Administrator**, nur Profil „Privat“):
   ```bat
   netsh advfirewall firewall add rule name="Harp GX Mobil" dir=in action=allow protocol=TCP localport=8765 profile=private
   ```
4. Am Handy im Browser öffnen: `http://192.168.1.50:8765/` (mit Token: `http://192.168.1.50:8765/?token=IHR_TOKEN`).
5. Optional „Zum Startbildschirm hinzufügen“. Hinweis: Der Service Worker (Offline-App-Hülle) wird von
   Browsern nur über **HTTPS** oder `localhost` aktiviert; über `http://<IP>` funktioniert die Seite
   vollständig, aber ohne Offline-Cache.

## 4a. Zugriff über das Internet (Cloudflare Quick Tunnel)

`start_online.bat` (ruft `start_online.ps1` auf) erledigt:

1. erzeugt einen zufälligen **Zugangscode** (10 Zeichen aus `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, also ohne 0/O, 1/I/L)
   – oder übernimmt `HARP_TOKEN`, falls gesetzt;
2. startet den Server **nur auf `127.0.0.1:8765`** (von außen nicht direkt erreichbar) mit diesem Code;
3. lädt bei Bedarf `cloudflared.exe` vom offiziellen GitHub-Release
   (`https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe`) nach `tools\`
   – oder nutzt ein bereits installiertes (`winget install --id Cloudflare.cloudflared`);
4. startet `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8765` (Quick Tunnel, kein Konto nötig),
   liest die `https://….trycloudflare.com`-Adresse aus `logs\cloudflared.log` und zeigt Adresse, Code,
   Direkt-Link `…/?token=CODE` und einen QR-Code an;
5. beendet beides, wenn im Fenster Enter gedrückt wird; alternativ `stop_online.bat`.

Technische Details:

* **Anmeldung**: Ohne gültige Sitzung leitet jede Seite auf `/login` um, `/api/*` antwortet mit 401, der WebSocket
  wird abgewiesen (HTTP 403). Nach Eingabe des Codes (oder Aufruf von `/?token=CODE`) setzt der Server ein
  Sitzungs-Cookie (`HttpOnly`, `SameSite=Lax`, hinter dem Tunnel zusätzlich `Secure`, gültig 7 Tage oder bis zum
  Neustart). Fehlversuche: Sperre je Client-IP und global (Bremse gegen Durchprobieren).
* **Hinter cloudflared**: cloudflared reicht den öffentlichen Hostnamen als `Host` weiter und setzt
  `X-Forwarded-For`/`X-Forwarded-Proto: https`/`CF-Connecting-IP`. uvicorn übernimmt `X-Forwarded-*` nur von
  127.0.0.1 (Standard `forwarded_allow_ips`), `CF-Connecting-IP` wird ebenfalls nur von localhost akzeptiert.
  Die WebSocket-**Origin-Prüfung** vergleicht den Hostnamen der Origin (`https://abc.trycloudflare.com`) mit
  `Host` bzw. `X-Forwarded-Host` (Groß-/Kleinschreibung und Standardports werden normalisiert) – fremde Origins werden
  abgewiesen (Schutz gegen Cross-Site-WebSocket-Hijacking).
  Grundlage: cloudflared-Quelltext `ingress/origin_proxy.go` (`httpService.RoundTrip`) – der ursprüngliche `Host`
  bleibt erhalten; nur wenn `httpHostHeader` konfiguriert ist, wird er ersetzt und als `X-Forwarded-Host`
  weitergegeben (<https://github.com/cloudflare/cloudflared/blob/master/ingress/origin_proxy.go>).
* Logs: `logs\server-online.log`, `logs\cloudflared.log`; `logs\online_info.txt` enthält Adresse und Code und wird
  beim Beenden gelöscht.
* Falls QUIC/UDP im Netz gesperrt ist: vor dem Start `set HARP_TUNNEL_PROTOCOL=http2`.

## 5. Bedienung und Bezug zum echten Gerät

Jede Änderung in der Oberfläche wird als Befehl an den Server geschickt und dort **validiert**. Es darf immer
nur **ein Client steuern** (Knopf „Steuerung übernehmen“; die erste Änderung übernimmt die Steuerung automatisch,
sofern frei). Die Sperre wird beim Trennen oder nach `lock_timeout_s` Inaktivität frei. Alle anderen Clients
sehen die Daten nur an. Jeder Befehl wird in `logs/commands.jsonl` protokolliert.

| Bedienelement | Bereich (Server-Prüfung) | Simulation | Spätere Abbildung am HH500 (snAPI) [ungeprüft] |
|---|---|---|---|
| Start / Stopp | – | Wiedergabe starten / pausieren | `histogram.measure()` / `stopMeasure()` |
| Reset | – | Akkumulation + Verlauf löschen | `histogram.clearMeasure()` |
| Von vorn | – | Datei zurückspulen | – |
| Frame-Intervall | 100–2000 ms | Anzeige-/Integrationstakt | Sequence-Fenster (`setSequenceMode(Timer, param)`) |
| Wiedergabe-Tempo | 0,05–100 (1 = „Echtzeit“) | Messzeit pro Frame = Intervall × Tempo | entfällt (Echtzeit) |
| Binbreite (Binning-Code) | 0–15 | Bin = Dateiauflösung × 2^n; angezeigt wird nur die Breite | `device.setBinning()` |
| Histogrammlänge | Code 0–7 (1024…131072 Bins) | Länge des Histogramms | `device.setHistoLength()` (2^(10+Code)) |
| Modus | Akkumulieren / gleitend (2–300 Frames) | serverseitig | serverseitig |
| Kanäle (API `channels`) | 1…Anzahl Kanäle der Quelle | Auswahl der übertragenen Kanäle; beim Öffnen einer Datei alle | zusätzlich `device.setInputChannelEnable()` |
| Referenzkanal (g²) / Binbreite g² | `ref_channel` 1…n / `corr_binning` | Korrelationsansicht | – |
| Anzeige-Punkte | 64–8192 | Rebinning nur für die Übertragung | gleich |
| PTU-Datei | nur Dateien in `data/` (kein Pfad) | Datei wechseln | entfällt |
| K0–K4-Tasten, Ansicht Histogramm/Korrelation/Zeitverlauf | (nur im Client) | Ein-/Ausblenden, y-Achse Histogramm immer log | – |

## 6. Eigene / echte PTU-Datei verwenden

1. Datei (`*.ptu`) in den Ordner `data/` kopieren (oder `data_dir` in `config.toml` ändern).
2. In der Oberfläche unter „PTU-Datei“ auswählen – oder in `config.toml` `default_file = "meine.ptu"` setzen.
3. Unterstützte Record-Typen (reine Python-Quelle): PicoHarp 300 T2/T3, HydraHarp V1/V2 T2/T3,
   TimeHarp 260 N/P T2/T3, Generic T2/T3 (MultiHarp, PicoHarp 330). **Welchen Record-Typ die HydraHarp 500
   (Beispiel) schreibt, ist nicht verifiziert** [unsicher]; die synthetische Datei verwendet Generic T3 (`0x00010307`).
   Eine echte HH500-Datei sollte als Erstes mit `python tools/crosscheck.py data\meine.ptu` geprüft werden.
4. Ansichten Histogramm, Zeitverlauf und Korrelation (g²-Rohkurve) für T2 und T3 gleichermaßen; g³/g⁴ siehe oben:
   * **Histogramm** (Start-Stopp, log): T3 → Mikrozeit (dtime, Start = Sync); T2 → Zeit seit dem letzten
     Ereignis auf dem **Referenzkanal** (ersetzt den Sync; Achse „t nach K1 / ns“, Referenz ohne eigene Kurve).
     T2-Startwert: 1024 Bins über ≈ 10 Sync-Perioden (HBT-Demo: 1,024 ns, 0–1 µs).
   * **Zeitverlauf**: Zählraten (kcps) über der Dateizeit.
   * **Korrelation** (log, x-Bereich symmetrisch um τ = 0, Diagramm in der Karte zentriert): Zeitdifferenz-Histogramm τ = t(Kn) − t(Kref) für jeden Kanal außer dem
     **Referenzkanal** (Auswahl „Referenzkanal (g²)“, K1…Kn; der Referenzkanal hat keine eigene Kurve).
     T3 nutzt die absolute Zeit nsync × Sync-Periode + dtime × Auflösung. Fenster symmetrisch,
     2048 Bins; Binbreite „Binbreite g²“ wird beim Öffnen so gewählt, dass das Fenster ≈ ±5 Sync-Perioden umfasst
     (T3-Demo 128 ps → ±131 ns, T2-HBT-Demo 512 ps → ±524 ns). Gezählt werden **alle** Paare im Fenster,
     auch über Frame-Grenzen hinweg genau einmal (`harp/histogram.py: correlate`, Tests in
     `tests/test_correlation.py`). Keine Normierung auf g²(τ) (Rohzählungen).
   Server berechnet Histogramm und Korrelation in jedem Frame (gering, getrennt akkumuliert) und sendet beide.
   Dateiliste: jede Datei genau einmal (früher Doppelte unter Windows, weil `*.ptu` und `*.PTU` auf dem
   nicht case-sensitiven Dateisystem dieselben Dateien fanden).
   Beim Öffnen einer Datei werden Binbreite und Länge auf Startwerte gesetzt: T3 → Standard
   (Auflösung × 8, 1024 Bins); T2 → 4096 Bins und Binbreite so, dass das Fenster ≈ 10 Sync-Perioden
   (±5 Perioden) umfasst (Demo: 256 ps, ±524 ns). Die Sync-Rate-Kachel zeigt bei T2-Dateien ohne
   aufgezeichnete Sync-Ereignisse die Rate aus dem Header (`TTResult_SyncRate`).
5. Sehr große Dateien: Die Datei wird speichergemappt und blockweise dekodiert; beim Öffnen erfolgt ein
   schneller Durchlauf zur Bestimmung von Dauer und Kanälen (bei mehreren GB einige Sekunden).

Synthetische Dateien erzeugen: GX-Demodateien siehe oben (`tools\generate_gx.py`). Der Generator aus Mobil
(`tools\generate_ptu.py`, T3-Fluoreszenz, HBT, Heralded) ist weiter enthalten, z. B.:
```bat
python tools\generate_ptu.py --out data\Demo_Synthetisch_T3_Fluoreszenz_4Kanal_5min.ptu --duration 300 --rates 5000,7500,10000,3500
```

**Sync als Datenkanal K0 (T2):** Bei T2 ist der Sync-Eingang der Harp ein normaler Zeitkanal; die
Sync-Ereignisse stehen mit Zeitstempel in der Datei (Spezial-Record, Kanal 0). Enthält eine T2-Datei solche
Ereignisse, erscheinen sie als **K0** (violett): eigene Taste in der Kopfzeile, eigene Zählratenkachel mit
gemessener Rate (statt „Sync“), Kurven in allen drei Ansichten, als Referenzkanal wählbar (Standard beim
Öffnen). Ist K0 zufällig (Herald, Abstände nicht konstant), werden ns-Fenster gewählt (s. o.); bei regelmäßigem
Laser-Sync Fenster über ≈ 10 Sync-Perioden. T2-Dateien ohne Sync-Ereignisse: keine K0-Taste, Kachel „Sync“ mit
Header-Rate. T3: unverändert (Kachel „Sync“, Histogramm = Mikrozeit nach Sync).

## 7. Umstieg auf snAPI und später auf eine echte Harp

* **snAPI-Quelle** (`[source] kind = "snapi"` oder `--source snapi`): öffnet die PTU-Datei als snAPI-*File-Device*
  und lässt snAPI histogrammieren (`snAPI.getFileDevice()`, `histogram.setSequenceMode(Timer, …)`,
  `histogram.measure()`, `histogram.getData()`). snAPI läuft dabei in einem **eigenen Worker-Prozess**
  (siehe Einschränkungen). Ein Frame wird aus Basisfenstern von `snapi_base_window_s` (50 ms) summiert.
* **Echtes Gerät** (`kind = "hh500"`): in 1.0 nur Platzhalter (`harp/sources/hh500_live.py`), der die geplante
  Abbildung der Befehle auf snAPI-Funktionen dokumentiert. Für V2 sind nötig: Implementierung mit
  `getDevice()`/`initDevice(MeasMode.Histogram oder T3)`/`loadIniConfig()`, Zählraten über
  `device.getCountRates()`, Trigger-/Offset-/Sync-Teiler-Befehle mit Wertebereichen aus `hh500defin.h`,
  Sicherheitsabfragen (z. B. Trigger-Ausgang/Laser) und Tests am Gerät.
* Wichtig: Die HH500 kann laut HH500Lib-Handbuch nur von **einem Programm gleichzeitig** benutzt werden – während
  der Server das Gerät nutzt, darf keine andere PicoQuant-Software darauf zugreifen.

## 8. Datenreduktion und Nutzlast (gemessen)

Pro Frame werden nur die Histogramme der ausgewählten Kanäle übertragen, bei Bedarf auf ≤ `display_points`
Punkte zusammengefasst (Summen benachbarter Bins, Faktor 2^n). Gemessen mit der Demo-Datei (JSON, ohne Kompression):

| Kanäle × Bins → Anzeige-Punkte | JSON/Frame | mit Deflate* | bei 6,7 Frames/s |
|---|---|---|---|
| 4 × 1024 → 1024 | ≈ 13 kB | ≈ 4,4 kB | ≈ 90 kB/s |
| 4 × 1024 → 256 | ≈ 3,6 kB | ≈ 1,5 kB | ≈ 24 kB/s |
| 8 × 1024 → 1024 | ≈ 25 kB | ≈ 4,6 kB | ≈ 170 kB/s |
| 4 × 8192 → 1024 | ≈ 9 kB | ≈ 0,9 kB | ≈ 60 kB/s |
| 4 × 8192 → 4096 | ≈ 35 kB | ≈ 2,9 kB | ≈ 240 kB/s |

\* uvicorn/websockets bieten WebSocket-Kompression (permessage-deflate) an; ob der Browser sie nutzt, hängt vom
Browser ab [unsicher]. Die aktuelle Größe pro Frame und kB/s zeigt die Oberfläche unten unter „Datenmenge“.
Zum Vergleich: ein TTTR-Rohdatenstrom mit 1 Mcps wären 4 MB/s.

## 9. Tests und Prüfwerkzeuge

```bat
python -m pytest -q                                   REM Unit-/Integrationstests
python tools\crosscheck.py data\meine.ptu            REM Gegenprobe mit ptufile/phconvert
python tools\ws_client_check.py ws://127.0.0.1:8765/ws REM End-to-End gegen laufenden Server
python tools\screenshot.py http://127.0.0.1:8765/     REM Screenshots (pip install playwright; playwright install chromium)
```
Die Tests decken ab: PTU-Header/Tag-Typen, T2/T3-Dekodierung inkl. Overflow-Varianten und Marker,
blockweises Dekodieren, Vergleich mit `ptufile`, Histogrammierung (Binning, Länge, T2 Start-Stopp über
Frame-Grenzen), Akkumulieren/gleitendes Fenster, Rebinning, Validierung aller Steuerparameter, Pfad-Schutz,
Steuer-Sperre, WebSocket-Ablauf, Anmeldung (Login-Seite, `?token=`, Cookie, Fehlversuch-Sperre) sowie die
Tunnel-Situation (Host/Origin `abc.trycloudflare.com`, `X-Forwarded-Proto`, `CF-Connecting-IP`, fremde Origin); mit installiertem snAPI zusätzlich den Vergleich
snAPI-Histogramm ↔ eigenes Histogramm.

## 10. Bekannte Einschränkungen (1.3.1)

* Keine echte Harp; die Live-Quelle `hh500` ist ein Platzhalter.
* snAPI-Quelle unter Windows ungetestet. Unter Linux (snAPI 1.2.5) beobachtet: Öffnen einer weiteren Datei im
  selben Prozess nach `stopMeasure()` mitten in der Datei führte zu Hängern/Abstürzen → deshalb Worker-Prozess,
  der bei Dateiwechsel, „Von vorn“ und Loop neu gestartet wird (dauert ca. 1 s). Der snAPI-Prozess belegt ca. 0,9 GB RAM.
  Das letzte, unvollständige Fenster einer Datei liefert snAPI nicht aus.
* Bei der snAPI-Quelle wird das Binning serverseitig auf das von snAPI gelieferte Histogramm (Dateiauflösung)
  angewendet; snAPI selbst erlaubt die Binbreite nur im T2-Modus.
* Zählraten = Ereignisse im Frame / Messzeit des Frames (keine Totzeitkorrektur). Sync-Rate bei T3 aus der
  Sync-Periode (`MeasDesc_GlobalResolution`) bzw. bei snAPI aus `AveSyncRate`.
* Marker werden gezählt, aber nicht ausgewertet; keine Imaging-/FLIM-Auswertung, keine Lebensdauer-Fits.
* Histogramm-Frames als JSON (einfach, gut messbar); g³/g⁴ als komprimierte Binär-Frames.
* Einstellungen gelten global für alle Clients (es gibt nur eine Messung).

## 11. Sicherheit

* **Internet-Zugriff nur über `start_online.bat`** (Quick Tunnel, HTTPS bis Cloudflare, Server nur auf
  127.0.0.1, Zugangscode Pflicht). Keine Portweiterleitung im Router! Quick Tunnels sind laut Cloudflare für Tests
  gedacht (keine Verfügbarkeitsgarantie, neue Adresse bei jedem Start). Für Dauerbetrieb später VPN
  (WireGuard/Tailscale) oder einen benannten Cloudflare-Tunnel mit Cloudflare Access.
* Im Tunnel-Betrieb terminiert Cloudflare TLS; der Verkehr ist damit für Cloudflare einsehbar. Für Messdaten eines
  Prototyps vertretbar, für vertrauliche Daten nicht.
* **Zugangscode**: `HARP_TOKEN` (Umgebung), `--token` oder `token = "…"` in `config.toml`. Ist ein Code gesetzt,
  sind Web-Oberfläche, `/api/*` und `/ws` geschützt (Vergleich in konstanter Zeit, Fehlversuch-Sperre). Code nicht
  weitergeben; nach Benutzung den Online-Betrieb beenden – beim nächsten Start gibt es einen neuen Code.
* Im LAN-Betrieb (`start_server.bat`) ist die Übertragung unverschlüsselt (HTTP/WS); dort nur in vertrauenswürdigen
  Netzen arbeiten und ebenfalls einen Code setzen.
* Serverseitige Validierung aller Parameter, Dateiauswahl nur aus `data/` (kein Pfad-Traversal),
  ein steuernder Client, Befehlsprotokoll.
* Mit echtem Gerät (V2) sind zusätzlich Sicherheitsverriegelungen nötig (z. B. kein Fernschalten des
  Trigger-Ausgangs, der einen Laser auslösen kann – das HH500Lib-Handbuch weist bei `HH500_SetTriggerOutput`
  ausdrücklich auf Lasersicherheit hin).

## 12. Quellen

* PicoQuant snAPI: <https://github.com/PicoQuant/snAPI> (Main.py, Constants.py, demos/, doc_source/install.rst,
  wheelhouse/), Doku <https://picoquant.github.io/snAPI/>
* PicoQuant PTU-Format-Demos und Doku „TTTR Record Format“, „Tag Dictionary“ (im HydraHarp-500-Paket v1.0.0.0,
  Ordner `filedemo`, sowie <https://github.com/PicoQuant/PicoQuant-Time-Tagged-File-Format-Demos>)
* HydraHarp 500 Softwarepaket v1.0.0.0 (HH500Lib-Handbuch, `hh500defin.h`):
  <https://downloads.picoquant.com/software/HydraHarp500/Hydraharp_500_Release_v1.0.0.0.zip>
* uPlot 1.6.32 (MIT-Lizenz, `web/vendor/LICENSE-uPlot.txt`): <https://github.com/leeoniya/uPlot>
* Unabhängige Reader für die Gegenprobe: `ptufile` (<https://pypi.org/project/ptufile/>), `phconvert`

## 13. Lizenz

MIT-Lizenz, siehe [`LICENSE`](LICENSE) – Copyright (c) 2026 ExplorationSE.
Enthaltene Fremdsoftware: uPlot (MIT, © Leon Sorokin), Lizenztext in `web/vendor/LICENSE-uPlot.txt`.
PicoQuant, HydraHarp, MultiHarp, PicoHarp, TimeHarp und snAPI sind Marken bzw. Software der PicoQuant GmbH;
dieses Projekt ist davon unabhängig.
