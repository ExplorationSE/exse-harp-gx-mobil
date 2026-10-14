"""Rechenkerne für Korrelationen höherer Ordnung auf sortierten Zeitmarken (int64, ps).

Gleitfenster: Für jede Start-Marke t (Kanal a, Indizes i0…i1) werden alle Marken der anderen Kanäle mit
t − W ≤ t_x < t + W besucht; Bin = (t_x − t + W) // BW mit NB·BW = 2W. Die Start-Marken werden in P Blöcke
geteilt (je Block eigenes Histogramm, parallel über alle Kerne), danach summiert.

Mit Numba (JIT, parallel, ohne GIL); fehlt Numba, rechnen gleichwertige NumPy-Varianten (langsamer).
Beide liefern bit-identische Histogramme (Test: tests/test_gx_engine.py).
"""
from __future__ import annotations

import os

import numpy as np

try:  # pragma: no cover - abhängig von der Installation
    if os.environ.get("HARP_GX_NO_NUMBA"):
        raise ImportError("per Umgebungsvariable abgeschaltet")
    import numba
    from numba import njit, prange
    HAVE_NUMBA = True
except Exception:  # noqa: BLE001
    HAVE_NUMBA = False

BACKEND = "numba" if HAVE_NUMBA else "numpy"


def n_threads() -> int:
    if HAVE_NUMBA:
        return int(numba.get_num_threads())
    return 1


# ---------------------------------------------------------------------------- NumPy (Fallback/Referenz)
def _ranges(ts, tx, W):
    return np.searchsorted(tx, ts - W, "left"), np.searchsorted(tx, ts + W, "left")


def g2_np(ta, tb, i0, i1, W, BW, NB):
    ts = ta[i0:i1]
    h = np.zeros(NB, np.int64)
    lo, hi = _ranges(ts, tb, W)
    m = int((hi - lo).max()) if ts.size else 0
    for k in range(m):
        s = lo + k < hi
        h += np.bincount((tb[lo[s] + k] - ts[s] + W) // BW, minlength=NB)[:NB]
    return h


def g3_np(ta, tb, tc, i0, i1, W, BW, NB):
    ts = ta[i0:i1]
    h = np.zeros(NB * NB, np.int64)
    lb, hb = _ranges(ts, tb, W)
    lc, hc = _ranges(ts, tc, W)
    mb = int((hb - lb).max()) if ts.size else 0
    mc = int((hc - lc).max()) if ts.size else 0
    for kb in range(mb):
        sb = lb + kb < hb
        for kc in range(mc):
            s = sb & (lc + kc < hc)
            if not s.any():
                continue
            t0 = ts[s]
            x = (tb[lb[s] + kb] - t0 + W) // BW
            y = (tc[lc[s] + kc] - t0 + W) // BW
            h += np.bincount(x * NB + y, minlength=NB * NB)[:NB * NB]
    return h.reshape(NB, NB)


def g4_np(ta, tb, tc, td, i0, i1, W, BW, NB):
    ts = ta[i0:i1]
    h = np.zeros(NB ** 3, np.int64)
    lb, hb = _ranges(ts, tb, W)
    lc, hc = _ranges(ts, tc, W)
    ld, hd = _ranges(ts, td, W)
    mb, mc, md = [(int((h_ - l_).max()) if ts.size else 0) for l_, h_ in ((lb, hb), (lc, hc), (ld, hd))]
    for kb in range(mb):
        sb = lb + kb < hb
        for kc in range(mc):
            sc = sb & (lc + kc < hc)
            if not sc.any():
                continue
            for kd in range(md):
                s = sc & (ld + kd < hd)
                if not s.any():
                    continue
                t0 = ts[s]
                x = (tb[lb[s] + kb] - t0 + W) // BW
                y = (tc[lc[s] + kc] - t0 + W) // BW
                z = (td[ld[s] + kd] - t0 + W) // BW
                h += np.bincount((x * NB + y) * NB + z, minlength=NB ** 3)[:NB ** 3]
    return h.reshape(NB, NB, NB)


# ---------------------------------------------------------------------------- Numba
if HAVE_NUMBA:  # pragma: no branch
    @njit(cache=True, nogil=True)
    def _lower(t, x):
        lo, hi = 0, t.size
        while lo < hi:
            mid = (lo + hi) >> 1
            if t[mid] < x:
                lo = mid + 1
            else:
                hi = mid
        return lo

    @njit(cache=True, nogil=True, parallel=True)
    def _g2_nb(ta, tb, i0, i1, W, BW, NB, P):
        out = np.zeros((P, NB), np.int64)
        n = i1 - i0
        for p in prange(P):
            s0 = i0 + n * p // P
            s1 = i0 + n * (p + 1) // P
            if s1 <= s0:
                continue
            jb = _lower(tb, ta[s0] - W)
            for i in range(s0, s1):
                t = ta[i]
                while jb < tb.size and tb[jb] < t - W:
                    jb += 1
                j = jb
                while j < tb.size and tb[j] < t + W:
                    out[p, (tb[j] - t + W) // BW] += 1
                    j += 1
        return out.sum(axis=0)

    @njit(cache=True, nogil=True, parallel=True)
    def _g3_nb(ta, tb, tc, i0, i1, W, BW, NB, P):
        out = np.zeros((P, NB, NB), np.int64)
        n = i1 - i0
        for p in prange(P):
            s0 = i0 + n * p // P
            s1 = i0 + n * (p + 1) // P
            if s1 <= s0:
                continue
            jb = _lower(tb, ta[s0] - W)
            jc = _lower(tc, ta[s0] - W)
            for i in range(s0, s1):
                t = ta[i]
                while jb < tb.size and tb[jb] < t - W:
                    jb += 1
                while jc < tc.size and tc[jc] < t - W:
                    jc += 1
                j = jb
                while j < tb.size and tb[j] < t + W:
                    x = (tb[j] - t + W) // BW
                    k = jc
                    while k < tc.size and tc[k] < t + W:
                        out[p, x, (tc[k] - t + W) // BW] += 1
                        k += 1
                    j += 1
        return out.sum(axis=0)

    @njit(cache=True, nogil=True, parallel=True)
    def _g4_nb(ta, tb, tc, td, i0, i1, W, BW, NB, P):
        out = np.zeros((P, NB, NB, NB), np.int64)
        n = i1 - i0
        for p in prange(P):
            s0 = i0 + n * p // P
            s1 = i0 + n * (p + 1) // P
            if s1 <= s0:
                continue
            jb = _lower(tb, ta[s0] - W)
            jc = _lower(tc, ta[s0] - W)
            jd = _lower(td, ta[s0] - W)
            for i in range(s0, s1):
                t = ta[i]
                while jb < tb.size and tb[jb] < t - W:
                    jb += 1
                while jc < tc.size and tc[jc] < t - W:
                    jc += 1
                while jd < td.size and td[jd] < t - W:
                    jd += 1
                j = jb
                while j < tb.size and tb[j] < t + W:
                    x = (tb[j] - t + W) // BW
                    k = jc
                    while k < tc.size and tc[k] < t + W:
                        y = (tc[k] - t + W) // BW
                        m = jd
                        while m < td.size and td[m] < t + W:
                            out[p, x, y, (td[m] - t + W) // BW] += 1
                            m += 1
                        k += 1
                    j += 1
        return out.sum(axis=0)


if HAVE_NUMBA:
    @njit(cache=True, nogil=True)
    def _wc_nb(ts, tx, d, w):
        out = np.empty(ts.size, np.float64)
        lo = _lower(tx, ts[0] + d - w // 2) if ts.size else 0
        hi = lo
        for i in range(ts.size):
            a = ts[i] + d - w // 2
            b = ts[i] + d + w - w // 2
            while lo < tx.size and tx[lo] < a:
                lo += 1
            if hi < lo:
                hi = lo
            while hi < tx.size and tx[hi] < b:
                hi += 1
            out[i] = hi - lo
        return out


def window_counts(ts, tx, d, w, backend=None):
    """Anzahl Marken von tx in [t+d−w/2, t+d+w/2) je Start t (ts sortiert). Linearer Zwei-Zeiger-Lauf."""
    d = int(round(d)); w = int(w)
    if (backend or BACKEND) == "numba" and HAVE_NUMBA:
        return _wc_nb(ts, tx, d, w)
    lo = np.searchsorted(tx, ts + d - w // 2, "left")
    hi = np.searchsorted(tx, ts + d + w - w // 2, "left")
    return (hi - lo).astype(np.float64)


def _P(n):
    return max(1, min(n_threads() * 2, n // 2048 + 1))


def g2_hist(ta, tb, i0, i1, W, BW, NB, backend=None):
    if (backend or BACKEND) == "numba" and HAVE_NUMBA:
        return _g2_nb(ta, tb, i0, i1, W, BW, NB, _P(i1 - i0))
    return g2_np(ta, tb, i0, i1, W, BW, NB)


def g3_hist(ta, tb, tc, i0, i1, W, BW, NB, backend=None):
    if (backend or BACKEND) == "numba" and HAVE_NUMBA:
        return _g3_nb(ta, tb, tc, i0, i1, W, BW, NB, _P(i1 - i0))
    return g3_np(ta, tb, tc, i0, i1, W, BW, NB)


def g4_hist(ta, tb, tc, td, i0, i1, W, BW, NB, backend=None):
    if (backend or BACKEND) == "numba" and HAVE_NUMBA:
        return _g4_nb(ta, tb, tc, td, i0, i1, W, BW, NB, _P(i1 - i0))
    return g4_np(ta, tb, tc, td, i0, i1, W, BW, NB)


def warmup() -> float:
    """JIT-Übersetzung vorab (beim ersten Start einige Sekunden, danach aus dem Cache)."""
    import time
    t0 = time.perf_counter()
    a = np.arange(0, 100_000, 7, dtype=np.int64)
    g2_hist(a, a, 0, a.size, 64, 2, 64)
    g3_hist(a, a, a, 0, a.size, 64, 4, 32)
    g4_hist(a, a, a, a, 0, a.size, 64, 8, 16)
    window_counts(a, a, 0, 10)
    return time.perf_counter() - t0
