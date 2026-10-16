"""GPU-Pfad (wgpu im Rust-Kern): bit-identisch zu Rust-CPU, NumPy und der Referenz harp/gn.py; Automatik,
Rückfall und Verhalten ohne Gerät.

Ohne Grafik-Adapter werden die GPU-Tests übersprungen. Für diese Tests sind Software-Adapter zugelassen
(lavapipe/llvmpipe unter Linux, WARP unter Windows), damit die Shader auch ohne echte GPU wirklich laufen; im
Betrieb nutzt die Automatik nur echte Grafikchips (HARP_GX_GPU_ALLOW_CPU).
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from harp.gn import tuple_count
from harp.gx import kernels as K
from harp.gx.engine import GnEngine
from harp.ptu import read_all
from tests.test_gx_rust import _cfg, _run, _same, _scenario_files, _state
from tools.generate_gx import SCENARIOS

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def gpu():
    if not K.HAVE_RUST or not getattr(K._rs, "gpu_compiled", lambda: False)():
        pytest.skip("Rust-Kern ohne GPU-Unterstützung")
    old_env, old_allow = os.environ.get("HARP_GX_GPU_ALLOW_CPU"), K._GPU_ALLOW_CPU
    os.environ["HARP_GX_GPU_ALLOW_CPU"] = "1"
    K._GPU_ALLOW_CPU = True
    K.gpu_reset_state()
    info = K.gpu_setup()
    if info is None:
        K._GPU_ALLOW_CPU = old_allow
        pytest.skip(f"kein GPU-Adapter ({K.GPU_STATE})")
    print("GPU:", info)
    yield info
    K.gpu_reset_state()
    K._GPU_ALLOW_CPU = old_allow
    if old_env is None:
        os.environ.pop("HARP_GX_GPU_ALLOW_CPU", None)
    else:
        os.environ["HARP_GX_GPU_ALLOW_CPU"] = old_env


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return _scenario_files(tmp_path_factory)


def _rand(seed=1, n=40_000, k=4, span=2 * 10**9, off=0):
    rng = np.random.default_rng(seed)
    return [np.sort(rng.integers(0, span, n)).astype(np.int64) + off for _ in range(k)]


@pytest.mark.parametrize("W,NB,i0,i1", [(6_000, 61, 10, 39_000), (25_000, 129, 0, 40_000), (1_000, 33, 500, 501),
                                        (64, 64, 0, 0), (200_000, 33, 100, 20_000), (2_000_000, 65, 0, 100)])
def test_gpu_kernels_equal_rust_and_numpy(gpu, W, NB, i0, i1):
    ts = _rand()
    BW = -(-2 * W // NB)
    NB4 = min(NB, 33); BW4 = -(-2 * W // NB4)
    for name, args, nb, bw in (("g2", ts[:2], NB, BW), ("g3", ts[:3], NB, BW), ("g4", ts, NB4, BW4)):
        f = getattr(K, f"{name}_hist")
        g = f(*args, i0, i1, W, bw, nb, "gpu")
        assert K._LAST[name] == "gpu"
        assert np.array_equal(g, f(*args, i0, i1, W, bw, nb, "rust")), name
        if W <= 25_000 or name == "g2":
            assert np.array_equal(g, getattr(K, f"{name}_np")(*args, i0, i1, W, bw, nb)), name


def test_gpu_large_absolute_times_and_gaps(gpu):
    """Absolute Zeiten weit jenseits 2^32 ps (1 h Messzeit) und Lücken > 2^30 ps: 32-bit-Relativzeiten je Block,
    Blockgrenzen an Lücken – Ergebnis unverändert."""
    rng = np.random.default_rng(4)
    bursts = [3_600 * 10**12 + k * 5 * 10**9 for k in range(6)]      # Bündel im Abstand von 5 ms
    ts = [np.sort(np.concatenate([b + rng.integers(0, 3 * 10**6, 1_000) for b in bursts])).astype(np.int64)
          for _ in range(4)]
    W, NB = 30_000, 61
    BW = -(-2 * W // NB)
    for name, args, nb in (("g2", ts[:2], NB), ("g3", ts[:3], NB), ("g4", ts, 31)):
        f = getattr(K, f"{name}_hist")
        bw = -(-2 * W // nb)
        a, b = f(*args, 0, ts[0].size, W, bw, nb, "gpu"), f(*args, 0, ts[0].size, W, bw, nb, "rust")
        assert K.HAVE_GPU and a.sum() > 0 and np.array_equal(a, b), name


def test_invalid_geometry_raises_without_disabling_engines(gpu):
    ts = _rand(1, 1000, 4)
    with pytest.raises(ValueError):
        K.g4_hist(*ts, 0, 1000, 30_000, 984, 31, "gpu")        # NB·BW < 2W
    with pytest.raises(ValueError):
        K.g2_hist(ts[0], ts[1], 0, 1001, 100, 10, 20)          # i1 außerhalb
    assert K.HAVE_GPU and K.HAVE_RUST


def test_gpu_dense_many_dispatches(gpu):
    """Hohe Rate × breites Fenster: viele Teil-Dispatches (Arbeitsgrenze), gleiche Summen wie die CPU."""
    ts = _rand(9, 10_000, 4, span=10**7)              # 1 Tag/ns je Kanal, ~30 Partner je Fenster
    W, NB = 15_000, 17
    BW = -(-2 * W // NB)
    a = K.g4_hist(*ts, 0, ts[0].size, W, BW, NB, "gpu")
    assert a.sum() > 10**8
    assert np.array_equal(a, K.g4_hist(*ts, 0, ts[0].size, W, BW, NB, "rust"))


def test_gpu_huge_window_uses_cpu(gpu):
    """2W > 2^30 ps sprengt die 32-bit-Relativzeiten → dieser Aufruf rechnet ohne Fehler auf der CPU."""
    ts = _rand(2, 2_000, 2, span=10**12)
    W = 2**30
    h = K.g2_hist(ts[0], ts[1], 0, 2_000, W, 2 * W // 64, 64, "gpu")
    assert K._LAST["g2"] != "gpu" and K.HAVE_GPU
    assert np.array_equal(h, K.g2_np(ts[0], ts[1], 0, 2_000, W, 2 * W // 64, 64))


def _times(path, limit=None):
    _, e = read_all(path)
    t, c = e.time.astype(np.int64), e.channel
    if limit:
        t, c = t[:limit], c[:limit]
    return {int(k): t[c == k] for k in np.unique(c)}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_gpu_histograms_match_gn_reference(gpu, demo, name):
    """Jeder Bin der GPU-Karte ist eine Tupelzählung von harp/gn.py: Bin (i, j) von g³ = tuple_count mit Fenster BW
    an den Verzögerungen ((i−c)·BW, (j−c)·BW), c = mittlerer Bin (NB ungerade). Geprüft: Mittelbin und Nachbarn
    für g², g³, g⁴ auf jeder Demodatei (erste 200 000 Marken)."""
    tm = _times(demo[name], 200_000)
    chans = [k for k in sorted(tm) if tm[k].size][:4]
    if len(chans) < 2:
        pytest.skip("zu wenige Kanäle")
    W, NB = 9_000, 9                              # BW = 2000 ps (gerade), c = 4
    BW, c = 2 * W // NB, NB // 2
    fl = {k: v.astype(np.float64) for k, v in tm.items()}
    a = chans[0]
    checks = [("g2", chans[:2], [(c,), (c + 1,), (0,)])]
    if len(chans) >= 3:
        checks.append(("g3", chans[:3], [(c, c), (c - 1, c + 2), (0, NB - 1)]))
    if len(chans) >= 4:
        checks.append(("g4", chans[:4], [(c, c, c), (c, c + 1, c - 1), (1, 2, 3)]))
    total = 0
    for kind, ch, bins in checks:
        h = getattr(K, f"{kind}_hist")(*[tm[k] for k in ch], 0, tm[a].size, W, BW, NB, "gpu")
        assert np.array_equal(h, getattr(K, f"{kind}_hist")(*[tm[k] for k in ch], 0, tm[a].size, W, BW, NB, "rust"))
        for b in bins:
            ref = tuple_count(fl, a, list(ch[1:]), [(i - c) * BW for i in b], BW)
            assert h[b] == ref, (kind, b, h[b], ref)
            total += ref
    assert total > 0 or name == "hom_scan"


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_engine_gpu_equals_rust_on_demo_files(gpu, demo, name):
    """Ganze Demodatei durch GnEngine (Kalibrierung, Autogeometrie, Karten, Würfel, Kacheln): GPU = Rust-CPU."""
    p = demo[name]
    g = _run(p, _cfg(name, "gpu"))
    _same(_state(g), _state(_run(p, _cfg(name, "rust"))))
    r = g.result()
    assert r["backend"] == "gpu" and r["gpu_name"] == gpu["name"]


def test_auto_choice_is_result_neutral(gpu, demo):
    """Automatik (backend=None): misst GPU und CPU abwechselnd, wählt dann; Ergebnis bleibt bit-identisch."""
    K.CHOOSER.s.clear()
    p = demo["thermal_cw"]
    auto = _run(p, _cfg("thermal_cw", None), chunk=60_000)
    _same(_state(auto), _state(_run(p, _cfg("thermal_cw", "rust"), chunk=60_000)))
    s = K.CHOOSER.summary()
    assert s and all(v["wahl"] in ("gpu", "cpu") for k, v in s.items() if k.startswith(("g3", "g4"))), s
    assert all(v["gpu_ns_je_start"] and v["cpu_ns_je_start"] for v in s.values()), s


def test_gpu_runtime_failure_falls_back(gpu, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Testfehler")
    for attr in ("HAVE_GPU", "GPU_STATE", "FALLBACK_NOTE"):
        monkeypatch.setattr(K, attr, getattr(K, attr))
    monkeypatch.setattr(K._rs, "gpu_g3_hist", boom)
    monkeypatch.setattr(K._rs, "gpu_release", lambda: None)   # Gerät für die übrigen Tests offen lassen
    ts = _rand(3, 5000, 3)
    h = K.g3_hist(*ts, 0, 5000, 50_000, 1_552, 65, "gpu")
    assert np.array_equal(h, K.g3_hist(*ts, 0, 5000, 50_000, 1_552, 65, "rust"))
    assert not K.HAVE_GPU and "Rückfall" in K.FALLBACK_NOTE and K.GPU_STATE.startswith("Fehler")


def _sub(env_extra, code):
    env = dict(os.environ, **env_extra)
    out = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, r'{ROOT}');" + code],
                         capture_output=True, text=True, env=env, timeout=300)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


CLEAN = {k: "" for k in ("HARP_GX_ENGINE", "HARP_GX_NO_RUST", "HARP_GX_NO_NUMBA", "HARP_GX_THREADS", "HARP_GX_NO_GPU",
                         "HARP_GX_GPU_ALLOW_CPU")}
INFO = ("from harp.gx import kernels as K; import numpy as np; K.warmup(); a=np.arange(0,10**6,97,dtype=np.int64);"
        "h=K.g3_hist(a,a+5,a+9,0,a.size,500,20,51); "
        "print(K.active_backend(), K.GPU_STATE.replace(' ','_'), int(h.sum()), '|' + K.FALLBACK_NOTE)")


def test_no_gpu_env_and_forced_gpu_without_device_never_crash():
    ref = _sub({**CLEAN, "HARP_GX_ENGINE": "rust"}, INFO).split()
    out = _sub({**CLEAN, "HARP_GX_NO_GPU": "1"}, INFO).split()
    assert out[0] == ref[0] == K.BACKEND and out[1] == "aus" and out[2] == ref[2]
    out = _sub({**CLEAN, "HARP_GX_NO_GPU": "1", "HARP_GX_ENGINE": "gpu"}, INFO)
    assert out.split()[0] == K.BACKEND and "nicht verfügbar" in out and out.split()[2] == ref[2]
    # ohne Software-Adapter-Freigabe: auf der Box (nur lavapipe) → „kein Gerät“, auf einem Rechner mit GPU → aktiv
    out = _sub(CLEAN, INFO).split()
    assert out[1] in ("kein_Gerät", "aktiv", "ohne_GPU_gebaut", "aus") and out[2] == ref[2]


def test_forced_gpu_env_uses_gpu(gpu):
    out = _sub({**CLEAN, "HARP_GX_ENGINE": "gpu", "HARP_GX_GPU_ALLOW_CPU": "1"}, INFO).split()
    ref = _sub({**CLEAN, "HARP_GX_ENGINE": "rust"}, INFO).split()
    assert out[0] == "gpu" and out[1] == "aktiv" and out[2] == ref[2]


def test_gpu_info_in_engine_result(gpu):
    eng = GnEngine(_cfg("thermal_cw", "gpu"))
    r = eng.result()
    assert r["backend"] == "gpu" and r["gpu_name"] == gpu["name"]
    assert K.info()["gpu"]["name"] == gpu["name"] and K.info()["gpu_state"] == "aktiv"
