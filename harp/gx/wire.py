"""Binäres, komprimiertes GX-Frame für die App.

Aufbau: b"GXF1" | uint32 (LE) Länge des JSON-Kopfs | JSON-Kopf (UTF-8) | zlib(Nutzdaten)
Nutzdaten: uint16-Felder (Little Endian) laut Kopf ``arrays`` (Name, Form, Byte-Offset).
Kodierung der Werte: 0 = keine Daten; sonst q = 1 + round((log10(g) + 4) / 12 · 65534) → g = 10^((q−1)/65534·12 − 4),
also g von 1e-4 bis 1e8 mit relativer Auflösung < 0,05 % (bis 0.2.6: bis 1e4 – die Peaks der Paar-/Tripel-Quellen
(g³ ≈ 7·10⁵, g⁴ ≈ 3·10⁶) wurden dort abgeschnitten).
"""
from __future__ import annotations

import json
import struct
import zlib

import numpy as np

LOG_LO, LOG_SPAN = -4.0, 12.0


def quantize(g: np.ndarray) -> np.ndarray:
    g = np.asarray(g, np.float64)
    q = np.zeros(g.shape, np.uint16)
    ok = np.isfinite(g) & (g > 0)
    v = np.clip((np.log10(g[ok]) - LOG_LO) / LOG_SPAN, 0, 1)
    q[ok] = (1 + np.rint(v * 65534)).astype(np.uint16)
    return q


def dequantize(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, np.float64)
    g = 10 ** ((q - 1) / 65534 * LOG_SPAN + LOG_LO)
    g[q == 0] = np.nan
    return g


def encode_body(arrays: dict[str, np.ndarray]) -> tuple[list, bytes]:
    """Nutzdaten (quantisiert, zlib) und Feldbeschreibung – kann vorab im GX-Worker laufen."""
    parts, meta, off = [], [], 0
    for name, a in arrays.items():
        q = quantize(a)
        b = q.astype("<u2").tobytes()
        meta.append({"name": name, "shape": list(q.shape), "offset": off})
        parts.append(b)
        off += len(b)
    return meta, zlib.compress(b"".join(parts), 1)   # Stufe 1: ~3× schneller als 6, kaum größer


def assemble(header: dict, meta: list, body: bytes) -> bytes:
    header = dict(header, arrays=meta, enc="log16", log_lo=LOG_LO, log_span=LOG_SPAN)
    h = json.dumps(header, separators=(",", ":"), default=_json).encode()
    return b"GXF1" + struct.pack("<I", len(h)) + h + body


def encode(header: dict, arrays: dict[str, np.ndarray]) -> bytes:
    return assemble(header, *encode_body(arrays))


def decode(buf: bytes) -> tuple[dict, dict[str, np.ndarray]]:
    assert buf[:4] == b"GXF1"
    n = struct.unpack("<I", buf[4:8])[0]
    h = json.loads(buf[8:8 + n])
    raw = zlib.decompress(buf[8 + n:])
    out = {}
    for m in h["arrays"]:
        cnt = int(np.prod(m["shape"]))
        q = np.frombuffer(raw, "<u2", cnt, m["offset"]).reshape(m["shape"])
        out[m["name"]] = dequantize(q)
    return h, out


def _json(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(type(o))
