"""Rechenkern-Vergleich Rust vs. Numba (vs. NumPy) je Demodatei und Thread-Zahl, offline wie im Live-Betrieb.

  python tools/bench_engines.py [--threads 1,2,4,8] [--engines rust,numba,gpu,auto] [--frame-s 0.15] [--only Name]
                                [--allow-cpu-gpu]

Engines: rust/numba/numpy erzwingen einen CPU-Kern (ohne GPU), gpu erzwingt die GPU für die Histogramme,
auto = Automatik wie im Betrieb (GPU nur, wenn sie für die Geometrie schneller ist). --allow-cpu-gpu lässt
Software-Adapter zu (lavapipe/WARP, nur zum Testen).

Je Lauf ein eigener Prozess (HARP_GX_ENGINE, HARP_GX_THREADS). Die Datei wird in Stücken zu je einer
Frame-Dauer Messzeit (Standard 150 ms) an GnEngine gegeben, wie der Worker es live tut (Kalibrierung und
Autogeometrie inklusive). Gemessen: Mtags/s = Marken / reine Rechenzeit, Rechenzeit je Frame (Median, Maximum),
Echtzeit-Reserve = Messzeit / Rechenzeit. Ergebnisse als JSON-Zeilen und Tabelle.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = r"""
import json, sys, time
import numpy as np
sys.path.insert(0, ROOT)
from harp.gx import kernels as K
from harp.gx.engine import GnConfig, GnEngine
from harp.ptu import read_all
from tools.generate_gx import SCENARIOS
name, frame_s = sys.argv[1], float(sys.argv[2])
sc = SCENARIOS[name]
hdr, e = read_all(str(ROOT) + "/data/" + sc["file"])
t = e.time.astype(np.int64) * round(hdr.global_resolution * 1e12); c = e.channel.astype(np.int16)
chans = [0, 1, 2] if name == "heralded_cw" else list(range(1, sc["nch"] + 1))
period = 1e12 / sc["sync"] if sc["sync"] else 0.0
K.warmup()
eng = GnEngine(GnConfig(channels=chans, period_ps=period, auto_geom=not period,
                        combo3=tuple(chans[:3]) if len(chans) >= 3 else (1, 2, 3)))
edges = np.searchsorted(t, np.arange(0, t[-1] + frame_s * 1e12, frame_s * 1e12))
lat = []
for a, b in zip(edges[:-1], edges[1:]):
    eng.feed(t[a:b], c[a:b])
    s = time.perf_counter(); eng.process(); lat.append(time.perf_counter() - s)
tot = sum(lat)
print(json.dumps({"file": sc["file"], "engine": K.active_backend(), "threads": K.n_threads(),
                  "gpu": (K.GPU_INFO or {}).get("name"), "choice": K.CHOOSER.summary(), "tags": int(t.size),
                  "T_s": float(t[-1] / 1e12), "proc_s": tot, "mtags": t.size / tot / 1e6,
                  "frame_ms_med": float(np.median(lat) * 1e3), "frame_ms_max": float(max(lat) * 1e3),
                  "realtime_x": float(t[-1] / 1e12 / tot), "win_ps": eng.cfg.win_ps, "n4": int(eng.cube4.sum())}))
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", default="1,2,4,8")
    ap.add_argument("--engines", default="rust,numba")
    ap.add_argument("--frame-s", type=float, default=0.15)
    ap.add_argument("--only")
    ap.add_argument("--json")
    ap.add_argument("--allow-cpu-gpu", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    from tools.generate_gx import SCENARIOS
    rows = []
    for name, sc in SCENARIOS.items():
        if a.only and a.only not in sc["file"] or not (ROOT / "data" / sc["file"]).exists():
            continue
        for eng in a.engines.split(","):
            for th in a.threads.split(","):
                env = dict(os.environ, HARP_GX_ENGINE="" if eng == "auto" else eng, HARP_GX_THREADS=th,
                           NUMBA_NUM_THREADS="8")
                if a.allow_cpu_gpu:
                    env["HARP_GX_GPU_ALLOW_CPU"] = "1"
                out = subprocess.run([sys.executable, "-c", f"ROOT={str(ROOT)!r}\n" + CHILD, name, str(a.frame_s)],
                                     capture_output=True, text=True, env=env, timeout=1800)
                if out.returncode:
                    print(out.stderr, file=sys.stderr); continue
                r = json.loads(out.stdout.strip().splitlines()[-1]); r["requested"] = (eng, int(th))
                rows.append(r)
                print(f"{sc['file'][19:60]:42s} {eng + '→' + r['engine']:11s} {r['threads']} Thr  {r['mtags']:7.1f} Mtags/s  "
                      f"Frame {r['frame_ms_med']:6.2f}/{r['frame_ms_max']:7.2f} ms  ×{r['realtime_x']:.1f} Echtzeit", flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
