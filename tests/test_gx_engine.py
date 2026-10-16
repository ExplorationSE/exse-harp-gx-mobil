"""GX-Rechenkern: Kerne (Numba = NumPy), Blockinvarianz, Abgleich mit harp/gn.py, Normierung,
Kalibrierung, Binärformat, Worker-Prozess und Live-Server."""
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from harp.gn import gn_cw, gn_pulsed, split_channels
from harp.gx import kernels as K
from harp.gx import wire
from harp.gx.engine import GnConfig, GnEngine
from harp.ptu import read_all
from tools.generate_gx import OFFS, SCENARIOS, generate, thermal_cw_expected  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("gxe")
    spec = {"thermal_pulsed": 3, "thermal_cw": 3, "single_pulsed": 2, "heralded_cw": 4, "laser_cw": 3, "single_cw": 2}
    return {n: generate(n, d / f"{n}.ptu", dur, seed=33) for n, dur in spec.items()}


def events(path):
    _, e = read_all(path)
    return e.time.astype(np.int64), e.channel.astype(np.int16)


def run(t, c, cfg, chunk=200_000):
    eng = GnEngine(cfg)
    for i in range(0, t.size, chunk):
        eng.feed(t[i:i + chunk], c[i:i + chunk]); eng.process()
    return eng


def test_kernels_numba_equals_numpy():
    if not K.HAVE_NUMBA:
        pytest.skip("Numba nicht installiert")
    rng = np.random.default_rng(1)
    ts = [np.sort(rng.integers(0, 2 * 10**9, 40_000)).astype(np.int64) for _ in range(4)]
    W, NB = 6_000, 61
    BW = 2 * W // NB + 0
    W = BW * NB // 2
    assert np.array_equal(K.g2_hist(ts[0], ts[1], 10, 39_000, W, BW, NB, "numba"), K.g2_np(ts[0], ts[1], 10, 39_000, W, BW, NB))
    assert np.array_equal(K.g3_hist(*ts[:3], 10, 39_000, W, BW, NB, "numba"), K.g3_np(*ts[:3], 10, 39_000, W, BW, NB))
    W4, NB4 = 20_000, 21
    BW4 = 2 * W4 // NB4; W4 = BW4 * NB4 // 2
    a = K.g4_hist(*ts, 10, 39_000, W4, BW4, NB4, "numba")
    assert a.sum() > 0 and np.array_equal(a, K.g4_np(*ts, 10, 39_000, W4, BW4, NB4))
    wn = K.window_counts(ts[0], ts[1], 500, 3000, "numba")
    wp = K.window_counts(ts[0], ts[1], 500, 3000, "numpy")
    assert np.array_equal(wn, wp)


def test_blocks_do_not_change_result(files):
    t, c = events(files["thermal_pulsed"])
    cfg = lambda: GnConfig(channels=[1, 2, 3, 4], range_ps=2_500_000, win_ps=10_000, period_ps=1e6,  # noqa: E731
                           delays={2: 1500.0, 3: 3000.0, 4: 4500.0}, auto_cal=False)
    a = run(t, c, cfg(), 50_000)
    b = run(t, c, cfg(), 700_000)
    assert a.map3.sum() > 1000 and a.cube4.sum() > 100
    assert np.array_equal(a.map3, b.map3) and np.array_equal(a.cube4, b.cube4)
    assert a.center == b.center and a.side == b.side and a.T == b.T


def _ref(path, chans, w, period=0.0):
    hdr, e = read_all(path)
    tm = split_channels(e.time.astype(np.int64), e.channel.astype(np.int64))
    for k in tm:
        tm[k] = tm[k] - OFFS[k]
    T = hdr.acquisition_time_s * 1e12
    return gn_pulsed(tm, chans, w, period)[0] if period else gn_cw(tm, chans, w, T)[0]


@pytest.mark.parametrize("name,period,w", [("thermal_pulsed", 1e6, 2000), ("single_pulsed", 25_000, 6000),
                                           ("thermal_cw", 0.0, 50_000)])
def test_tiles_match_reference(files, name, period, w):
    t, c = events(files[name])
    eng = run(t, c, GnConfig(channels=[1, 2, 3, 4], range_ps=max(25_000, int(2.5 * period)), win_ps=w,
                             period_ps=period, delays={2: 1500.0, 3: 3000.0, 4: 4500.0}, auto_cal=False))
    tiles = {tuple(x["ch"]): x["g"] for x in eng.result()["tiles"]}
    for chans in ([1, 2], [1, 2, 3], [1, 2, 3, 4]):
        ref = _ref(files[name], chans, w, period)
        got = tiles[tuple(chans)]
        if not np.isfinite(got) or ref == 0:   # Einzelphotonen: keine Seitenpeak-Tupel → undefiniert
            assert len(chans) >= 3 and name == "single_pulsed"
            continue
        if ref < 0.2:
            assert abs(got - ref) < 0.02, (chans, got, ref)
        else:
            assert abs(got - ref) / ref < 0.04, (chans, got, ref)


def test_map_normalization_pulsed(files):
    t, c = events(files["thermal_pulsed"])
    eng = run(t, c, GnConfig(channels=[1, 2, 3, 4], range_ps=2_500_000, win_ps=10_000, period_ps=1e6,
                             delays={2: 1500.0, 3: 3000.0, 4: 4500.0}, auto_cal=False))
    r = eng.result()
    m, q = r["map3"], r["cube4"]
    assert abs(m[64, 64] - 6) / 6 < 0.12            # Mittelbin = τ1 = τ2 = 0
    assert abs(q[16, 16, 16] - 24) / 24 < 0.25
    k = lambda tau: 64 + int(round(tau / r["bw3_ps"]))  # noqa: E731
    side = m[k(1e6), k(2e6)]                         # Seitenpeak (1 µs, 2 µs)
    assert 0.7 < side < 1.3


def test_map_normalization_cw_laser(files):
    t, c = events(files["laser_cw"])
    eng = run(t, c, GnConfig(channels=[1, 2, 3, 4], range_ps=2_000_000, win_ps=1_000_000, auto_cal=False,
                             delays={2: 1500.0, 3: 3000.0, 4: 4500.0}))
    m = eng.result()["map3"]
    assert abs(np.nanmedian(m) - 1) < 0.1


def test_auto_calibration(files):
    t, c = events(files["thermal_pulsed"])
    eng = run(t, c, GnConfig(channels=[1, 2, 3, 4], range_ps=2_500_000, win_ps=10_000, period_ps=1e6))
    d = eng.result()["delays"]
    assert eng.cal_done and eng.result()["cal_status"] == "ok"
    for k, v in {2: 1500, 3: 3000, 4: 4500}.items():
        assert abs(d[k] - v) <= 150, d
    t, c = events(files["heralded_cw"])
    eng = run(t, c, GnConfig(channels=[0, 1, 2], combo3=(0, 1, 2), range_ps=25_000, win_ps=4000))
    d = eng.result()["delays"]
    assert abs(d[0] + 12_000) <= 150 and abs(d[2] - 3000) <= 150, d
    g2h = [x for x in eng.result()["tiles"] if x.get("kind") == "g2h"][0]["g"]
    assert g2h < 0.03


def test_wire_roundtrip():
    g = np.array([[np.nan, 1e-3, 0.5], [1.0, 6.0, 24.0], [100.0, 3e3, np.nan]], np.float32)
    buf = wire.encode({"type": "gn", "x": 1}, {"map3": g})
    h, a = wire.decode(buf)
    assert h["x"] == 1 and h["arrays"][0]["shape"] == [3, 3]
    ok = np.isfinite(g)
    assert np.array_equal(np.isnan(a["map3"]), ~ok)
    assert np.max(np.abs(a["map3"][ok] / g[ok] - 1)) < 3e-4


def test_numpy_fallback_subprocess(files):
    code = ("import sys,numpy as np; sys.path.insert(0, r'%s');"
            "from harp.gx import kernels as K; from harp.gx.engine import GnEngine, GnConfig;"
            "from harp.ptu import read_all; h,e=read_all(r'%s');"
            "eng=GnEngine(GnConfig(channels=[1,2,3,4],range_ps=2_500_000,win_ps=10_000,period_ps=1e6,"
            "delays={2:1500.0,3:3000.0,4:4500.0},auto_cal=False));"
            "eng.feed(e.time.astype(np.int64), e.channel.astype(np.int16)); eng.process();"
            "print(K.BACKEND, int(eng.map3.sum()), int(eng.cube4.sum()))") % (ROOT, files["thermal_pulsed"])
    env = dict(os.environ, HARP_GX_NO_NUMBA="1", HARP_GX_ENGINE="numpy")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=300)
    assert out.returncode == 0, out.stderr
    be, n3, n4 = out.stdout.split()
    assert be == "numpy"
    t, c = events(files["thermal_pulsed"])
    eng = GnEngine(GnConfig(channels=[1, 2, 3, 4], range_ps=2_500_000, win_ps=10_000, period_ps=1e6,
                            delays={2: 1500.0, 3: 3000.0, 4: 4500.0}, auto_cal=False))
    eng.feed(t, c); eng.process()
    assert (int(n3), int(n4)) == (int(eng.map3.sum()), int(eng.cube4.sum()))


def test_worker_process(files):
    from harp.gx.runner import GnRunner
    r = GnRunner(0.2)
    r.start()
    try:
        r.configure(GnConfig(channels=[1, 2, 3, 4], range_ps=2_500_000, win_ps=10_000, period_ps=1e6,
                             delays={2: 1500.0, 3: 3000.0, 4: 4500.0}, auto_cal=False), keep_delays=False)
        t, c = events(files["thermal_pulsed"])
        for i in range(0, t.size, 300_000):
            r.feed(t[i:i + 300_000], c[i:i + 300_000])
        res, t0 = None, time.monotonic()
        while time.monotonic() - t0 < 120:
            r.poll()
            res = r.latest
            if res and res["T_s"] > 1.0:
                break
            time.sleep(0.1)
        assert res is not None and res["T_s"] > 1.0
        g4 = {tuple(x["ch"]): x["g"] for x in res["tiles"]}[(1, 2, 3, 4)]
        assert abs(g4 - 24) / 24 < 0.12
        assert r.info.get("backend") in ("rust", "numba", "numpy")
    finally:
        r.stop()
    assert not r.alive


def test_server_streams_binary_gn_frames(tmp_path, files, monkeypatch):
    from fastapi.testclient import TestClient

    from harp.config import Config
    from harp.server import create_app
    d = tmp_path / "data"; d.mkdir()
    (d / "tp.ptu").write_bytes(Path(files["thermal_pulsed"]).read_bytes())
    cfg = Config(data_dir=d, default_file="tp.ptu", log_dir=tmp_path / "logs", autostart=True)
    cfg.gx_enabled = True
    app = create_app(cfg)
    with TestClient(app) as cl, cl.websocket_connect("/ws") as ws:
        ws.send_json({"type": "view", "v": "g3"})
        t0, got = time.monotonic(), None
        while time.monotonic() - t0 < 90:
            m = ws.receive()
            if m.get("bytes"):
                h, a = wire.decode(m["bytes"])
                if "map3" in a and h["n3"] > 0:
                    got = (h, a)
                    break
        assert got is not None, "kein g³-Frame erhalten"
        h, a = got
        assert a["map3"].shape == (129, 129) and h["backend"] in ("rust", "numba", "numpy")
        assert len(m["bytes"]) < 200_000
        st = cl.get("/api/status").json()
        assert st["settings"]["gn_range_ps"] == 2_500_000 and st["gn"]["period_ps"] == pytest.approx(1e6)


def test_laser_calibration_falls_back_without_offsets(files):
    t, c = events(files["laser_cw"])
    eng = run(t, c, GnConfig(channels=[1, 2, 3, 4], range_ps=25_000, win_ps=2000))
    r = eng.result()
    assert r["cal_done"] and r["cal_status"] == "kein_merkmal" and r["delays"] == {}


def test_low_statistics_tiles_are_marked_not_zero(files):
    """Thermisch cw mit Live-Standard (±25 ns, 2 ns): Quadrupel ~1/s·10⁻² → „sammelt Daten“, nicht g = 0."""
    t, c = events(files["thermal_cw"])
    eng = run(t, c, GnConfig(channels=[1, 2, 3, 4], range_ps=25_000, win_ps=2000, auto_cal=False))
    tiles = {tuple(x["ch"]): x for x in eng.result()["tiles"]}
    q = tiles[(1, 2, 3, 4)]
    assert q["low"] and not np.isfinite(q["g"])
    assert not tiles[(1, 2)]["low"] and abs(tiles[(1, 2)]["g"] - 2) < 0.4


def _auto(path, chans=(1, 2, 3, 4)):
    t, c = events(path)
    return run(t, c, GnConfig(channels=list(chans), range_ps=25_000, win_ps=2000, auto_geom=True), 150_000)


def test_autogeom_thermal_cw_fills_g3_g4(files):
    """Live-Standard (±25 ns, 2 ns) + automatische Wahl aus der g²-Breite → g³/g⁴ füllen sich."""
    eng = _auto(files["thermal_cw"])
    r = eng.result()
    g = r["geo"]
    assert g["basis"] == "g2-Breite" and 200_000 <= g["fwhm_ps"] <= 350_000
    assert 35_000 <= r["win_ps"] <= 60_000 and r["range_set_ps"] >= 600_000
    assert r["cal_status"] == "unnoetig"
    ex = thermal_cw_expected(r["win_ps"])
    tiles = {tuple(x["ch"]): x for x in r["tiles"]}
    assert abs(tiles[(1, 2, 3)]["g"] / ex["g3"] - 1) < 0.12
    assert tiles[(1, 2, 3, 4)]["n"] >= 100 and abs(tiles[(1, 2, 3, 4)]["g"] / ex["g4"] - 1) < 0.25
    assert r["n3"] > 1000 and r["n4"] > 100


def test_autogeom_laser_statistics(files):
    r = _auto(files["laser_cw"]).result()
    assert r["geo"]["basis"] == "Statistik" and r["win_ps"] > 20_000
    q = {tuple(x["ch"]): x for x in r["tiles"]}[(1, 2, 3, 4)]
    assert not q["low"] and abs(q["g"] - 1) < 0.35


def test_autogeom_keeps_defaults_for_narrow_features(files):
    r = _auto(files["single_cw"]).result()
    assert r["geo"]["basis"] == "Standard" and r["win_ps"] == 2000 and r["range_set_ps"] == 25_000
    assert not r["geo"]["changed"]


def test_autogeom_off_for_pulsed(files):
    t, c = events(files["thermal_pulsed"])
    eng = run(t, c, GnConfig(channels=[1, 2, 3, 4], range_ps=2_500_000, win_ps=10_000, period_ps=1e6, auto_geom=True))
    assert eng.result()["geo"] is None and eng.cfg.win_ps == 10_000


def test_wire_range_large_g():
    """Paar-/Tripel-Quellen: g³ ≈ 7·10⁵, g⁴ ≈ 3·10⁶ dürfen im Binär-Frame nicht abgeschnitten werden."""
    from harp.gx.wire import dequantize, quantize
    g = np.array([1e-3, 0.05, 1.0, 501.0, 6.97e5, 2.78e6, 5e7])
    back = dequantize(quantize(g))
    assert np.all(np.abs(back / g - 1) < 5e-4)
