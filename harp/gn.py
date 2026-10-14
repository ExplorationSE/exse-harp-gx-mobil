"""Korrelationen höherer Ordnung g⁽ⁿ⁾ (n = 2, 3, 4) aus T2-Zeitmarken – Referenz-Implementierung (NumPy).

Prinzip (Koinzidenzzählung mit Fenster, alle Kanäle verschieden):
  Für jede Start-Marke t_a (Kanal a) zählt man die Marken n_j der übrigen Kanäle j im Fenster
  [t_a + d_j − w/2, t_a + d_j + w/2). Die Zahl der n-Tupel ist  N = Σ_a Π_j n_j(t_a).

Normierung
  - Dauerstrich (cw):  g⁽ⁿ⁾ = N / (N_a · Π_j (N_j · w / T)),  T = Messdauer
    (erwartete Zufalls-Tupel bei unkorrelierten Poisson-Strömen).
  - Gepulst: g⁽ⁿ⁾ = N(0,…,0) / ⟨N(k₁P, k₂P, …)⟩  mit paarweise verschiedenen Pulsabständen k_j ≠ 0
    (Seitenpeaks, P = Laserperiode). Unabhängig von Effizienzen und Raten.

Diese Version ist bewusst einfach und exakt (Referenz für Tests); der schnelle Rechenkern
(Numba/Rust/GPU) folgt in späteren Versionen und wird gegen diese Funktionen geprüft.
"""
from __future__ import annotations

import itertools

import numpy as np


def window_counts(t_start: np.ndarray, t_other: np.ndarray, delay_ps: float, w_ps: float) -> np.ndarray:
    lo = np.searchsorted(t_other, t_start + delay_ps - w_ps / 2, side="left")
    hi = np.searchsorted(t_other, t_start + delay_ps + w_ps / 2, side="left")
    return hi - lo


def tuple_count(times: dict[int, np.ndarray], start: int, others: list[int], delays_ps: list[float],
                w_ps: float) -> float:
    ta = times[start]
    prod = np.ones(ta.size, np.float64)
    for ch, d in zip(others, delays_ps):
        prod *= window_counts(ta, times[ch], d, w_ps)
    return float(prod.sum())


def gn_cw(times: dict[int, np.ndarray], chans: list[int], w_ps: float, duration_ps: float,
          delays_ps: list[float] | None = None) -> tuple[float, float]:
    """g⁽ⁿ⁾ bei Dauerstrich an den Verzögerungen ``delays_ps`` (Standard 0). Rückgabe (g, Tupelzahl)."""
    a, others = chans[0], list(chans[1:])
    d = list(delays_ps) if delays_ps is not None else [0.0] * len(others)
    n = tuple_count(times, a, others, d, w_ps)
    acc = times[a].size * np.prod([times[c].size * w_ps / duration_ps for c in others])
    return n / acc, n


def gn_pulsed(times: dict[int, np.ndarray], chans: list[int], w_ps: float, period_ps: float,
              n_side: int = 6) -> tuple[float, float]:
    """g⁽ⁿ⁾(0) einer gepulsten Quelle, normiert auf Seitenpeaks. Rückgabe (g, Tupelzahl im Mittelpeak)."""
    a, others = chans[0], list(chans[1:])
    m = len(others)
    center = tuple_count(times, a, others, [0.0] * m, w_ps)
    side = []
    # paarweise verschiedene, von 0 verschiedene Pulsabstände (alle Photonen aus verschiedenen Pulsen)
    ks = [k for k in range(-n_side, n_side + 1) if k != 0]
    for combo in itertools.permutations(ks, m):
        side.append(tuple_count(times, a, others, [k * period_ps for k in combo], w_ps))
        if len(side) >= 120:
            break
    m_side = float(np.mean(side))
    return (center / m_side if m_side > 0 else float("nan")), center


def split_channels(t: np.ndarray, c: np.ndarray) -> dict[int, np.ndarray]:
    return {int(k): np.sort(t[c == k]).astype(np.float64) for k in np.unique(c)}
