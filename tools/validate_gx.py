"""Prüft die synthetischen GX-Demodateien: berechnet g⁽ⁿ⁾ mit harp.gn und vergleicht mit den Sollwerten.

  python tools/validate_gx.py            # alle Dateien in data/
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harp.gn import gn_cw, gn_pulsed, split_channels, window_counts  # noqa: E402
from harp.ptu import read_all  # noqa: E402
from tools.generate_gx import OFFS, SCENARIOS, hom_visibility  # noqa: E402


def load(path, offsets=OFFS):
    hdr, ev = read_all(path)
    t = ev.time.astype(np.int64) * round(hdr.global_resolution * 1e12)
    c = ev.channel.astype(np.int64)
    times = split_channels(t, c)
    for k in times:   # Kabel-Laufzeiten korrigieren (wie später der Kalibrier-Assistent)
        times[k] = times[k] - offsets[k]
    return times, hdr.acquisition_time_s * 1e12


def evaluate(name: str, path) -> dict:
    sc = SCENARIOS[name]; ex = sc["expected"]; w = ex["w_ps"]
    if name in ("thermal_cw", "laser_cw", "single_cw"):
        tm, T = load(path)
        r = {"g2": gn_cw(tm, [1, 2], w, T)[0], "g3": gn_cw(tm, [1, 2, 3], w, T)[0]}
        g4, n4 = gn_cw(tm, [1, 2, 3, 4], w, T); r["g4"] = g4; r["n4"] = n4
        return r
    if name in ("pairs_cw", "triplets_cw"):
        tm, T = load(path)
        combos = {"g2": [1, 2], "g2_13": [1, 3], "g2_24": [2, 4], "g2_34": [3, 4], "g3": [1, 2, 3], "g3_134": [1, 3, 4],
                  "g4": [1, 2, 3, 4]}
        r = {}
        for k, c in combos.items():
            r[k], n = gn_cw(tm, c, w, T)
            r["n" + k[1:]] = n
        return r
    if name in ("thermal_pulsed", "single_pulsed"):
        tm, T = load(path)
        P = ex["period_ps"]
        r = {"g2": gn_pulsed(tm, [1, 2], w, P)[0], "g3": gn_pulsed(tm, [1, 2, 3], w, P)[0]}
        g4, n4 = gn_pulsed(tm, [1, 2, 3, 4], w, P); r["g4"] = g4; r["n4"] = n4
        return r
    if name == "heralded_cw":
        tm, T = load(path, offsets=np.zeros(5))
        d1, d2 = ex["delays_ps"]
        h = tm[0]
        n1 = window_counts(h, tm[1], d1, w); n2 = window_counts(h, tm[2], d2, w)
        g2h = h.size * float((n1 * n2).sum()) / (float(n1.sum()) * float(n2.sum()))
        g2u = gn_cw(tm, [1, 2], 200_000, T, delays_ps=[d2 - d1 + 300_000])[0]   # ohne Herald, abseits, breites Fenster
        g2u0 = gn_cw(tm, [1, 2], 200_000, T, delays_ps=[d2 - d1])[0]
        return {"g2h": g2h, "n_triple": float((n1 * n2).sum()), "g2_unheralded": g2u0, "g2_flat": g2u}
    if name == "hom_scan":
        tm, T = load(path, offsets=np.zeros(5))
        a = tm[1]
        n = window_counts(a, tm[2], ex["delay_ps"], w)
        frac = a / T
        bins = np.linspace(0, 1, 21)
        idx = np.clip(np.digitize(frac, bins) - 1, 0, 19)
        coinc = np.bincount(idx, weights=n, minlength=20)
        ref = np.mean(coinc[[0, 1, 18, 19]] / (1 - hom_visibility((bins[[0, 1, 18, 19]] + 0.025))))
        rel = coinc / ref
        expv = 1 - np.array([hom_visibility(np.linspace(b, b + 0.05, 51)).mean() for b in bins[:-1]])
        return {"dip_min": float(rel.min()), "dip_expected": float(expv.min()), "max_dev": float(np.abs(rel - expv).max())}
    raise KeyError(name)


def main():
    for name, sc in SCENARIOS.items():
        p = Path("data") / sc["file"]
        if not p.exists():
            continue
        r = evaluate(name, p)
        print(f"{sc['file']}\n   gemessen: " + ", ".join(f"{k}={v:.4g}" for k, v in r.items())
              + "\n   erwartet: " + ", ".join(f"{k}={v}" for k, v in sc["expected"].items() if k not in ("note",)))


if __name__ == "__main__":
    main()
