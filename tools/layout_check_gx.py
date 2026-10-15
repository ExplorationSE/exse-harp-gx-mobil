"""Prüft Höhen/Positionen in allen Ansichten (360/390 px, Server auf Port 8812):
Diagrammhöhe, Beginn der Leiste, Größe der g³/g⁴-Karte, Zeichenfläche Histo vs. Zeit.
   python tools/layout_check_gx.py [URL]"""
import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8812/"
J = """() => { const r=(s)=>{const e=document.querySelector(s); if(!e||e.hidden||!e.offsetParent) return null; const b=e.getBoundingClientRect(); return [Math.round(b.top),Math.round(b.height)];};
  const over = (id) => { const o = document.querySelector('#' + id + ' .u-over'); if (!o || !o.offsetParent) return null;
    const b = o.getBoundingClientRect(), w = document.querySelector('#' + id).getBoundingClientRect();
    return [Math.round(b.left - w.left), Math.round(w.right - b.right), Math.round(b.width)]; };
  return {chart:r('.chartwrap'), zeile:r('#readout') || r('#gnSliderRow'), leiste:r('#gnbar'), steuerung:r('#controls'),
    karte: (typeof G !== 'undefined' && G.geom && document.querySelector('#gnCanvas').offsetParent && document.querySelector('#gnCut').hidden !== false) ? G.geom.side : null,
    histo: over('histPlot'), zeit: over('tracePlot')}; }"""
with sync_playwright() as p:
    b = p.chromium.launch(); errs = []
    for w, h in ((360, 780), (390, 844)):
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
        pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        pg.goto(URL); pg.wait_for_selector("#histPlot canvas"); time.sleep(3)
        for v, mode in (("hist", None), ("corr", None), ("g3", "map"), ("g3", "diag"), ("g4", "slice"), ("g4", "diag"), ("trace", None)):
            pg.click(f'#viewBtn span[data-v="{v}"]'); time.sleep(0.8)
            if mode:
                pg.click(f'#gnMode button[data-m="{mode}"]'); time.sleep(1.0)
            print(w, v, mode or "", pg.evaluate(J))
    print("JS-Fehler:", errs or "keine"); b.close()
