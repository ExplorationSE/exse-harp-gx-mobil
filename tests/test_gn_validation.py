"""Validierung: g⁽²⁾, g⁽³⁾, g⁽⁴⁾ aus synthetischen T2-Dateien gegen die analytischen Sollwerte."""
from pathlib import Path

import numpy as np
import pytest

from harp.gn import gn_cw, gn_pulsed, tuple_count
from tools.generate_gx import SCENARIOS, generate
from tools.validate_gx import evaluate

ROOT = Path(__file__).resolve().parent.parent

# kurze Dateien für schnelle Tests (Dauer in s); Toleranzen nach Zählstatistik gewählt
SHORT = {"thermal_cw": 3, "thermal_pulsed": 1, "laser_cw": 2, "single_cw": 2, "single_pulsed": 2,
         "heralded_cw": 8, "hom_scan": 10}


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    d = tmp_path_factory.mktemp("gx")
    return {n: evaluate(n, generate(n, d / f"{n}.ptu", dur, seed=21)) for n, dur in SHORT.items()}


def rel(a, b):
    return abs(a - b) / b


def test_unit_tuple_count_exact():
    tm = {1: np.array([0.0, 100.0]), 2: np.array([1.0, 50.0, 101.0]), 3: np.array([-2.0, 99.0, 102.0])}
    # Start 0: K2 {1}, K3 {-2} bei w=10 → 1·1; Start 100: K2 {101}, K3 {99, 102} → 1·2
    assert tuple_count(tm, 1, [2, 3], [0, 0], 10) == 3
    assert tuple_count(tm, 1, [2], [50], 10) == 1


def test_unit_poisson_is_one():
    rng = np.random.default_rng(0)
    T = 1e12
    tm = {k: np.sort(rng.random(200_000) * T) for k in (1, 2, 3)}
    assert rel(gn_cw(tm, [1, 2], 1e6, T)[0], 1) < 0.03
    assert rel(gn_cw(tm, [1, 2, 3], 1e7, T)[0], 1) < 0.05


def test_thermal_cw(results):
    r = results["thermal_cw"]
    ex = SCENARIOS["thermal_cw"]["expected"]   # über das Fenster (50 ns, τc 400 ns) gemittelte Sollwerte
    assert rel(r["g2"], ex["g2"]) < 0.03 and rel(r["g3"], ex["g3"]) < 0.08 and rel(r["g4"], ex["g4"]) < 0.15
    assert r["n4"] > 200


def test_thermal_pulsed(results):
    r = results["thermal_pulsed"]
    assert rel(r["g2"], 2) < 0.03 and rel(r["g3"], 6) < 0.06 and rel(r["g4"], 24) < 0.12


def test_laser(results):
    r = results["laser_cw"]
    assert rel(r["g2"], 1) < 0.03 and rel(r["g3"], 1) < 0.06 and rel(r["g4"], 1) < 0.15


def test_single_cw_antibunching(results):
    r = results["single_cw"]
    assert abs(r["g2"] - SCENARIOS["single_cw"]["expected"]["g2"]) < 0.05
    assert r["g3"] < 0.1


def test_single_pulsed(results):
    r = results["single_pulsed"]
    assert abs(r["g2"] - 0.05) < 0.03
    assert r["g3"] < 0.1


def test_heralded(results):
    r = results["heralded_cw"]
    assert abs(r["g2h"] - 0.008) < 0.004
    assert r["g2h"] < 0.05                 # deutliches Herald-Antibunching
    assert rel(r["g2_flat"], 1) < 0.05     # ohne Herald unkorreliert


def test_hom_dip(results):
    r = results["hom_scan"]
    assert abs(r["dip_min"] - r["dip_expected"]) < 0.05
    assert r["max_dev"] < 0.08


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_demo_files_named_and_valid(name):
    fn = SCENARIOS[name]["file"]
    assert "Synthetisch" in fn and fn.endswith(".ptu")
    p = ROOT / "data" / fn
    if not p.exists():
        pytest.skip("Demodatei nicht vorhanden (nur im Release)")
    assert p.stat().st_size < 24e6
