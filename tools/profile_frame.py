"""Zeitaufteilung je Frame wie im Live-Betrieb (Server-Schleife und GX-Worker), offline auf einer Demodatei.

  python tools/profile_frame.py [Datei] [--frames N] [--speed 1] [--refresh-ms 150] [--corr-binning 9]

Server-Schleife (ein Prozess, „Server … ms“ in der Info-Zeile): read_frame (PTU dekodieren, Histogramm T2,
g²-Korrelation zum Referenzkanal, Zählraten, Ereignisse für GX), Akkumulation, Frame-JSON, Übergabe der Ereignisse
an den GX-Worker (Queue = Pickle). GX-Worker: GnEngine.process() aufgeschlüsselt nach Kernen, result() und
Kodierung des g³/g⁴-Frames. Ausgabe: Median/Mittel je Teil in ms.
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from harp.gx import kernels as K  # noqa: E402
from harp.gx import wire  # noqa: E402
from harp.gx.engine import GnConfig, GnEngine  # noqa: E402
from harp.histogram import Accumulator, rebin  # noqa: E402
from harp.sources.base import AcqParams  # noqa: E402
from harp.sources.pure_ptu import PurePythonPtuSource  # noqa: E402
import harp.sources.pure_ptu as P  # noqa: E402
import harp.histogram as H  # noqa: E402

T = defaultdict(list)


def timed(name, fn):
    def w(*a, **k):
        t0 = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            T[name].append(time.perf_counter() - t0)
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="Demo_Synthetisch_T2_Thermisch_cw_g2g3g4_3s.ptu")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--refresh-ms", type=int, default=150)
    ap.add_argument("--corr-binning", type=int, default=9)
    ap.add_argument("--no-gx", action="store_true")
    a = ap.parse_args()
    meas = a.refresh_ms / 1000 * a.speed
    # Teilfunktionen der Quelle instrumentieren
    P.histogram_t2 = timed("src: histogram_t2", P.histogram_t2)
    P.correlate = timed("src: g²-Korrelation (correlate)", P.correlate)
    P.counts_per_channel = timed("src: counts", P.counts_per_channel)
    src = PurePythonPtuSource()
    info = src.open(ROOT / "data" / a.file)
    src._fill_until = timed("src: PTU dekodieren", src._fill_until)
    src.configure(AcqParams(binning=0, hist_len_code=0, loop=True, ref_channel=1, corr_binning=a.corr_binning))
    acc, cacc = Accumulator(), Accumulator()
    K.warmup()
    eng = GnEngine(GnConfig(channels=list(range(1, info.num_channels + 1)), auto_geom=True))
    for name in ("g2_hist", "g3_hist", "g4_hist", "tile_sums", "split_channels"):
        setattr(K, name, timed(f"gx: {name}", getattr(K, name)))
    eng._calibrate = timed("gx: _calibrate", eng._calibrate)
    for i in range(a.frames):
        t0 = time.perf_counter()
        fr = timed("src: read_frame gesamt", src.read_frame)(meas)
        t1 = time.perf_counter()
        total = acc.add(fr)
        cacc.add_array(fr.corr, fr.meas_time_s)
        t2 = time.perf_counter()
        ct = cacc.total
        h = total[[0, 1, 2, 3][:total.shape[0]]]
        disp, f = rebin(h, 1024)
        cd, cf = rebin(ct[1:], 1024)
        import json
        txt = json.dumps({"hist": disp.astype(np.int64).tolist(), "corr": cd.astype(np.int64).tolist()})
        t3 = time.perf_counter()
        blob = pickle.dumps(("ev", fr.events[0], np.ascontiguousarray(fr.events[1], np.int16), 0.0), protocol=5)
        t4 = time.perf_counter()
        T["srv: Akkumulation"].append(t2 - t1)
        T["srv: Frame-JSON"].append(t3 - t2)
        T["srv: Pickle für GX-Queue"].append(t4 - t3)
        T["SERVER gesamt (≈ „Server … ms“)"].append(t4 - t0)
        if a.no_gx:
            continue
        g0 = time.perf_counter()
        if fr.wrapped:   # wie der Server: Zeitachse springt zurück → Puffer leeren
            eng.reset(True)
        eng.feed(fr.events[0], fr.events[1])
        g1 = time.perf_counter()
        eng.process()
        g2 = time.perf_counter()
        r = eng.result()
        g3 = time.perf_counter()
        wire.encode({"x": 1}, {"map3": r["map3"]}); wire.encode({"x": 1}, {"cube4": r["cube4"]})
        g4 = time.perf_counter()
        T["gx: feed"].append(g1 - g0); T["gx: process"].append(g2 - g1); T["gx: result (Normierung)"].append(g3 - g2)
        T["gx: wire encode g³+g⁴"].append(g4 - g3)
        T["GX gesamt"].append(g4 - g0)
    n_ev = len(fr.events[0])
    print(f"{a.file}: {a.frames} Frames à {meas * 1e3:.0f} ms Messzeit, ~{n_ev} Ereignisse/Frame, "
          f"GX: Fenster {eng.cfg.win_ps} ps, Bereich {eng.cfg.range_ps} ps, {K.BACKEND} {K.n_threads()} Thr")
    skip = 3
    for k, v in T.items():
        v = np.array(v[skip:] if len(v) > skip + 2 else v) * 1e3
        per = len(v) / max(1, a.frames - skip)
        print(f"  {k:40s} median {np.median(v):8.2f} ms  mittel {v.mean():8.2f} ms  ({per:.1f}×/Frame)")


if __name__ == "__main__":
    main()
