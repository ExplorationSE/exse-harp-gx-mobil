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


def test_gn_bar_structure_same_for_g2_g3_g4():
    """Leiste unter den Diagrammen: Auswahl, große Kachel, Kachelliste, graue Hinweise (in dieser Reihenfolge);
    τ₃-Regler sitzt im Diagrammbereich, damit die Leiste in allen drei Ansichten gleich aufgebaut ist."""
    html = (APP.parent / "index.html").read_text(encoding="utf-8")
    bar = html[html.index('id="gnbar"'):html.index("</section>", html.index('id="gnbar"'))]
    order = [bar.index(x) for x in ('id="gnCombo"', 'id="gnBig"', 'id="gnList"', 'id="gnNotes"')]
    assert order == sorted(order) and "gnSliderRow" not in bar
    assert html.index('id="readout"') < html.index('id="gnSliderRow"') < html.index('id="gnbar"')
    js = APP.read_text(encoding="utf-8")
    assert "corr: 2, g3: 3, g4: 4" in js and 'localStorage.setItem("harp.gn2"' in js


def test_all_charts_use_common_height():
    """Histo, g², g³/g⁴-Schnitte und Zeitverlauf nutzen dieselbe Höhe wie die quadratische g³/g⁴-Karte."""
    js = APP.read_text(encoding="utf-8")
    assert "function chartHeight()" in js
    assert not re.search(r"height:\s*histHeight\(\)", js)          # keine uPlot-Höhe mehr direkt aus histHeight
    assert js.count("height: chartHeight()") >= 3                  # Histo/g², Zeit, Schnitte
    heat = js[js.index("function drawHeat"):js.index("function gnPick")]
    assert "Hmax = chartHeight();" in heat and "slH" not in heat   # g⁴-Karte so groß wie g³
    html = (APP.parent / "index.html").read_text(encoding="utf-8")
    plot = html[html.index('id="gnPlot"'):html.index('id="chartHint"')]
    assert "gnSliderRow" not in plot                                # Regler außerhalb der Diagrammhöhe
    assert html.index('id="readout"') < html.index('id="gnSliderRow"') < html.index('id="gnbar"')


def test_generic_harp_naming():
    root = APP.parent.parent
    html = (APP.parent / "index.html").read_text(encoding="utf-8")
    assert "diese Version enthält noch keine Schnittstelle zu einer echten Harp." in html
    for f in ("web/index.html", "web/app.js", "web/manifest.webmanifest", "ANLEITUNG_WINDOWS.md"):
        t = (root / f).read_text(encoding="utf-8")
        assert "echten HydraHarp" not in t and "Harp-Gerät" not in t, f
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "sind Marken" in readme and "PicoQuant" in readme


def test_harp_feminine():
    """„die Harp“: keine neutralen Formen (ein/einem/eines/das/des … Harp) in App, Doku und Code."""
    root = APP.parent.parent
    bad = re.compile(r"\b(ein|einem|eines|das|des|dessen|echtes|ein echtes|jedes)\s+(\(?simulierten\)?\s+|echten\s+|PicoQuant\s+|\*\*)?Harp\b(?![-\w])")
    files = ["web/index.html", "web/app.js", "web/manifest.webmanifest", "README.md", "ANLEITUNG_WINDOWS.md",
             "LIESMICH.txt", "config.toml", "harp/__init__.py", "harp/sources/hh500_live.py"]
    for f in files:
        p = root / f
        if p.exists():
            t = p.read_text(encoding="utf-8")
            assert not bad.search(t), (f, bad.search(t).group(0))
            assert "echtes Harp" not in t, f
    for f in ("README.md", "ANLEITUNG_WINDOWS.md", "web/index.html"):
        assert "einem echten Harp" not in (root / f).read_text(encoding="utf-8"), f


def test_control_labels_single_line_markup():
    """Jedes Label der Steuerung hat eine eigene Text-Hülle .lt (sonst stapelt der Flex-Container Text und g-Symbol)."""
    html = (APP.parent / "index.html").read_text(encoding="utf-8")
    grid = html[html.index('<div class="grid">'):html.index('</section>', html.index('<div class="grid">'))]
    labels = re.findall(r"<label>(.*?)<(?:select|input)", grid, re.S)
    assert len(labels) >= 12
    for lab in labels:
        assert lab.startswith('<span class="lt">') and lab.endswith("</span>"), lab
    css = (APP.parent / "style.css").read_text(encoding="utf-8")
    assert re.search(r"label \.lt\{[^}]*white-space:nowrap", css)


def test_view_order():
    html = (APP.parent / "index.html").read_text(encoding="utf-8")
    btn = html[html.index('id="viewBtn"'):html.index("</button>", html.index('id="viewBtn"'))]
    assert re.findall(r'data-v="(\w+)"', btn) == ["hist", "trace", "corr", "g3", "g4"]
    assert 'const VIEWS = ["hist", "trace", "corr", "g3", "g4"];' in APP.read_text(encoding="utf-8")
