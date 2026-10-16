"""Rechenkerne für Korrelationen höherer Ordnung auf sortierten Zeitmarken (int64, ps).

Gleitfenster: Für jede Start-Marke t (Kanal a, Indizes i0…i1) werden alle Marken der anderen Kanäle mit
t − W ≤ t_x < t + W besucht; Bin = (t_x − t + W) // BW mit NB·BW = 2W. Die Start-Marken werden in P Blöcke
geteilt (je Block eigenes Histogramm, parallel über alle Kerne), danach summiert.

Rechenkerne in der Reihenfolge Rust > Numba > NumPy (automatischer Rückfall, wenn einer fehlt oder versagt):
  * Rust (`harp_gx_core`, PyO3 + rayon, alle Kerne, ohne GIL) – optionales Paket aus `rust/harp_gx_core`,
  * Numba (JIT, parallel, ohne GIL),
  * NumPy (gleichwertig, langsamer).
Alle drei liefern bit-identische Histogramme (Tests: tests/test_gx_engine.py, tests/test_gx_rust.py).

Umgebungsvariablen: HARP_GX_ENGINE = rust | numba | numpy erzwingt einen Kern (fehlt er, gilt die
Reihenfolge oben, mit Hinweis in FALLBACK_NOTE); HARP_GX_THREADS = n legt die Thread-Zahl fest;
HARP_GX_NO_NUMBA = 1 schaltet Numba ab (wie bisher).
"""
from __future__ import annotations

import logging
import os

import numpy as np

log = logging.getLogger("harp.gx")
ENGINES = ("rust", "numba", "numpy")
_FORCE = (os.environ.get("HARP_GX_ENGINE") or "").strip().lower() or None
_THREADS = int(os.environ.get("HARP_GX_THREADS") or 0)

try:  # pragma: no cover - abhängig von der Installation
    if os.environ.get("HARP_GX_NO_NUMBA") or _FORCE == "numpy":
        raise ImportError("per Umgebungsvariable abgeschaltet")
    import numba
    from numba import njit, prange
    HAVE_NUMBA = True
    if _THREADS > 0:
        numba.set_num_threads(min(_THREADS, numba.config.NUMBA_NUM_THREADS))
except Exception:  # noqa: BLE001
    HAVE_NUMBA = False

try:  # pragma: no cover - abhängig von der Installation
    if os.environ.get("HARP_GX_NO_RUST") or _FORCE in ("numba", "numpy"):
        raise ImportError("per Umgebungsvariable abgeschaltet")
    import harp_gx_core as _rs
    _rs.init_threads(_THREADS)
    HAVE_RUST = True
except Exception:  # noqa: BLE001
    _rs = None
    HAVE_RUST = False

AVAILABLE = tuple(e for e, ok in zip(ENGINES, (HAVE_RUST, HAVE_NUMBA, True)) if ok)
FALLBACK_NOTE = ""
if _FORCE and _FORCE not in ENGINES:
    FALLBACK_NOTE = f"HARP_GX_ENGINE={_FORCE} unbekannt – automatische Wahl"
    _FORCE = None
if _FORCE and _FORCE not in AVAILABLE:
    FALLBACK_NOTE = f"Rechenkern {_FORCE} nicht verfügbar – Rückfall auf {AVAILABLE[0]}"
    log.warning(FALLBACK_NOTE)
BACKEND = _FORCE if _FORCE in AVAILABLE else AVAILABLE[0]


def n_threads(backend=None) -> int:
    b = backend or BACKEND
    if b == "rust" and HAVE_RUST:
        return int(_rs.n_threads())
    if b == "numba" and HAVE_NUMBA:
        return int(numba.get_num_threads())
    return 1


def _rust_failed(e: Exception) -> None:
    """Laufzeitfehler im Rust-Kern: auf den nächsten Kern zurückfallen (einmalig, mit Hinweis)."""
    global BACKEND, HAVE_RUST, FALLBACK_NOTE, AVAILABLE
    HAVE_RUST = False
    AVAILABLE = tuple(x for x in AVAILABLE if x != "rust")
    if BACKEND == "rust":
        BACKEND = AVAILABLE[0]
    FALLBACK_NOTE = f"Rust-Kern-Fehler ({e}) – Rückfall auf {BACKEND}"
    log.warning(FALLBACK_NOTE)


def _use(backend, name):
    b = backend or BACKEND
    if b == "rust" and not HAVE_RUST:
        b = BACKEND if BACKEND != "rust" else ("numba" if HAVE_NUMBA else "numpy")
    if b == "numba" and not HAVE_NUMBA:
        b = "numpy"
    return b


def _c64(a):
    return np.ascontiguousarray(a, dtype=np.int64)


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
    b = _use(backend, "wc")
    if b == "rust":
        try:
            out = np.empty(len(ts), np.float64)
            _rs.window_counts(_c64(ts), _c64(tx), d, w, out)
            return out
        except Exception as e:  # noqa: BLE001
            _rust_failed(e); b = _use(None, "wc")
    if b == "numba":
        return _wc_nb(ts, tx, d, w)
    lo = np.searchsorted(tx, ts + d - w // 2, "left")
    hi = np.searchsorted(tx, ts + d + w - w // 2, "left")
    return (hi - lo).astype(np.float64)


def _P(n):
    return max(1, min(n_threads("numba") * 2, n // 2048 + 1))


def g2_hist(ta, tb, i0, i1, W, BW, NB, backend=None):
    b = _use(backend, "g2")
    if b == "rust":
        try:
            out = np.zeros(NB, np.int64)
            _rs.g2_hist(_c64(ta), _c64(tb), int(i0), int(i1), int(W), int(BW), int(NB), out)
            return out
        except Exception as e:  # noqa: BLE001
            _rust_failed(e); b = _use(None, "g2")
    if b == "numba":
        return _g2_nb(ta, tb, i0, i1, W, BW, NB, _P(i1 - i0))
    return g2_np(ta, tb, i0, i1, W, BW, NB)


def g3_hist(ta, tb, tc, i0, i1, W, BW, NB, backend=None):
    b = _use(backend, "g3")
    if b == "rust":
        try:
            out = np.zeros(NB * NB, np.int64)
            _rs.g3_hist(_c64(ta), _c64(tb), _c64(tc), int(i0), int(i1), int(W), int(BW), int(NB), out)
            return out.reshape(NB, NB)
        except Exception as e:  # noqa: BLE001
            _rust_failed(e); b = _use(None, "g3")
    if b == "numba":
        return _g3_nb(ta, tb, tc, i0, i1, W, BW, NB, _P(i1 - i0))
    return g3_np(ta, tb, tc, i0, i1, W, BW, NB)


def g4_hist(ta, tb, tc, td, i0, i1, W, BW, NB, backend=None):
    b = _use(backend, "g4")
    if b == "rust":
        try:
            out = np.zeros(NB ** 3, np.int64)
            _rs.g4_hist(_c64(ta), _c64(tb), _c64(tc), _c64(td), int(i0), int(i1), int(W), int(BW), int(NB), out)
            return out.reshape(NB, NB, NB)
        except Exception as e:  # noqa: BLE001
            _rust_failed(e); b = _use(None, "g4")
    if b == "numba":
        return _g4_nb(ta, tb, tc, td, i0, i1, W, BW, NB, _P(i1 - i0))
    return g4_np(ta, tb, tc, td, i0, i1, W, BW, NB)


def split_channels(t, ch, chans, backend=None) -> dict:
    """{kanal: Zeitmarken} für die gewünschten Kanäle (Reihenfolge erhalten), leere Kanäle fehlen."""
    t = np.ascontiguousarray(t, np.int64); ch = np.asarray(ch)
    if not t.size:
        return {}
    chans = [int(k) for k in chans]
    if ch.min() < 0:
        return {k: x for k in chans if (x := t[ch == k]).size}
    cnt = np.bincount(ch.astype(np.intp, copy=False))
    present = [k for k in chans if 0 <= k < cnt.size and cnt[k]]
    b = _use(backend, "split")
    if b == "rust" and cnt.size <= 32768 and present:
        try:
            lut = [-1] * cnt.size
            outs = []
            for j, k in enumerate(present):
                lut[k] = j; outs.append(np.empty(int(cnt[k]), np.int64))
            _rs.split_channels(t, np.ascontiguousarray(ch, np.int16), lut, outs)
            return dict(zip(present, outs))
        except Exception as e:  # noqa: BLE001
            _rust_failed(e)
    return {k: t[ch == k] for k in present}


def tile_sums(ts, xs, ds, w, terms, backend=None):
    """Je Term Σ_t Π_{j∈Term} n_j(t) mit n_j = window_counts(ts, xs[j], ds[j], w). Rust: ein Lauf über alle
    Schlüssel (parallel, ganzzahlig); sonst window_counts je Schlüssel und NumPy-Produkte. Ergebnis als float
    (exakt, solange < 2^53 – bei allen realistischen Zählungen erfüllt)."""
    b = _use(backend, "tiles")
    ds = [int(round(d)) for d in ds]; w = int(w)
    if b == "rust":
        try:
            return [float(v) for v in _rs.tile_sums(_c64(ts), [_c64(x) for x in xs], ds, w, [list(t) for t in terms])]
        except Exception as e:  # noqa: BLE001
            _rust_failed(e); b = _use(None, "tiles")
    n = [window_counts(ts, x, d, w, b) for x, d in zip(xs, ds)]
    out = []
    for term in terms:
        prod = n[term[0]].copy()
        for j in term[1:]:
            prod *= n[j]
        out.append(float(prod.sum()))
    return out


def info() -> dict:
    return {"backend": BACKEND, "available": list(AVAILABLE), "threads": n_threads(), "note": FALLBACK_NOTE,
            "rust_version": getattr(_rs, "__version__", None)}


def warmup() -> float:
    """JIT-Übersetzung vorab (beim ersten Start einige Sekunden, danach aus dem Cache)."""
    import time
    t0 = time.perf_counter()
    a = np.arange(0, 100_000, 7, dtype=np.int64)
    for be in [x for x in AVAILABLE if x != "numpy"] or ["numpy"]:   # auch den Rückfall-Kern vorbereiten
        g2_hist(a, a, 0, a.size, 64, 2, 64, be)
        g3_hist(a, a, a, 0, a.size, 64, 4, 32, be)
        g4_hist(a, a, a, a, 0, a.size, 64, 8, 16, be)
        window_counts(a, a, 0, 10, be)
    return time.perf_counter() - t0
