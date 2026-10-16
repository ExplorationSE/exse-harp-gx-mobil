"""GPU (wgpu) gegen Rust-CPU: reine Histogramm-Kerne g²/g³/g⁴ auf synthetischen Poisson-Zeitmarken.

  python tools/bench_gpu.py [--allow-cpu] [--threads 8] [--json out.json]

Je Fall werden dieselben Felder mit dem Rust-CPU-Kern (rayon, --threads) und der GPU gerechnet; gemessen wird die
Wandzeit je Aufruf inkl. Übertragung zur GPU und zurück (Median aus 5 nach einem Aufwärmlauf). Ergebnis: Mtags/s
(Start-Marken je s), Faktor GPU/CPU, Bitgleichheit. --allow-cpu lässt Software-Adapter (lavapipe/WARP) zu –
deren Zahlen sagen nichts über eine echte GPU aus.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (Name, Zählrate je Kanal [cps], Zeitmarken je Kanal, W [ps], NB)
CASES = [
    ("g2  2,5 Mcps  ±50 ns  1000 Bins", 2.5e6, 1_000_000, 50_000, 1000, 2),
    ("g3  2,5 Mcps  ±25 ns  129²", 2.5e6, 1_000_000, 25_000, 129, 3),
    ("g4  2,5 Mcps  ±25 ns  33³", 2.5e6, 1_000_000, 25_000, 33, 4),
    ("g3  20 Mcps   ±25 ns  129²", 2.0e7, 1_000_000, 25_000, 129, 3),
    ("g4  20 Mcps   ±25 ns  33³", 2.0e7, 1_000_000, 25_000, 33, 4),
    ("g3  2,5 Mcps  ±1 µs   129² (R·T≈5)", 2.5e6, 300_000, 1_000_000, 129, 3),
    ("g4  2,5 Mcps  ±250 ns 33³ (R·T≈1,25)", 2.5e6, 200_000, 250_000, 33, 4),
    ("g4  thermisch-live 0,15 s Frame (1 Mcps, ±25 ns)", 1.0e6, 150_000, 25_000, 33, 4),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-cpu", action="store_true")
    ap.add_argument("--threads", default="")
    ap.add_argument("--json")
    ap.add_argument("--reps", type=int, default=5)
    a = ap.parse_args()
    if a.allow_cpu:
        os.environ["HARP_GX_GPU_ALLOW_CPU"] = "1"
    if a.threads:
        os.environ["HARP_GX_THREADS"] = a.threads
    sys.path.insert(0, str(ROOT))
    import numpy as np
    from harp.gx import kernels as K
    info = K.gpu_setup()
    print("CPU:", K.BACKEND, K.n_threads(), "Threads ·", "GPU:", info or K.GPU_STATE, flush=True)
    rows = []
    rng = np.random.default_rng(1)
    for name, rate, n, W, NB, order in CASES:
        span = int(n / rate * 1e12)
        ts = [np.sort(rng.integers(0, span, n)).astype(np.int64) for _ in range(order)]
        BW = -(-2 * W // NB)
        f = getattr(K, f"g{order}_hist")
        res = {}
        for be in (["rust", "gpu"] if info else ["rust"]):
            f(*ts, 0, n, W, BW, NB, be)
            dts = []
            for _ in range(a.reps):
                t0 = time.perf_counter(); h = f(*ts, 0, n, W, BW, NB, be); dts.append(time.perf_counter() - t0)
            res[be] = (float(np.median(dts)), h)
            if be == "gpu":
                prof = K._rs.gpu_profile()
        r = {"case": name, "tags": n, "cpu_s": res["rust"][0], "cpu_mtags": n / res["rust"][0] / 1e6,
             "tuples": int(res["rust"][1].sum())}
        if "gpu" in res:
            r.update(gpu_s=res["gpu"][0], gpu_mtags=n / res["gpu"][0] / 1e6, gpu_over_cpu=res["rust"][0] / res["gpu"][0],
                     equal=bool(np.array_equal(res["gpu"][1], res["rust"][1])), gpu_prep_s=prof["prep_s"],
                     gpu_wait_s=prof["wait_s"], dispatches=prof["dispatches"])
        rows.append(r)
        print(f"{name:48s} CPU {r['cpu_mtags']:8.1f} Mtags/s" + (
            f"  GPU {r['gpu_mtags']:8.1f} Mtags/s  ×{r['gpu_over_cpu']:.2f}  {'gleich' if r['equal'] else 'UNGLEICH'}"
            f"  [Vorb. {r['gpu_prep_s'] * 1e3:.1f} ms, GPU {r['gpu_wait_s'] * 1e3:.1f} ms, {r['dispatches']} Disp.]"
            if "gpu_s" in r else "") + f"  ({r['tuples']:.3g} Tupel)", flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps({"gpu": info, "threads": K.n_threads(), "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
