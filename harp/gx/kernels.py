"""Rechenkerne für Korrelationen höherer Ordnung auf sortierten Zeitmarken (int64, ps).

Gleitfenster: Für jede Start-Marke t (Kanal a, Indizes i0…i1) werden alle Marken der anderen Kanäle mit
t − W ≤ t_x < t + W besucht; Bin = (t_x − t + W) // BW mit NB·BW = 2W. Die Start-Marken werden in P Blöcke
geteilt (je Block eigenes Histogramm, parallel über alle Kerne), danach summiert.

Rechenkerne in der Reihenfolge Rust > Numba > NumPy (automatischer Rückfall, wenn einer fehlt oder versagt):
  * Rust (`harp_gx_core`, PyO3 + rayon, alle Kerne, ohne GIL) – optionales Paket aus `rust/harp_gx_core`,
  * Numba (JIT, parallel, ohne GIL),
  * NumPy (gleichwertig, langsamer).
Alle drei liefern bit-identische Histogramme (Tests: tests/test_gx_engine.py, tests/test_gx_rust.py).

GPU (ab 1.2): Der Rust-Kern enthält einen wgpu-Pfad (DirectX 12 / Vulkan / Metal) für die Histogramme g²/g³/g⁴
(32-bit-Relativzeiten je Block, atomare Bins, bit-identisch zur CPU). `gpu_setup()` (vom Worker beim Start über
`warmup()` aufgerufen) prüft das Gerät zuerst in einem eigenen Prozess (Absturz/Hänger des Treibers → einfach
keine GPU) samt Selbsttest gegen die CPU, öffnet es dann hier. Automatik: je Rechenart und Geometrie werden die
ersten Aufrufe abwechselnd auf GPU und CPU gemessen, danach rechnet das Schnellere; regelmäßige Nachprüfung.
Fensterzählungen/Kacheln bleiben auf der CPU (linear, dort schneller). Jeder GPU-Fehler → Rückfall auf die CPU.

Umgebungsvariablen: HARP_GX_ENGINE = gpu | rust | numba | numpy erzwingt einen Kern (fehlt er, gilt die
Reihenfolge oben, mit Hinweis in FALLBACK_NOTE; gpu = Histogramme immer auf der GPU, Rest Rust);
HARP_GX_THREADS = n legt die Thread-Zahl fest; HARP_GX_NO_NUMBA / HARP_GX_NO_RUST / HARP_GX_NO_GPU = 1 schalten
einen Kern ab; HARP_GX_GPU_ALLOW_CPU = 1 lässt auch Software-Adapter (lavapipe, WARP) zu – nur für Tests;
HARP_GX_GPU_BACKEND = dx12 | vulkan | metal wählt die Grafik-Schnittstelle.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("harp.gx")
ENGINES = ("rust", "numba", "numpy")          # CPU-Kerne (Reihenfolge des Rückfalls)
_FORCE = (os.environ.get("HARP_GX_ENGINE") or "").strip().lower() or None
_FORCE_GPU = _FORCE == "gpu"
if _FORCE_GPU:
    _FORCE = None
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

# ---------------------------------------------------------------------------- GPU-Zustand
_NO_GPU = bool(os.environ.get("HARP_GX_NO_GPU")) or (_FORCE in ENGINES)
_GPU_ALLOW_CPU = bool(os.environ.get("HARP_GX_GPU_ALLOW_CPU"))
_GPU_BACKEND = (os.environ.get("HARP_GX_GPU_BACKEND") or "").strip().lower() or None
HAVE_GPU = False
GPU_INFO: dict | None = None      # Gerätedaten (name, backend, device_type, …) der geöffneten GPU
GPU_STATE = "nicht geprüft"       # nicht geprüft | aktiv | kein Gerät | aus | Fehler: …
GPU_MODE = "force" if _FORCE_GPU else "auto"
_LAST: dict[str, str] = {}        # Rechenart → zuletzt benutzter Kern ("gpu" / CPU-Kern)


def n_threads(backend=None) -> int:
    b = backend or BACKEND
    if b == "gpu":
        b = BACKEND
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
    if b == "gpu":            # Nicht-Histogramm-Rechnungen laufen bei „gpu“ auf dem besten CPU-Kern
        b = BACKEND
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


def _g2_cpu(ta, tb, i0, i1, W, BW, NB, backend=None):
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


def _g3_cpu(ta, tb, tc, i0, i1, W, BW, NB, backend=None):
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


def _g4_cpu(ta, tb, tc, td, i0, i1, W, BW, NB, backend=None):
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

# ---------------------------------------------------------------------------- GPU (wgpu im Rust-Kern)
SPAN_LIMIT_W = 1 << 29        # 2W ≤ 2^30 ps: Grenze der 32-bit-Relativzeiten (größere Fenster → CPU)
_TRY = 3                      # Messaufrufe je Kern, bevor die Automatik entscheidet
_REPROBE = 200                # danach alle n Aufrufe erneut beide Kerne messen
_GPU_MARGIN = 0.9             # GPU nur, wenn sie mindestens 10 % schneller ist (Messrauschen, Echtzeit zuerst)


def _cpu(backend):
    return None if backend in (None, "gpu") else backend


class _Chooser:
    """Automatische GPU/CPU-Wahl je (Rechenart, Geometrie) anhand der tatsächlichen Rechenzeit je Start-Marke
    (inkl. Übertragung zur GPU und zurück). Die Ergebnisse beider Wege sind bit-identisch, das Umschalten
    ändert daher nichts an den Histogrammen."""

    def __init__(self):
        self.s: dict = {}

    def pick(self, key) -> str:
        st = self.s.setdefault(key, {"gpu": [], "cpu": [], "calls": 0, "choice": None, "decided": None})
        st["calls"] += 1
        if st["choice"] is not None and st["calls"] % _REPROBE == 0:   # Nachprüfung (Rate/Fenster ändern sich)
            st["gpu"], st["cpu"], st["choice"] = st["gpu"][-1:], st["cpu"][-1:], None
        if st["choice"] is None:
            ng, nc = len(st["gpu"]), len(st["cpu"])
            if ng >= _TRY and nc >= _TRY:
                st["choice"] = st["decided"] = "gpu" if min(st["gpu"]) < _GPU_MARGIN * min(st["cpu"]) else "cpu"
            else:
                return "gpu" if ng <= nc else "cpu"
        return st["choice"]

    def record(self, key, which, sec, n):
        if n > 0 and key in self.s:
            self.s[key][which].append(sec / n)
            del self.s[key][which][:-8]

    def summary(self) -> dict:
        return {f"{k[0]} W={k[1][0]} NB={k[1][2]}": {"wahl": v["decided"],
                                                    "gpu_ns_je_start": (min(v["gpu"]) * 1e9 if v["gpu"] else None),
                                                    "cpu_ns_je_start": (min(v["cpu"]) * 1e9 if v["cpu"] else None)}
                for k, v in self.s.items()}


CHOOSER = _Chooser()
_PENDING: dict = {}
_LAST_KEY: dict = {}


def _want_gpu(backend, kind, geom) -> bool:
    """Soll dieser Histogramm-Aufruf auf die GPU? backend="gpu" bzw. HARP_GX_ENGINE=gpu: immer (falls möglich);
    backend=None: Automatik (nur wenn gpu_setup() ein Gerät geöffnet hat); expliziter CPU-Kern: nie."""
    if backend not in (None, "gpu") or 2 * geom[0] > 2 * SPAN_LIMIT_W:
        return False
    if backend == "gpu" or (backend is None and GPU_MODE == "force"):
        if GPU_STATE == "nicht geprüft":
            gpu_setup()
        return HAVE_GPU
    if not HAVE_GPU or _NO_GPU:
        return False
    _LAST_KEY[kind] = (kind, geom)
    which = CHOOSER.pick((kind, geom))
    _PENDING[kind] = which
    return which == "gpu"


def _gpu_failed(e: Exception) -> None:
    global HAVE_GPU, GPU_STATE, FALLBACK_NOTE
    HAVE_GPU = False
    GPU_STATE = f"Fehler: {e}"
    FALLBACK_NOTE = f"GPU-Fehler ({e}) – Rückfall auf {BACKEND}"
    log.warning(FALLBACK_NOTE)
    try:
        _rs.gpu_release()
    except Exception:  # noqa: BLE001
        pass




def _probe_main() -> None:  # pragma: no cover - läuft im Prüfprozess
    """Prüfprozess: GPU öffnen, Selbsttest GPU = CPU (g², g³, g⁴), kurze Zeitmessung; Ausgabe JSON."""
    info = _rs.gpu_init(_GPU_ALLOW_CPU, _GPU_BACKEND)
    if info is None:
        print(json.dumps({"ok": False, "reason": "kein Gerät"}))
        return
    rng = np.random.default_rng(7)
    ts = [np.sort(rng.integers(0, 4 * 10**8, 30_000)).astype(np.int64) for _ in range(4)]
    for W, NB in ((25_000, 33), (5_000, 129)):
        BW = -(-2 * W // NB)
        for k, (cpu, gpu) in enumerate(((_rs.g2_hist, _rs.gpu_g2_hist), (_rs.g3_hist, _rs.gpu_g3_hist),
                                        (_rs.g4_hist, _rs.gpu_g4_hist))):
            a, b = np.zeros(NB ** (k + 1), np.int64), np.zeros(NB ** (k + 1), np.int64)
            cpu(*ts[:k + 2], 0, ts[0].size, W, BW, NB, a)
            gpu(*ts[:k + 2], 0, ts[0].size, W, BW, NB, b)
            if not np.array_equal(a, b):
                print(json.dumps({"ok": False, "reason": f"Selbsttest g{k + 2} ungleich", "info": info}))
                return
    print(json.dumps({"ok": True, "info": info}))


def gpu_setup(timeout_s: float = 60.0) -> dict | None:
    """GPU suchen, im Prüfprozess testen und hier öffnen. Rückgabe Gerätedaten oder None. Nie eine Ausnahme."""
    global HAVE_GPU, GPU_INFO, GPU_STATE, FALLBACK_NOTE
    if GPU_STATE != "nicht geprüft":
        return GPU_INFO if HAVE_GPU else None
    if _NO_GPU or not HAVE_RUST or not getattr(_rs, "gpu_compiled", lambda: False)():
        GPU_STATE = "aus" if (_NO_GPU or not HAVE_RUST) else "ohne GPU gebaut"
        if _FORCE_GPU:
            FALLBACK_NOTE = f"Rechenkern gpu nicht verfügbar ({GPU_STATE}) – Rückfall auf {BACKEND}"
        return None
    root = str(Path(__file__).resolve().parents[2])
    env = dict(os.environ, HARP_GX_NO_NUMBA="1", HARP_GX_THREADS="2")
    try:
        p = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {root!r});"
                            "from harp.gx import kernels as K; K._probe_main()"],
                           capture_output=True, text=True, env=env, timeout=timeout_s)
        lines = [x for x in p.stdout.strip().splitlines() if x.startswith("{")]
        res = json.loads(lines[-1]) if lines else {"ok": False, "reason": f"Prüfprozess Code {p.returncode}"}
    except Exception as e:  # noqa: BLE001  (Zeitüberschreitung, Treiberabsturz im Prüfprozess …)
        res = {"ok": False, "reason": f"Prüfung fehlgeschlagen: {type(e).__name__}"}
    if not res.get("ok"):
        GPU_STATE = "kein Gerät" if res.get("reason") == "kein Gerät" else f"Fehler: {res.get('reason')}"
        if _FORCE_GPU:
            FALLBACK_NOTE = f"Rechenkern gpu nicht verfügbar ({GPU_STATE}) – Rückfall auf {BACKEND}"
        log.info("GPU: %s", GPU_STATE)
        return None
    try:
        info = _rs.gpu_init(_GPU_ALLOW_CPU, _GPU_BACKEND)
    except Exception as e:  # noqa: BLE001
        info = None
        GPU_STATE = f"Fehler: {e}"
    if not info:
        if GPU_STATE == "nicht geprüft":
            GPU_STATE = "kein Gerät"
        return None
    HAVE_GPU, GPU_INFO, GPU_STATE = True, dict(info), "aktiv"
    log.info("GPU: %s (%s, %s)", info["name"], info["backend"], info["device_type"])
    return GPU_INFO


def gpu_reset_state() -> None:
    """Nur für Tests: GPU schließen und den Zustand „nicht geprüft“ herstellen."""
    global HAVE_GPU, GPU_INFO, GPU_STATE
    if HAVE_RUST and hasattr(_rs, "gpu_release"):
        _rs.gpu_release()
    HAVE_GPU, GPU_INFO, GPU_STATE = False, None, "nicht geprüft"
    CHOOSER.s.clear()
    _PENDING.clear()
    _LAST.clear()
    _LAST_KEY.clear()


def active_backend(backend=None) -> str:
    """Kern der Histogramme (Info-Zeile). Automatik: „gpu“, wenn sie für die zuletzt gerechnete g⁴- bzw.
    g³-Geometrie gewählt wurde (Messphase und Nachprüfung lassen die Anzeige unverändert); erzwungen: „gpu“,
    sobald g³/g⁴ dort liefen."""
    if backend:
        return backend
    if not HAVE_GPU:
        return BACKEND
    if GPU_MODE == "force":
        return "gpu" if any(_LAST.get(k) == "gpu" for k in ("g4", "g3", "g2")) else BACKEND
    for k in ("g4", "g3"):
        st = CHOOSER.s.get(_LAST_KEY.get(k))
        if st and st["decided"]:
            return "gpu" if st["decided"] == "gpu" else BACKEND
    return BACKEND


def gpu_note() -> str:
    """Kurzer Hinweis für die Info-Zeile, wenn eine GPU vorhanden ist, aber die CPU schneller rechnet."""
    if HAVE_GPU and GPU_MODE == "auto" and active_backend() != "gpu" and any(
            v["decided"] == "cpu" for v in CHOOSER.s.values()):
        return f"GPU {GPU_INFO['name']} vorhanden, CPU schneller"
    return ""


def _hist(kind, arrs, i0, i1, W, BW, NB, backend, cpu):
    """Gemeinsamer Einstieg: GPU (falls gewünscht/schneller), sonst CPU-Kern; misst für die Automatik."""
    geom = (int(W), int(BW), int(NB))
    m = len(arrs) - 1
    if W <= 0 or BW <= 0 or NB <= 0 or NB * BW < 2 * W or not 0 <= i0 <= i1 <= len(arrs[0]):
        # vorab prüfen: sonst würde z. B. Numba ohne Grenzprüfung außerhalb des Histogramms schreiben
        raise ValueError(f"Geometrie/Bereich ungültig: W={W}, BW={BW}, NB={NB}, i0={i0}, i1={i1}")
    if _want_gpu(backend, kind, geom):
        out = np.zeros(NB ** m, np.int64)
        t0 = time.perf_counter()
        try:
            getattr(_rs, f"gpu_{kind}_hist")(*[_c64(a) for a in arrs], int(i0), int(i1), *geom, out)
            CHOOSER.record((kind, geom), "gpu", time.perf_counter() - t0, i1 - i0)
            _LAST[kind] = "gpu"
            return out.reshape((NB,) * m)
        except Exception as e:  # noqa: BLE001
            _gpu_failed(e)
            _PENDING.pop(kind, None)
    t0 = time.perf_counter()
    b = _cpu(backend)
    h = cpu(*arrs, i0, i1, W, BW, NB, b)
    if _PENDING.pop(kind, None) == "cpu":
        CHOOSER.record((kind, geom), "cpu", time.perf_counter() - t0, i1 - i0)
    _LAST[kind] = _use(b, kind)
    return h


def g2_hist(ta, tb, i0, i1, W, BW, NB, backend=None):
    return _hist("g2", (ta, tb), i0, i1, W, BW, NB, backend, _g2_cpu)


def g3_hist(ta, tb, tc, i0, i1, W, BW, NB, backend=None):
    return _hist("g3", (ta, tb, tc), i0, i1, W, BW, NB, backend, _g3_cpu)


def g4_hist(ta, tb, tc, td, i0, i1, W, BW, NB, backend=None):
    return _hist("g4", (ta, tb, tc, td), i0, i1, W, BW, NB, backend, _g4_cpu)


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
            "rust_version": getattr(_rs, "__version__", None), "gpu": GPU_INFO, "gpu_state": GPU_STATE,
            "gpu_mode": GPU_MODE}


def warmup() -> float:
    """JIT-Übersetzung vorab (beim ersten Start einige Sekunden, danach aus dem Cache)."""
    t0 = time.perf_counter()
    gpu_setup()
    a = np.arange(0, 100_000, 7, dtype=np.int64)
    for be in [x for x in AVAILABLE if x != "numpy"] or ["numpy"]:   # auch den Rückfall-Kern vorbereiten
        g2_hist(a, a, 0, a.size, 64, 2, 64, be)
        g3_hist(a, a, a, 0, a.size, 64, 4, 32, be)
        g4_hist(a, a, a, a, 0, a.size, 64, 8, 16, be)
        window_counts(a, a, 0, 10, be)
    if HAVE_GPU:
        g4_hist(a, a, a, a, 0, a.size, 64, 8, 16, "gpu")
    return time.perf_counter() - t0
