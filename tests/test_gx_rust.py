"""Rust-Rechenkern (harp_gx_core): bit-identisch zu Numba und NumPy-Referenz, blockinvariant, Rückfall-Logik."""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from harp.gx import kernels as K
from harp.gx.engine import GnConfig, GnEngine
from harp.ptu import read_all
from tools.generate_gx import SCENARIOS, generate

ROOT = Path(__file__).resolve().parent.parent
need_rust = pytest.mark.skipif(not K.HAVE_RUST, reason="harp_gx_core (Rust) nicht installiert")
ENGS = [e for e in ("rust", "numba") if e in K.AVAILABLE]


def _rand(seed=1, n=40_000, k=4, span=2 * 10**9):
    rng = np.random.default_rng(seed)
    return [np.sort(rng.integers(0, span, n)).astype(np.int64) for _ in range(k)]


@need_rust
@pytest.mark.parametrize("W,NB,i0,i1", [(6_000, 61, 10, 39_000), (25_000, 129, 0, 40_000), (1_000, 33, 500, 501),
                                        (64, 64, 0, 0), (200_000, 33, 100, 20_000)])
def test_kernels_rust_equals_numba_and_numpy(W, NB, i0, i1):
    ts = _rand()
    BW = -(-2 * W // NB)
    refs = {"g2": K.g2_np(ts[0], ts[1], i0, i1, W, BW, NB), "g3": K.g3_np(*ts[:3], i0, i1, W, BW, NB)}
    NB4 = min(NB, 33); BW4 = -(-2 * W // NB4)
    refs["g4"] = K.g4_np(*ts, i0, i1, W, BW4, NB4)
    for be in ENGS:
        assert np.array_equal(K.g2_hist(ts[0], ts[1], i0, i1, W, BW, NB, be), refs["g2"]), be
        assert np.array_equal(K.g3_hist(*ts[:3], i0, i1, W, BW, NB, be), refs["g3"]), be
        assert np.array_equal(K.g4_hist(*ts, i0, i1, W, BW4, NB4, be), refs["g4"]), be
    for d, w in ((0, 10), (500, 3000), (-12_000, 4001)):
        r = K.window_counts(ts[0], ts[1], d, w, "numpy")
        for be in ENGS:
            assert np.array_equal(K.window_counts(ts[0], ts[1], d, w, be), r), be


@need_rust
def test_rust_rejects_bad_geometry_without_crash():
    a = np.arange(0, 1000, 3, dtype=np.int64)
    import harp_gx_core as rs
    with pytest.raises(ValueError):
        rs.g2_hist(a, a, 0, a.size, 100, 1, 10, np.zeros(10, np.int64))      # NB·BW < 2W
    with pytest.raises(ValueError):
        rs.g2_hist(a, a, 0, a.size + 5, 10, 1, 20, np.zeros(20, np.int64))   # i1 außerhalb
    with pytest.raises(ValueError):
        rs.g2_hist(a, a, 0, a.size, 10, 1, 20, np.zeros(19, np.int64))      # falsche Ausgabegröße


def _scenario_files(tmp_path_factory):
    out = {}
    d = None
    for name, sc in SCENARIOS.items():
        p = ROOT / "data" / sc["file"]
        if not p.exists():                       # CI: keine Demodaten im Repository → kurz erzeugen
            d = d or tmp_path_factory.mktemp("rs")
            p = generate(name, d / f"{name}.ptu", min(sc["dur"], 1.5), seed=5)
        out[name] = p
    return out


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return _scenario_files(tmp_path_factory)


def _cfg(name, be):
    sc = SCENARIOS[name]
    nch = sc["nch"]
    chans = [0, 1, 2] if name == "heralded_cw" else list(range(1, nch + 1))
    period = 1e12 / sc["sync"] if sc["sync"] else 0.0
    return GnConfig(channels=chans, period_ps=period, auto_geom=not period, backend=be,
                    combo3=tuple(chans[:3]) if len(chans) >= 3 else (1, 2, 3))


def _run(path, cfg, chunk=300_000, limit=None):
    _, e = read_all(path)
    t, c = e.time.astype(np.int64), e.channel.astype(np.int16)
    if limit:
        t, c = t[:limit], c[:limit]
    eng = GnEngine(cfg)
    for i in range(0, t.size, chunk):
        eng.feed(t[i:i + chunk], c[i:i + chunk]); eng.process()
    return eng


def _state(eng):
    return {"map3": eng.map3.copy(), "cube4": eng.cube4.copy(), "center": dict(eng.center), "side": dict(eng.side),
            "n": dict(eng.n), "T": eng.T, "delays": dict(eng.cfg.delays), "win": eng.cfg.win_ps,
            "range": eng.cfg.range_ps, "cal": {k: v.copy() for k, v in (eng.cal or {}).items()}}


def _same(a, b):
    assert a.keys() == b.keys()
    for k in a:
        if isinstance(a[k], np.ndarray):
            assert np.array_equal(a[k], b[k]), k
        elif k == "cal":
            assert a[k].keys() == b[k].keys() and all(np.array_equal(a[k][x], b[k][x]) for x in a[k]), k
        else:
            assert a[k] == b[k], k


@need_rust
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_engine_rust_equals_numba_and_reference_on_demo_files(demo, name):
    """Ganze Demodatei: Rust = Numba (Karten, Würfel, Kacheln, g²-Kalibrierkurven, gewählte Geometrie).
    NumPy-Referenz auf den ersten 150 000 Marken (sonst zu langsam)."""
    p = demo[name]
    r = _state(_run(p, _cfg(name, "rust")))
    if "numba" in K.AVAILABLE:
        _same(r, _state(_run(p, _cfg(name, "numba"))))
    lim = 150_000
    _same(_state(_run(p, _cfg(name, "rust"), 40_000, lim)), _state(_run(p, _cfg(name, "numpy"), 40_000, lim)))
    assert r["map3"].sum() > 0 or name in ("hom_scan", "heralded_cw")


@need_rust
def test_rust_chunk_size_invariant(demo):
    p = demo["thermal_pulsed"]
    cfg = lambda: GnConfig(channels=[1, 2, 3, 4], range_ps=2_500_000, win_ps=10_000, period_ps=1e6,  # noqa: E731
                           delays={2: 1500.0, 3: 3000.0, 4: 4500.0}, auto_cal=False, backend="rust")
    a, b = _state(_run(p, cfg(), 37_000)), _state(_run(p, cfg(), 900_000))
    assert a["cube4"].sum() > 100
    _same(a, b)


def _sub(env_extra, code):
    env = dict(os.environ, **env_extra)
    out = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, r'{ROOT}');" + code],
                         capture_output=True, text=True, env=env, timeout=300)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_engine_order_and_forcing():
    info = "from harp.gx import kernels as K; print(K.BACKEND, ','.join(K.AVAILABLE), K.n_threads(), '|' + K.FALLBACK_NOTE)"
    clean = {k: "" for k in ("HARP_GX_ENGINE", "HARP_GX_NO_RUST", "HARP_GX_NO_NUMBA", "HARP_GX_THREADS")}
    be = _sub(clean, info).split()[0]
    assert be == K.AVAILABLE[0] == ("rust" if K.HAVE_RUST else "numba" if K.HAVE_NUMBA else "numpy")
    assert _sub({**clean, "HARP_GX_ENGINE": "numpy"}, info).startswith("numpy numpy 1")
    if K.HAVE_NUMBA:
        assert _sub({**clean, "HARP_GX_ENGINE": "numba"}, info).startswith("numba ")
    # erzwungener, aber fehlender Rust-Kern → Rückfall mit Hinweis
    out = _sub({**clean, "HARP_GX_ENGINE": "rust", "HARP_GX_NO_RUST": "1"}, info)
    assert out.split()[0] == ("numba" if K.HAVE_NUMBA else "numpy") and "nicht verfügbar" in out
    out = _sub({**clean, "HARP_GX_ENGINE": "gpu"}, info)
    assert "unbekannt" in out
    if K.HAVE_RUST:
        assert _sub({**clean, "HARP_GX_THREADS": "2"}, info).split()[2] == "2"


@need_rust
def test_thread_count_does_not_change_result(demo):
    code = ("import numpy as np; from harp.gx import kernels as K; from harp.ptu import read_all;"
            f"h,e=read_all(r'{demo['thermal_cw']}'); t=e.time.astype(np.int64)[:400000]; c=e.channel[:400000];"
            "a,b,cc,d=[t[c==k] for k in (1,2,3,4)];"
            "print(K.BACKEND, K.n_threads(), int((K.g3_hist(a,b,cc,0,a.size,200000,3101,129)*np.arange(129*129).reshape(129,129)).sum()),"
            " int((K.g4_hist(a,b,cc,d,0,a.size,200000,12122,33)*np.arange(33**3).reshape(33,33,33)).sum()))")
    outs = {n: _sub({"HARP_GX_ENGINE": "rust", "HARP_GX_THREADS": str(n)}, code).split() for n in (1, 3, 8)}
    assert {o[0] for o in outs.values()} == {"rust"} and [o[1] for o in outs.values()] == ["1", "3", "8"]
    assert len({tuple(o[2:]) for o in outs.values()}) == 1


@need_rust
def test_runtime_failure_falls_back(monkeypatch):
    """Wirft der Rust-Kern zur Laufzeit, rechnet derselbe Aufruf mit dem nächsten Kern weiter (Hinweis gesetzt)."""
    def boom(*a, **k):
        raise RuntimeError("Testfehler")
    monkeypatch.setattr(K._rs, "g2_hist", boom)
    for attr in ("BACKEND", "HAVE_RUST", "AVAILABLE", "FALLBACK_NOTE"):
        monkeypatch.setattr(K, attr, getattr(K, attr))
    monkeypatch.setattr(K, "BACKEND", "rust")
    ts = _rand(3, 5000, 2)
    h = K.g2_hist(ts[0], ts[1], 0, 5000, 1_000_000, 15_504, 129)
    assert np.array_equal(h, K.g2_np(ts[0], ts[1], 0, 5000, 1_000_000, 15_504, 129))
    assert K.BACKEND != "rust" and not K.HAVE_RUST and "Rückfall" in K.FALLBACK_NOTE


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_tile_sums_equal_all_backends(seed):
    rng = np.random.default_rng(seed)
    xs = [np.sort(rng.integers(0, 10**9, 40_000)).astype(np.int64) for _ in range(4)]
    ts = np.sort(rng.integers(0, 10**9, 30_000)).astype(np.int64)
    ds = [0, 12_500, -12_500, 25_000]
    terms = [[0], [0, 1], [1, 2, 3], [0, 1, 2, 3], [3, 3]]
    ref = None
    for be in [b for b in ("rust", "numba", "numpy") if b in K.AVAILABLE]:
        got = K.tile_sums(ts, xs, ds, 3000, terms, be)
        if ref is None:
            ref = got
        assert got == ref, be
    # Referenz direkt aus window_counts
    n = [K.window_counts(ts, x, d, 3000, "numpy") for x, d in zip(xs, ds)]
    assert ref == [float(np.prod([n[j] for j in t], axis=0).sum()) for t in terms]


def test_split_channels_equal_and_fallback():
    rng = np.random.default_rng(5)
    t = np.sort(rng.integers(0, 10**9, 50_000)).astype(np.int64)
    ch = rng.integers(0, 6, t.size).astype(np.int16)
    want = [1, 2, 4, 9]
    ref = {k: t[ch == k] for k in want if (ch == k).any()}
    for be in K.AVAILABLE:
        got = K.split_channels(t, ch, want, be)
        assert list(got) == list(ref)
        for k in ref:
            assert np.array_equal(got[k], ref[k])
    assert K.split_channels(t[:0], ch[:0], want) == {}
    if K.HAVE_RUST:   # falsche Ausgabegrößen → ValueError statt Absturz
        with pytest.raises(ValueError):
            K._rs.split_channels(t, ch, [-1, 0], [np.empty(3, np.int64)])
