"""Farbskala der g³/g⁴-Karten: logarithmische 1-2-5-Teilung (Prüfung der JS-Funktion mit Node, falls vorhanden)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "web" / "app.js"


def _ticks(cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node nicht installiert")
    src = APP.read_text(encoding="utf-8")
    fn = re.search(r"function colorTicks\(lo, hi, maxN\) \{.*?\n\}\n", src, re.S).group(0)
    js = fn + f"console.log(JSON.stringify({json.dumps(cases)}.map(([lo, hi, n]) => colorTicks(lo, hi, n))));"
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_color_ticks_125_and_reference_one():
    lg = __import__("math").log10
    (a, b, c, d, e) = _ticks([[lg(0.08), lg(30), 12], [lg(0.9), lg(1.3), 12], [lg(3), lg(28), 12],
                              [lg(1e-3), lg(1.0), 8], [lg(0.05), lg(60), 4]])
    assert a == [0.1, 0.2, 0.5, 1, 2, 5, 10, 20]
    assert len(b) >= 2 and 1 in b                     # schmaler Bereich um 1: trotzdem mehrere Marken
    assert c[:3] == [5, 10, 20] or len(c) >= 3        # nur eine Dekadenmarke im Bereich → 1-2-5 füllt auf
    assert 1 in d and len(d) >= 3
    assert 1 in e and 3 <= len(e) <= 4               # ausgedünnt, 1 bleibt
    for t in (a, b, c, d, e):
        assert t == sorted(t) and len(t) >= 2
