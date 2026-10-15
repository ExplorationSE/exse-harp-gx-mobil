# ExSE Harp GX Mobil – Anleitung: Betrieb unter Windows mit Zugriff vom Handy über das Internet

Diese Anleitung führt Sie Schritt für Schritt durch Installation, Start und Bedienung von ExSE Harp GX Mobil
(Simulation aus einer PTU-Datei) auf Ihrem eigenen Windows-PC. Das Handy greift über das Internet
(z. B. mobile Daten) darauf zu – über einen **Cloudflare Quick Tunnel**. Sie benötigen dafür **kein Konto**,
keine Router-Einstellung und keine Portfreigabe.

> **Kurzfassung:** Python 3.13 installieren („Add python.exe to PATH“ ankreuzen) → ZIP entpacken →
> `install_windows.bat` → `start_online.bat` → Adresse + Code am Handy eingeben (oder QR-Code scannen) →
> zum Beenden Enter im Fenster drücken.

---

## 0. Was passiert technisch?

```
Handy (Browser, mobile Daten)
   │  HTTPS  https://<zufällige-wörter>.trycloudflare.com
   ▼
Cloudflare (Internet)
   │  ausgehende Verbindung, von Ihrem PC aufgebaut (cloudflared.exe)
   ▼
Ihr Windows-PC:  cloudflared.exe  ──►  Harp-GX-Mobil-Server  http://127.0.0.1:8765  (nur lokal)
                                         └─ spielt die Demo-PTU-Datei ab und histogrammiert
```

* Der Server lauscht nur auf `127.0.0.1` – aus Ihrem Netzwerk oder dem Internet ist er **nicht direkt**
  erreichbar, ausschließlich über den Tunnel.
* Wer die Adresse kennt, sieht zunächst nur eine **Anmeldeseite**. Ohne den **Zugangscode** gibt es weder Daten
  noch Steuerung.
* Datenquelle sind neun mitgelieferte synthetische T2-Messungen `data\Demo_Synthetisch_T2_*.ptu` mit bekannten
  g⁽²⁾/g⁽³⁾/g⁽⁴⁾ (Standard: `Demo_Synthetisch_T2_Thermisch_cw_g2g3g4_3s.ptu`, 4 Kanäle, läuft in Schleife; Übersicht im README). Es wird **kein Messgerät** und **kein snAPI** benötigt.

## 1. Voraussetzungen

* Windows 10 oder 11, 64 Bit, Internetzugang.
* ca. 300 MB freier Speicher.
* Ein Smartphone mit aktuellem Browser (Chrome, Safari, Firefox, Edge).
* Rechte, Programme zu installieren (keine Administratorrechte nötig, wenn Python „nur für mich“ installiert wird).

## 2. Python installieren (einmalig)

1. Öffnen Sie <https://www.python.org/downloads/windows/> und laden Sie den
   **„Windows installer (64-bit)“ für Python 3.13** herunter (3.12 oder 3.14 funktionieren ebenfalls;
   3.13 wird empfohlen, weil PicoQuant sie auch für snAPI empfiehlt).
2. Starten Sie den Installer. **Wichtig:** Setzen Sie unten im ersten Fenster das Häkchen bei
   **„Add python.exe to PATH“**. Dann „Install Now“.
3. Kontrolle (optional): Eingabeaufforderung öffnen (Windows-Taste, `cmd`, Enter) und eingeben:
   ```
   py --version
   ```
   Es sollte z. B. `Python 3.13.x` erscheinen.

> Falls `python` den Microsoft Store öffnet: Das ist nur ein Platzhalter von Windows. Installieren Sie Python
> wie oben von python.org; `install_windows.bat` verwendet bevorzugt den Python-Launcher `py`.

## 3. Paket entpacken

1. Speichern Sie `exse-harp-gx-mobil-<Version>-programm.zip` und die Daten-Zips z. B. im Ordner „Downloads“.
2. Rechtsklick → **„Alle extrahieren…“** → Ziel z. B. `C:\ExSE` (kurzer Pfad ohne Sonderzeichen empfohlen).
3. Danach gibt es den Ordner `C:\ExSE\exse-harp-gx-mobil` mit u. a. `install_windows.bat`, `start_online.bat`,
   `stop_online.bat`, `start_server.bat`, `LIESMICH.txt` und `README.md`.
4. Die neun Demodateien `Demo_Synthetisch_T2_*.ptu` aus den Daten-Zips (daten-1 bis daten-8) direkt in
   `C:\ExSE\exse-harp-gx-mobil\data\` legen (ohne Unterordner).

> Tipp: Falls Windows beim Öffnen der ZIP-Datei warnt, können Sie vor dem Entpacken Rechtsklick auf die ZIP →
> **Eigenschaften** → unten **„Zulassen“** anhaken → OK. Dann erscheinen später weniger Warnungen.

## 4. Installation (einmalig): `install_windows.bat`

1. Doppelklick auf **`install_windows.bat`** im Ordner `exse-harp-gx-mobil`.
2. Falls **„Der Computer wurde durch Windows geschützt“** (SmartScreen) erscheint: auf **„Weitere Informationen“**
   und dann **„Trotzdem ausführen“** klicken. Die Skripte sind unsignierte Textdateien; Sie können sie vorher mit
   dem Editor ansehen.
3. Das Skript legt eine eigene Python-Umgebung (`.venv`) im Ordner an und lädt die Pakete (FastAPI, uvicorn,
   NumPy, qrcode, pytest). Das dauert je nach Verbindung 1–5 Minuten. Es wird **kein Compiler** benötigt.
4. Am Ende steht „Fertig.“ – Fenster mit einer Taste schließen.

## 5. Online starten: `start_online.bat`

1. Doppelklick auf **`start_online.bat`** (ggf. erneut SmartScreen wie oben bestätigen).
2. Beim **ersten** Start lädt das Skript automatisch das offizielle Programm **`cloudflared.exe`** von GitHub
   (Cloudflare, ca. 55 MB) nach `exse-harp-gx-mobil\tools\`. Ist cloudflared bereits installiert, wird dieses verwendet.
   *Alternative, falls der Download scheitert:* in einer Eingabeaufforderung
   ```
   winget install --id Cloudflare.cloudflared
   ```
   ausführen und `start_online.bat` erneut starten.
3. Nach 10–30 Sekunden erscheint ein Kasten etwa so:
   ```
   ==================================================================
     ExSE Harp GX Mobil ist ONLINE (Cloudflare Quick Tunnel)
   ==================================================================
     Adresse:      https://beispiel-woerter.trycloudflare.com
     Zugangscode:  K7QM4-XPR9H
     Direkt-Link:  https://beispiel-woerter.trycloudflare.com/?token=K7QM4XPR9H
   ==================================================================
     QR-Code (Direkt-Link inkl. Code) mit der Handy-Kamera scannen:
     ███████████████████…
   ```
4. **Lassen Sie dieses Fenster offen**, solange Sie testen. Adresse und Code stehen zusätzlich in
   `exse-harp-gx-mobil\logs\online_info.txt` (wird beim Beenden gelöscht).
5. Falls eine **Windows-Firewall-Meldung** erscheint (für Python oder cloudflared): Für den Tunnel ist **keine**
   eingehende Freigabe nötig. Sie können „Abbrechen“ wählen bzw. nur „Private Netzwerke“ zulassen – der Zugriff
   über das Internet funktioniert trotzdem, weil cloudflared die Verbindung **von innen nach außen** aufbaut.

## 6. Am Handy öffnen und anmelden

1. Schalten Sie am Handy WLAN ruhig aus – es soll ja über **mobile Daten** funktionieren.
2. Entweder den **QR-Code** mit der Kamera-App scannen (öffnet den Direkt-Link inklusive Code), **oder** die
   Adresse `https://….trycloudflare.com` von Hand in den Browser tippen.
3. Ohne Code erscheint die Seite **„Harp GX Mobil“** mit einem Eingabefeld. Code eingeben → **„Anmelden“**.
   Groß-/Kleinschreibung, Leerzeichen und der Bindestrich spielen keine Rolle (`k7qm4 xpr9h` geht auch).
   Zur Sicherheit wird nach mehreren falschen Eingaben kurz gesperrt.
4. Danach bleibt das Handy angemeldet (Cookie, max. 7 Tage bzw. bis `start_online.bat` neu gestartet wird).

> Die neue Adresse ist manchmal erst **nach 10–60 Sekunden** weltweit bekannt. Meldet der Browser „Server nicht
> gefunden“, kurz warten und neu laden.

## 7. Was Sie ausprobieren können

* **Histogramm** pro Kanal (Abklingkurven mit verschiedenen Lebensdauern, logarithmische Achse); oben links
  **Histo | Zeit** umschalten auf den **Zählraten-Verlauf**; Tasten **K1–K4** blenden Kurven ein/aus.
* **Zählraten** (Sync und je Kanal) als kompakte Zeile.
* **Steuerung** (zuerst „Steuerung übernehmen“, es darf immer nur ein Gerät steuern):
  * **▶ Start / ■ Stopp**, **⟲ Reset** (Histogramm leeren), **⏮ Von vorn** (Datei neu beginnen),
  * **Frame-Intervall** (Aktualisierungsrate), **Wiedergabe-Tempo** („Echtzeit“, 0,1× bis 100×),
  * **Binbreite** und **Histogrammlänge**,
  * **Modus** Akkumulieren oder gleitendes Fenster (**Fenster (Frames)**), **Anzeige-Punkte**, **Datei wiederholen**,
  * **PTU-Datei**: z. B. `Demo_Synthetisch_T2_Einzelphotonen_gepulst_40MHz_4s.ptu` – Einzelphotonenquelle, in **g²**
    Peaks alle 25 ns, der **Mittelpeak bei 0 fehlt fast** (Antibunching); `Demo_Synthetisch_T2_Heralded_K0_g2h_8s.ptu` –
    K0 (violett) = Herald-Detektor am Sync-Eingang, K1/K2 = HBT, Peaks bei +12 ns (K1) und +15 ns (K2);
    `Demo_Synthetisch_T2_HOM_Dip_Scan_20s.ptu` – in der Ansicht **Zeit** sieht man den HOM-Dip nicht direkt in den
    Einzelraten (nur in den Koinzidenzen, Anzeige folgt in 0.2);
    `Demo_Synthetisch_T2_Photonenpaare_SPDC_cw_3s.ptu` – Photonenpaare, in **g²** ein scharfer Peak g²(0) ≈ 500
    zwischen K1/K2, K1/K4, K3/K2, K3/K4, flach (≈ 1) zwischen K1/K3 und K2/K4;
    `Demo_Synthetisch_T2_Photonentripel_cw_5s.ptu` – Photonentripel, in **g³** ein starker Peak g³(0,0) ≈ 7·10⁵.
  * **Referenzkanal (g²)**: Bezugskanal der Korrelation (τ = t(Kn) − t(Kref)) und bei T2 Start des Histogramms; er hat keine eigene Kurve.
* Unter **Datenmenge** sehen Sie Größe pro Bild und kB/s (typisch wenige kB pro Bild).
* Zweites Handy/Browser parallel: sieht dieselben Daten, kann aber erst steuern, wenn das erste die Steuerung abgibt (oder 5 Minuten lang nichts geändert hat).
* Optional „Zum Startbildschirm hinzufügen“ – dann startet die Seite wie eine App.

## 8. Beenden

* Im Fenster von `start_online.bat` **Enter** drücken – Server und Tunnel werden beendet, die Adresse ist sofort
  ungültig.
* Wurde das Fenster bereits geschlossen (z. B. mit dem X), laufen Server und Tunnel im Hintergrund weiter. Dann
  **`stop_online.bat`** doppelklicken.
* Kontrolle: Die trycloudflare-Adresse ist danach nicht mehr erreichbar.

## 9. Fehlerbehebung

| Problem | Ursache / Lösung |
|---|---|
| **SmartScreen** „Windows hat den PC geschützt“ | „Weitere Informationen“ → „Trotzdem ausführen“. Oder vor dem Entpacken ZIP → Eigenschaften → „Zulassen“. |
| **Virenscanner/Defender** meldet oder blockiert `cloudflared.exe` | cloudflared ist das offizielle Programm von Cloudflare (Quelle: github.com/cloudflare/cloudflared). Ggf. freigeben oder per `winget install --id Cloudflare.cloudflared` installieren. In Firmen-Umgebungen IT fragen. |
| Fenster schließt sich sofort / „Ausführung von Skripts ist deaktiviert“ | Die Batch-Datei startet PowerShell mit `-ExecutionPolicy Bypass`. Ist PowerShell per Gruppenrichtlinie gesperrt (Firmen-PC), bitte die IT fragen. |
| „Python-Umgebung nicht gefunden“ | Zuerst `install_windows.bat` ausführen. |
| `install_windows.bat`: „Python wurde nicht gefunden“ / „zu alt“ | Python 3.13 (64 Bit) von python.org installieren, „Add python.exe to PATH“ ankreuzen, neue Eingabeaufforderung/Explorer-Fenster öffnen. |
| Paketinstallation scheitert | Internetverbindung prüfen; hinter einem Firmen-Proxy vorher `set HTTPS_PROXY=http://proxy:port` in einer Eingabeaufforderung setzen und `install_windows.bat` von dort starten. |
| **Firewall-Abfrage** für Python/cloudflared | Für den Tunnel nicht nötig; „Abbrechen“ oder nur „Privat“ ist in Ordnung. |
| „Port 8765 ist bereits belegt“ | Läuft noch `start_server.bat` oder ein früherer Start? `stop_online.bat` ausführen bzw. das andere Fenster schließen. Anderer Port: in einer Eingabeaufforderung `powershell -ExecutionPolicy Bypass -File start_online.ps1 -Port 8780`. |
| „Download von cloudflared fehlgeschlagen“ | `winget install --id Cloudflare.cloudflared` oder die Datei `cloudflared-windows-amd64.exe` von <https://github.com/cloudflare/cloudflared/releases/latest> manuell als `exse-harp-gx-mobil\tools\cloudflared.exe` speichern. |
| WARNUNG „Tunnel meldet noch keine Verbindung“ / keine trycloudflare-Adresse | Das Netzwerk (oft **Firmen-/Uni-Netz**) blockiert die ausgehenden Tunnelverbindungen von cloudflared (Port **7844**, UDP/QUIC bzw. TCP). Versuch: Eingabeaufforderung im Ordner `exse-harp-gx-mobil` öffnen, `set HARP_TUNNEL_PROTOCOL=http2`, dann `start_online.bat`. Hilft das nicht: anderes Netz (z. B. Handy-Hotspot für den PC) oder IT fragen. Details in `logs\cloudflared.log`. |
| Handy: „Server nicht gefunden“ | 10–60 s warten und neu laden; Adresse genau prüfen (sie ändert sich bei **jedem** Start). |
| Handy: Anmeldeseite kommt immer wieder | Code falsch oder Server neu gestartet (neuer Code). Code aus dem aktuellen Fenster verwenden. Nach vielen Fehlversuchen kurz warten. |
| Handy: Seite lädt, aber keine Daten / „getrennt“ | Fenster am PC noch offen? Mobilfunk schwach? Die Seite verbindet sich automatisch neu. Server-Log: `logs\server-online.log`. |
| Die Adresse ist nach einem Neustart anders | Normal bei Quick Tunnels – jede Sitzung bekommt eine neue zufällige Adresse und einen neuen Code. |

## 10. Sicherheitshinweise

* **Zugangscode geheim halten** – nicht in Chats, E-Mails oder Screenshots weitergeben. Der QR-Code enthält
  den Code ebenfalls.
* **Nach dem Test beenden** (Enter bzw. `stop_online.bat`). Beim nächsten Start entstehen neue Adresse und neuer Code.
* **Quick Tunnels sind nur für Tests gedacht**: Cloudflare gibt keine Verfügbarkeitsgarantie; der Datenverkehr
  läuft verschlüsselt (HTTPS) bis Cloudflare und wird dort entschlüsselt und weitergeleitet. Für Dauerbetrieb oder
  vertrauliche Daten später ein VPN (z. B. WireGuard/Tailscale) oder einen benannten Cloudflare-Tunnel mit
  Zugangskontrolle verwenden.
* **Keine Portfreigabe im Router** einrichten – sie ist nicht nötig.
* Diese Version steuert nur eine **Simulation**. Bei Anschluss einer echten Harp (spätere Version) kommen zusätzliche
  Sicherheitsverriegelungen hinzu (z. B. kein Fernschalten eines Laser-Triggers).

## 11. Für Fortgeschrittene

* Festen Code verwenden: vor dem Start in der Eingabeaufforderung `set HARP_TOKEN=MEINCODE123`, dann
  `start_online.bat` aus dieser Eingabeaufforderung starten.
* Nur lokal ohne Tunnel, aber mit Code: `powershell -ExecutionPolicy Bypass -File start_online.ps1 -NoTunnel`.
* Betrieb im lokalen Netz ohne Internet: `start_server.bat` (siehe `README.md`, Abschnitt 4).
* Tests: `.venv\Scripts\python.exe -m pytest -q`
* Logdateien: `logs\server-online.log`, `logs\cloudflared.log`, `logs\commands.jsonl` (Steuerbefehle).
