"""Synthetische T2-PTU-Dateien mit analytisch bekanntem g⁽²⁾, g⁽³⁾, g⁽⁴⁾ (ExplorationSE Harp GX Mobil).

Alle Dateien: Generic-T2-Records, Auflösung 1 ps, Kanäle K1…K4 (Strahlteiler-Baum auf 4 Detektoren),
beim Herald-Szenario K0 = Herald-Detektor am Sync-Eingang. Die erwarteten Werte stehen in
``SCENARIOS[...]["expected"]`` und im PTU-Kommentar; ``tests/test_gn_validation.py`` prüft sie.

  python tools/generate_gx.py --all            # alle Demo-Dateien nach data/
  python tools/generate_gx.py thermal_cw --duration 3 --out /tmp/x.ptu
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harp.ptu import RT_GENERIC_T2, encode_t2_generic, standard_tags, write_ptu  # noqa: E402

PS = 1e12
OFFS = np.array([0.0, 0.0, 1500.0, 3000.0, 4500.0])   # Kabel-Laufzeiten K0…K4 in ps (werden in der Auswertung korrigiert)
DARK = 100.0                                          # Dunkelzählrate je Detektor (cps)


def _finish(rng, t_list, c_list, duration_s, nch, jitter_ps=40.0, offsets=OFFS, dark=DARK):
    for ch in range(1, nch + 1):
        nd = rng.poisson(dark * duration_s)
        t_list.append(rng.random(nd) * duration_s * PS); c_list.append(np.full(nd, ch))
    t = np.concatenate(t_list); c = np.concatenate(c_list).astype(np.int64)
    t = t + offsets[c] + rng.normal(0, jitter_ps, t.size)
    t = np.rint(t).astype(np.int64)
    keep = (t >= 0) & (t < duration_s * PS)
    t, c = t[keep], c[keep]
    o = np.argsort(t, kind="stable")
    return t[o], c[o]


def _route(rng, n, nch=4):
    return rng.integers(1, nch + 1, n)


# ---------------------------------------------------------------- Szenarien
def thermal_cw(duration_s, rng, rate=450_000.0, tau_c_us=0.4, dt_us=0.02):
    """Pseudo-thermisches Licht (rotierende Mattscheibe): komplexes Gauß-Feld (Ornstein-Uhlenbeck),
    Feldkorrelation exp(−|τ|/τc) → g²(τ)=1+exp(−2|τ|/τc), g²(0)=2, g³(0,0)=3!=6, g⁴(0,0,0)=4!=24.
    Jeder der 4 Detektoren zählt Poisson mit Rate rate·I(t). τc = 400 ns (FWHM von g² ≈ 277 ns) und
    450 kHz je Kanal: mit dem automatisch gewählten Fenster (FWHM/6 ≈ 50 ns) ≈ 80 Quadrupel/s."""
    dt = dt_us * 1e-6
    a = np.exp(-dt / (tau_c_us * 1e-6))
    nsteps = int(duration_s / dt)
    tl, cl = [], []
    e = (rng.normal() + 1j * rng.normal()) / np.sqrt(2)
    chunk = 1_000_000
    for s0 in range(0, nsteps, chunk):
        n = min(chunk, nsteps - s0)
        z = (rng.normal(size=n) + 1j * rng.normal(size=n)) / np.sqrt(2) * np.sqrt(1 - a * a)
        # AR(1)-Rekursion vektorisiert: e_k = a^k e_0 + Σ a^(k−j) z_j  (über lfilter-artige Kumulation)
        ak = a ** np.arange(1, n + 1)
        ek = ak * (e + np.cumsum(z / ak)) if n <= 200 else _ar1(e, z, a, bl=int(min(100_000, max(200, 300 / -np.log(a)))))
        e = ek[-1]
        inten = np.abs(ek) ** 2
        for ch in range(1, 5):
            k = rng.poisson(rate * inten * dt)
            idx = np.repeat(np.arange(n), k)
            tl.append((s0 + idx + rng.random(idx.size)) * dt * PS); cl.append(np.full(idx.size, ch))
    return _finish(rng, tl, cl, duration_s, 4)


def _ar1(e0, z, a, bl=200):
    # stabile blockweise Rekursion (Blocklänge so, dass a^-k ≤ e^300 bleibt, kein Überlauf)
    out = np.empty(z.size, np.complex128)
    e = e0
    for b in range(0, z.size, bl):
        zz = z[b:b + bl]
        ak = a ** np.arange(1, zz.size + 1)
        blk = ak * (e + np.cumsum(zz / ak))
        out[b:b + zz.size] = blk
        e = blk[-1]
    return out


def thermal_pulsed(duration_s, rng, rep_hz=1e6, mu=0.25):
    """Gepulstes thermisches Licht, eine Mode pro Puls: Pulsintensität exponentialverteilt, Pulse
    unabhängig. Je Detektor Poisson(mu·I). Seitenpeak-normiert: g²=2, g³=6, g⁴=24."""
    npulse = int(duration_s * rep_hz)
    period = PS / rep_hz
    tl, cl = [], []
    for p0 in range(0, npulse, 2_000_000):
        n = min(2_000_000, npulse - p0)
        inten = rng.exponential(1.0, n)
        for ch in range(1, 5):
            k = rng.poisson(mu * inten)
            idx = np.repeat(np.arange(n), k) + p0
            tl.append(idx * period + 2000.0); cl.append(np.full(idx.size, ch))
    return _finish(rng, tl, cl, duration_s, 4)


def laser_cw(duration_s, rng, rate=450_000.0):
    """Kohärentes Laserlicht (Poisson): g²=g³=g⁴=1."""
    tl, cl = [], []
    for ch in range(1, 5):
        n = rng.poisson(rate * duration_s)
        tl.append(rng.random(n) * duration_s * PS); cl.append(np.full(n, ch))
    return _finish(rng, tl, cl, duration_s, 4)


def single_cw(duration_s, rng, rate=1_000_000.0, tau_ex_ns=20.0, tau_rad_ns=5.0):
    """Einzelner Emitter (Zwei-Niveau, inkohärent gepumpt): Erneuerungsprozess mit Abstand
    Exp(τex)+Exp(τrad) → g²(τ)=1−exp(−|τ|/τ0), 1/τ0=1/τex+1/τrad. Detektion = Ausdünnung mit η
    (geometrisch viele Zyklen zwischen detektierten Photonen). g³(0,0)=g⁴=0."""
    period_ns = tau_ex_ns + tau_rad_ns
    eta = rate * period_ns * 1e-9
    n = int(rate * duration_s * 1.02) + 100
    k = rng.geometric(eta, n)
    gaps = rng.gamma(k, tau_ex_ns) + rng.gamma(k, tau_rad_ns)
    t = np.cumsum(gaps) * 1000.0
    t = t[t < duration_s * PS]
    return _finish(rng, [t], [_route(rng, t.size)], duration_s, 4)


Q_SP = 0.012658   # Zwei-Photonen-Anteil → g²(0)=4q/(1+q)² = 0,0500 bei p=0,5


def single_pulsed(duration_s, rng, rep_hz=40e6, p=0.5, q=Q_SP, eta=0.04, lifetime_ns=1.0):
    """Gepulste Einzelphotonenquelle: je Puls mit Wahrscheinlichkeit p ein Photon, davon Anteil q mit
    zweitem Photon. g²(0)=2q/(p(1+q)²) (Seitenpeak-normiert, unabhängig von η), g³=g⁴=0."""
    npulse = int(duration_s * rep_hz)
    period = PS / rep_hz
    n1 = rng.poisson(npulse * p * (1 - q) * eta)
    n2 = rng.poisson(npulse * p * q * (1 - (1 - eta) ** 2))
    # verschiedene Pulse ziehen (ohne Zurücklegen, sonst entstünden Poisson-Zufallspaare im selben Puls)
    cand = np.unique(rng.integers(0, npulse, int((n1 + n2) * 1.05) + 10))
    rng.shuffle(cand)
    pul1, pul2 = cand[:n1], cand[n1:n1 + n2]
    n2 = pul2.size
    both = rng.random(n2) < eta / (2 - eta)
    pulses = np.concatenate([pul1, pul2, pul2[both]])
    t = pulses * period + 3000.0 + rng.exponential(lifetime_ns * 1000, pulses.size)
    return _finish(rng, [t], [_route(rng, t.size)], duration_s, 4, dark=50.0)


def heralded_cw(duration_s, rng, pair_rate=1e6, eta_i=0.1, eta_s=0.25):
    """SPDC-Paare (Poisson, Dauerstrich): Idler → K0 (Herald, Sync-Eingang), Signal → 50:50 → K1/K2.
    Heralded g²(0) ≈ 2·R·w (Mehrpaar-Beiträge, R=Paarrate, w=Fenster); ohne Herald g²(K1,K2)=1."""
    n = rng.poisson(pair_rate * duration_s)
    tp = rng.random(n) * duration_s * PS
    i = rng.random(n) < eta_i
    s = rng.random(n) < eta_s
    tl = [tp[i], tp[s]]
    cl = [np.zeros(i.sum(), np.int64), rng.integers(1, 3, s.sum())]
    offs = np.array([0.0, 12000.0, 15000.0, 0, 0])
    nd = rng.poisson(DARK * duration_s)
    tl.append(rng.random(nd) * duration_s * PS); cl.append(np.zeros(nd, np.int64))
    return _finish(rng, tl, cl, duration_s, 2, jitter_ps=25.0, offsets=offs)


HOM_V0, HOM_SCAN_PS, HOM_TC_PS = 0.9, 1.0, 0.3


def hom_visibility(frac):
    """Sichtbarkeit beim Zeitanteil frac∈[0,1] des Scans: Verzögerung δ läuft linear von −1 ps bis +1 ps."""
    d = (2 * np.asarray(frac) - 1) * HOM_SCAN_PS
    return HOM_V0 * np.exp(-(d / HOM_TC_PS) ** 2)


def hom_scan(duration_s, rng, pair_rate=400_000.0, eta=0.2):
    """Hong-Ou-Mandel: Photonenpaare an 50:50-Strahlteiler, Ausgänge K1/K2. Verzögerung δ wird über
    die Messzeit linear von −1 ps bis +1 ps gefahren, V(δ)=0,9·exp(−(δ/0,3 ps)²).
    Koinzidenzrate K1–K2 (τ≈Kabelversatz) ∝ 1−V(δ) → HOM-Dip im Zeitverlauf, Minimum 10 %."""
    n = rng.poisson(pair_rate * duration_s)
    tp = np.sort(rng.random(n) * duration_s * PS)
    v = hom_visibility(tp / (duration_s * PS))
    d1 = rng.random(n) < eta
    d2 = rng.random(n) < eta
    # P(verschieden)=(1−V)/2, P(beide gleich)=(1+V)/2.
    sep = rng.random(n) < (1 - v) / 2
    o1 = rng.integers(1, 3, n)
    o2 = np.where(sep, 3 - o1, o1)
    both = d1 & d2
    t_list = [tp[d1], tp[d2 & ~(both & ~sep)]]      # gleicher Ausgang: zweites Photon geht in der Totzeit verloren
    c_list = [o1[d1], o2[d2 & ~(both & ~sep)]]
    offs = np.array([0.0, 0.0, 8000.0, 0, 0])
    return _finish(rng, t_list, c_list, duration_s, 2, jitter_ps=30.0, offsets=offs)


# ------------------------------------------------ Mehrphotonen-Quellen (Cluster-Prozess, cw)
PAIR_RATE, PAIR_ETA = 1.0e6, 0.8          # Paare/s, Sammel-/Heralding-Effizienz je Arm
TRIP_RATE, TRIP_ETA = 6.0e5, 0.5          # Tripel/s, Effizienz je Photon
MULTI_W = 2000                             # Standard-Koinzidenzfenster der Live-Ansicht (ps, keine Autogeometrie bei schmalem Peak)


def _arm(rng, n, eta, chans):
    """Ausdünnung mit η und Verteilung auf die Detektoren des Arms (50:50 bei zwei Kanälen)."""
    d = rng.random(n) < eta
    return d, rng.choice(np.asarray(chans), n)


def photon_pairs(duration_s, rng, pair_rate=PAIR_RATE, eta=PAIR_ETA):
    """Sehr gute Zwei-Photonen-Quelle (SPDC cw, ein Paar je Erzeugung, Poisson-Paarstrom, Mehrpaar-
    Wahrscheinlichkeit je Fenster R·w = 0,002). Signal → 50:50 → K1/K3, Idler → 50:50 → K2/K4,
    η = 0,8 je Arm (hohe Sammel-/Heralding-Effizienz), Photonen eines Paares gleichzeitig (± Jitter).
    Erwartung (Fenster w, x = R·w): g²(K1,K2) = g²(K1,K4) = g²(K3,K2) = g²(K3,K4) = 1 + 1/x,
    g²(K1,K3) = g²(K2,K4) = 1; g³(K1,K2,K3) = 1 + 2/x; g⁴(K1..K4) = 1 + 4/x + 2/x²."""
    n = rng.poisson(pair_rate * duration_s)
    tp = rng.random(n) * duration_s * PS
    ds, cs = _arm(rng, n, eta, (1, 3))
    di, ci = _arm(rng, n, eta, (2, 4))
    return _finish(rng, [tp[ds], tp[di]], [cs[ds], ci[di]], duration_s, 4)


def photon_triplets(duration_s, rng, trip_rate=TRIP_RATE, eta=TRIP_ETA):
    """Gute Drei-Photonen-Quelle (z. B. kaskadierte Emission / Tripel, cw, Poisson-Tripelstrom):
    Photon a → K1, Photon b → K2, Photon c → 50:50 → K3/K4, η = 0,5 je Photon, kaum Untergrund
    (nur 100 cps Dunkelzählrate). Erwartung (x = R·w): g²(K1,K2) = g²(K1,K3) = … = 1 + 1/x, g²(K3,K4) = 1;
    g³(K1,K2,K3) = 1 + 3/x + 1/x²; g³ mit K3 und K4 = 1 + 2/x; g⁴(K1..K4) = 1 + 5/x + 4/x²."""
    n = rng.poisson(trip_rate * duration_s)
    tp = rng.random(n) * duration_s * PS
    da = rng.random(n) < eta
    db = rng.random(n) < eta
    dc, cc = _arm(rng, n, eta, (3, 4))
    return _finish(rng, [tp[da], tp[db], tp[dc]],
                   [np.full(int(da.sum()), 1), np.full(int(db.sum()), 2), cc[dc]], duration_s, 4)


def _partitions(items):
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for p in _partitions(rest):
        for i in range(len(p)):
            yield p[:i] + [[first] + p[i]] + p[i + 1:]
        yield [[first]] + p


E_RANGE = {1: 0.0, 2: 2 / np.sqrt(np.pi), 3: 3 / np.sqrt(np.pi)}   # mittlere Spannweite von m N(0,1)-Werten


def cluster_g(chans, x, allowed, w_ps=None, jitter_ps=0.0):
    """g⁽ⁿ⁾(0) eines Poisson-Cluster-Prozesses (Photonen eines Clusters gleichzeitig ± Jitter):
    g = Σ über Zerlegungen der Kanäle in Blöcke, die je aus einem Cluster stammen können, von x^(b−n)·f,
    x = R·w (Clusterrate × Fensterbreite), b = Zahl der Blöcke. Unabhängig von den Effizienzen.
    f: Randverlust – ein Block ohne das Start-Photon passt nur ganz ins Fenster, wenn seine Jitter-Spannweite
    hineinpasst: Faktor 1 − E[Spannweite]/w je solchem Block (bei 40 ps Jitter, w = 2 ns: 0,977)."""
    n = len(chans)
    tot = 0.0
    for p in _partitions(list(chans)):
        if not all(allowed(frozenset(b)) for b in p):
            continue
        f = 1.0
        if w_ps:
            for b in p:
                if chans[0] not in b and len(b) > 1:
                    f *= 1 - E_RANGE[len(b)] * jitter_ps / w_ps
        tot += x ** (len(p) - n) * f
    return tot


def pair_allowed(b):
    return len(b) == 1 or (len(b) == 2 and len(b & {1, 3}) == 1 and len(b & {2, 4}) == 1)


def triplet_allowed(b):
    return not {3, 4} <= b


def multi_expected(rate, allowed, w_ps=MULTI_W):
    x = rate * w_ps / PS
    combos = {"g2": (1, 2), "g2_13": (1, 3), "g2_24": (2, 4), "g2_34": (3, 4), "g3": (1, 2, 3), "g3_134": (1, 3, 4),
              "g4": (1, 2, 3, 4)}
    out = {k: float(f"{cluster_g(c, x, allowed, w_ps, 40.0):.5g}") for k, c in combos.items()}
    out.update({k + "_ideal": float(f"{cluster_g(c, x, allowed):.6g}") for k, c in combos.items() if k in ("g2", "g3", "g4")})
    out.update(w_ps=w_ps, x=x, jitter_ps=40.0)
    return out


def thermal_cw_expected(w_ps, tau_c_ps=400_000.0, n=400_000, seed=7):
    """Erwartete Kachelwerte bei Fensterbreite w: Mittel der Permanente der Korrelationsmatrix
    γ_ij = exp(−|τi−τj|/τc) (Gauß-Feld, Wick) über τ_i gleichverteilt in ±w/2 um die Start-Marke (τ=0)."""
    rng = np.random.default_rng(seed)
    out = {}
    for order in (2, 3, 4):
        tau = np.concatenate([np.zeros((n, 1)), rng.uniform(-w_ps / 2, w_ps / 2, (n, order - 1))], axis=1)
        g = np.exp(-np.abs(tau[:, :, None] - tau[:, None, :]) / tau_c_ps)
        per = np.zeros(n)
        import itertools
        for p in itertools.permutations(range(order)):
            per += np.prod([g[:, i, p[i]] for i in range(order)], axis=0)
        out[f"g{order}"] = round(float(per.mean()), 3)
    return out


THERMAL_CW_W = 50_000   # automatisch gewähltes Fenster (FWHM/6, gerundet)


def _tau0():
    return 1.0 / (1 / 20.0 + 1 / 5.0)


def single_cw_expected(w_ns):
    t0 = _tau0()
    return 1 - (2 * t0 / w_ns) * (1 - np.exp(-w_ns / (2 * t0)))


SCENARIOS = {
    "thermal_cw": dict(fn=thermal_cw, dur=3, file="Demo_Synthetisch_T2_Thermisch_cw_g2g3g4_3s.ptu", nch=4, sync=0,
                       expected={**thermal_cw_expected(THERMAL_CW_W), "g2_ideal": 2.0, "g3_ideal": 6.0,
                                 "g4_ideal": 24.0, "w_ps": THERMAL_CW_W,
                                 "note": "ideal 2/6/24; Fenster 50 ns vs. τc 400 ns → Werte über das Fenster gemittelt"},
                       comment="Synthetisch: pseudo-thermisches Licht cw, tau_c=400 ns, 450 kHz je Kanal K1-K4; g2(0)=2, g3(0,0)=6, g4(0,0,0)=24 (ideal)"),
    "thermal_pulsed": dict(fn=thermal_pulsed, dur=4, file="Demo_Synthetisch_T2_Thermisch_gepulst_1MHz_4s.ptu", nch=4, sync=1e6,
                           expected={"g2": 2.0, "g3": 6.0, "g4": 24.0, "w_ps": 2000, "period_ps": 1e6},
                           comment="Synthetisch: thermisches Licht gepulst 1 MHz, eine Mode/Puls; Seitenpeak-normiert g2=2, g3=6, g4=24"),
    "laser_cw": dict(fn=laser_cw, dur=3, file="Demo_Synthetisch_T2_Laser_kohaerent_Referenz_3s.ptu", nch=4, sync=0,
                     expected={"g2": 1.0, "g3": 1.0, "g4": 1.0, "w_ps": 140_000},
                     comment="Synthetisch: kohaerentes Laserlicht (Poisson), 4 Detektoren; erwartet g2=g3=g4=1"),
    "single_cw": dict(fn=single_cw, dur=4, file="Demo_Synthetisch_T2_Einzelphotonen_cw_Antibunching_4s.ptu", nch=4, sync=0,
                      expected={"g2": float(single_cw_expected(4.0)), "g2_ideal": 0.0, "g3": 0.0, "w_ps": 4000,
                                "tau0_ns": _tau0(), "note": "g2(tau)=1-exp(-|tau|/4 ns); Mittel über Fenster 4 ns → 0,213"},
                      comment="Synthetisch: Einzelemitter cw, g2(tau)=1-exp(-|tau|/4ns), 4 Detektoren; g3=g4=0"),
    "single_pulsed": dict(fn=single_pulsed, dur=4, file="Demo_Synthetisch_T2_Einzelphotonen_gepulst_40MHz_4s.ptu", nch=4, sync=40e6,
                          expected={"g2": 0.05, "g3": 0.0, "w_ps": 6000, "period_ps": 25_000},
                          comment="Synthetisch: Einzelphotonenquelle gepulst 40 MHz, Seitenpeak-normiert g2(0)=0.05, g3=g4=0"),
    "heralded_cw": dict(fn=heralded_cw, dur=8, file="Demo_Synthetisch_T2_Heralded_K0_g2h_8s.ptu", nch=2, sync=None,
                        expected={"g2h": 2 * 1e6 * 4e-9, "g2_unheralded": 1.0, "w_ps": 4000,
                                  "delays_ps": [12000, 15000]},
                        comment="Synthetisch: SPDC-Paare cw 1 MHz, K0=Herald (Sync-Eingang), K1/K2 HBT (+12/+15 ns); heralded g2(0)=2*R*w=0.008 bei w=4 ns"),
    "hom_scan": dict(fn=hom_scan, dur=20, file="Demo_Synthetisch_T2_HOM_Dip_Scan_20s.ptu", nch=2, sync=0,
                     expected={"V0": HOM_V0, "dip_min": 1 - HOM_V0, "w_ps": 2000, "delay_ps": 8000},
                     comment="Synthetisch: Hong-Ou-Mandel, Verzoegerung -1..+1 ps linear ueber die Messzeit, V=0.9*exp(-(d/0.3ps)^2); Koinzidenzen K1-K2 (+8 ns) zeigen Dip auf 10 %"),
    "pairs_cw": dict(fn=photon_pairs, dur=3, file="Demo_Synthetisch_T2_Photonenpaare_SPDC_cw_3s.ptu", nch=4, sync=0,
                     expected={**multi_expected(PAIR_RATE, pair_allowed),
                               "note": "R=1 MHz Paare, w=2 ns → x=0,002: g2(K1,K2)=501, g2(K1,K3)=1, g3=1+2/x=1001, "
                                       "g4=1+4/x+2/x²=502001 (ideal); mit 40 ps Jitter-Randverlust g3=990, g4=4,9e5"},
                     comment="Synthetisch: Photonenpaare SPDC cw 1 MHz, eta=0,8 je Arm; Signal K1/K3, Idler K2/K4; bei w=2 ns g2(K1,K2)=501, g2(K1,K3)=1, g3(K1K2K3)=990, g4=4,9e5"),
    "triplets_cw": dict(fn=photon_triplets, dur=5, file="Demo_Synthetisch_T2_Photonentripel_cw_5s.ptu", nch=4, sync=0,
                        expected={**multi_expected(TRIP_RATE, triplet_allowed),
                                  "note": "R=600 kHz Tripel, w=2 ns → x=0,0012: g2=834, g2(K3,K4)=1, g3(K1K2K3)=1+3/x+1/x²=6,97e5, "
                                          "g3(K1K3K4)=1+2/x=1668, g4=1+5/x+4/x²=2,78e6 (ideal; mit Jitter-Randverlust etwas kleiner)"},
                        comment="Synthetisch: Photonentripel cw 600 kHz, eta=0,5; a K1, b K2, c K3/K4; bei w=2 ns g2(K1,K2)=834, g2(K3,K4)=1, g3(K1K2K3)=6,97e5, g4=2,78e6"),
}


def generate(name: str, out: Path, duration: float | None = None, seed: int = 1) -> Path:
    sc = SCENARIOS[name]
    dur = float(duration or sc["dur"])
    rng = np.random.default_rng(seed)
    t, c = sc["fn"](dur, rng)
    rec = encode_t2_generic(t, c)
    rates = [float(np.count_nonzero(c == k)) / dur for k in range(1, sc["nch"] + 1)]
    sync = sc["sync"] if sc["sync"] is not None else float(np.count_nonzero(c == 0)) / dur
    tags = standard_tags(record_type=RT_GENERIC_T2, num_records=rec.size, global_res_s=1e-12, res_s=1e-12,
                         mode=2, num_channels=sc["nch"], acq_time_ms=int(dur * 1000), sync_rate=sync,
                         input_rates=rates, comment=sc["comment"])
    out.parent.mkdir(parents=True, exist_ok=True)
    write_ptu(out, tags, rec)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", nargs="?", choices=list(SCENARIOS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--duration", type=float)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    names = list(SCENARIOS) if a.all else [a.scenario]
    for i, n in enumerate(names):
        out = Path(a.out) if (a.out and not a.all) else Path("data") / SCENARIOS[n]["file"]
        generate(n, out, a.duration, a.seed + i)
        print(f"{out}  {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
