"""Rust-Kern für den Server-Pfad je Frame (seit 1.3.0): PTU-Dekodierung, T2-Histogramm, g²-Korrelation, Zählraten.

Optional: Ist `harp_gx_core` (≥ 1.3.0) installiert, rechnen `StreamDecoder.decode`, `histogram_t2`, `correlate`
und `counts_per_channel` dort in einem Durchlauf ohne Zwischenfelder – bit-identisch zu den NumPy-Fassungen, die
als Rückfall bleiben (Tests vergleichen beide). HARP_STREAM_NUMPY = 1 oder HARP_GX_NO_RUST = 1 erzwingt NumPy.
"""
from __future__ import annotations

import os

_NEEDED = ("ptu_decode", "t2_hist", "chan_counts", "corr_hist")


def _load():
    if os.environ.get("HARP_STREAM_NUMPY") or os.environ.get("HARP_GX_NO_RUST"):
        return None
    try:
        import harp_gx_core as m
    except Exception:  # noqa: BLE001 - optionales Paket
        return None
    return m if all(hasattr(m, n) for n in _NEEDED) else None


CORE = _load()
