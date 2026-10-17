"""Latenz der g³/g⁴-Frames messen: echter Server (in-process), WebSocket-Client in der Ansicht g³/g⁴.

  python tools/latency_gx.py [Datei] [--view g4] [--seconds 20] [--refresh-ms 150] [--clients 1]

Server, GX-Worker und Client laufen auf derselben Maschine; alle Zeitpunkte stammen aus time.monotonic()
(systemweit, auch im Worker-Prozess vergleichbar). Je empfangenem g³/g⁴-Frame:
  Frame-Ende   – Ende der Messzeit des neuesten enthaltenen Frames (Server liest ihn aus der Quelle)
  Hinweg       – Frame-Ende → Block im Worker (Server-Rechnung des Frames, Queue/Pickle zum Worker)
  GX-Rechnung  – Block im Worker → gerechnet (GnEngine.process)
  Ergebnis     – gerechnet → Ergebnis fertig (Normierung, Kodierung der Karten, ggf. Mindestabstand)
  Rückweg      – Ergebnis fertig → im Server angekommen (Queue/IPC, Abholen)
  Warten       – im Server angekommen → kodiert/abgeschickt (Sendetakt)
  Senden       – abgeschickt → beim Client angekommen (Sende-Warteschlange, WebSocket)
  Gesamt       – Frame-Ende → beim Client
Fehlen dem Server die Zeitstempel (Versionen vor 1.3.0-dev r2), werden sie per Monkeypatch nachgerüstet;
„Rechnung“ und „Rückweg“ sind dann nur zusammen messbar.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import harp.server as S  # noqa: E402
from harp.config import Config  # noqa: E402
from harp.gx import runner as R  # noqa: E402


def patch_legacy():
    """Für ältere Server: Zeitstempel über Monkeypatches einsammeln."""
    cur = {}
    orig_poll = R.GnRunner.poll

    def poll(self):
        new = orig_poll(self)
        if new is not None:
            new.setdefault("t_srv", time.monotonic())
        return new
    R.GnRunner.poll = poll
    orig_frame = S.HarpService.gn_frame

    def gn_frame(self, view):
        r = self.gn_last or {}
        cur.update(stamp=r.get("stamp"), t_srv=r.get("t_srv"))
        return orig_frame(self, view)
    S.HarpService.gn_frame = gn_frame
    orig_enc = S.gxwire.encode

    def enc(header, arrays):
        header = dict(header, t_frame=cur.get("stamp"), t_srv=cur.get("t_srv"), t_send=time.monotonic())
        return orig_enc(header, arrays)
    S.gxwire.encode = enc


def client(c, view, seconds, out, frames, out_txt):
    with c.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "view", "v": view}))
        t_end = time.monotonic() + seconds
        while time.monotonic() < t_end:
            m = ws.receive()
            now = time.monotonic()
            if m.get("bytes"):
                b = m["bytes"]
                n = int.from_bytes(b[4:8], "little")
                h = json.loads(b[8:8 + n])
                out.append((now, len(b), h))
            elif (m.get("text") or "").startswith('{"type":"frame"'):
                frames.append(now)
                out_txt.append(len(m["text"].encode()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="Demo_Synthetisch_T2_Thermisch_cw_g2g3g4_3s.ptu")
    ap.add_argument("--view", default="g4")
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--refresh-ms", type=int, default=150)
    ap.add_argument("--clients", type=int, default=1)
    ap.add_argument("--skip-s", type=float, default=4.0, help="Anlaufzeit (Kalibrierung, Geometrie) verwerfen")
    a = ap.parse_args()
    if not hasattr(R.GnRunner, "t_stamps"):
        patch_legacy()
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(port=0, data_dir=ROOT / "data", default_file=a.file, log_dir=tmp,
                 defaults={"refresh_ms": a.refresh_ms, "speed": 1.0})
    outs = [[] for _ in range(a.clients)]
    frames = [[] for _ in range(a.clients)]
    txt = [[] for _ in range(a.clients)]
    with TestClient(S.create_app(cfg)) as c:
        th = [threading.Thread(target=client, args=(c, a.view, a.seconds, outs[i], frames[i], txt[i]))
              for i in range(a.clients)]
        t0 = time.monotonic()
        for t in th:
            t.start()
        for t in th:
            t.join()
        rows = []
        for (now, nb, h) in outs[0]:
            if now - t0 < a.skip_s or h.get("t_frame") is None or not h.get("arrays"):
                continue
            tf, ts, tx = h["t_frame"], h.get("t_srv"), h["t_send"]
            tr = h.get("t_res")
            rows.append((now, nb, tf, tr, ts, tx, h.get("latency_ms"), h.get("t_in"), h.get("t_proc")))
        if not rows:
            print("keine g³/g⁴-Frames empfangen")
            os._exit(1)
        A = np.array([[np.nan if x is None else x for x in r] for r in rows], float)
        now, nb, tf, tr, ts, tx, lat, ti, tp = A.T
        dt = np.diff(now)
        fr = np.diff(np.array(frames[0]))

        def st(x):
            x = x[np.isfinite(x)] * 1e3
            return f"median {np.median(x):7.1f}  p90 {np.percentile(x, 90):7.1f}  max {x.max():7.1f} ms" if x.size else "–"
        print(f"{a.file} · Ansicht {a.view} · {a.clients} Client(s) · Refresh {a.refresh_ms} ms · "
              f"{len(rows)} GX-Frames in {now[-1] - now[0]:.1f} s")
        print(f"  Frame-Abstand Histogramm        {st(fr)}  ({1 / fr.mean():.2f} fps)")
        print(f"  Abstand g³/g⁴-Frames            {st(dt)}  ({1 / dt.mean():.2f} Hz)")
        if np.isfinite(ti).any():
            print(f"  Hinweg (Frame-Ende → Worker)    {st(ti - tf)}")
            print(f"  GX-Rechnung (process)           {st(tp - ti)}")
            print(f"  Ergebnis (result + Kodierung)   {st(tr - tp)}")
            print(f"  Rückweg (Ergebnis → Server)     {st(ts - tr)}")
        elif np.isfinite(tr).any():
            print(f"  Rechnung (Frame-Ende → Ergebnis) {st(tr - tf)}")
            print(f"  Rückweg (Ergebnis → Server)     {st(ts - tr)}")
        else:
            print(f"  Rechnung + Rückweg              {st(ts - tf)}")
        print(f"  Warten (Server → abgeschickt)   {st(tx - ts)}")
        print(f"  Senden (→ Client)               {st(now - tx)}")
        print(f"  GESAMT Frame-Ende → Client       {st(now - tf)}")
        print(f"  Info-Zeile „Latenz“             {st(lat / 1e3)}")
        print(f"  Größe {np.median(nb) / 1e3:.1f} kB/Frame · {nb.sum() / (now[-1] - now[0]) / 1e3:.1f} kB/s je Client")
        tb = np.array(txt[0][len(txt[0]) // 4:], float)
        dur = frames[0][-1] - frames[0][len(frames[0]) // 4]
        print(f"  Histogramm-Frames {np.median(tb) / 1e3:.1f} kB/Frame · {tb.sum() / dur / 1e3:.1f} kB/s je Client")
        sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
