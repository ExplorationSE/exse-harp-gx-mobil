"""Headless-Prüfung der GX-Ansichten (Playwright/Chromium): JS-Fehler, Kopfzeile einzeilig bei 360/390 px,
Screenshots der g³- und g⁴-Ansicht.

  python tools/screenshot_gx.py [URL] [Ausgabeordner]
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent
FILE = sys.argv[3] if len(sys.argv) > 3 else "Demo_Synthetisch_T2_Thermisch_gepulst_1MHz_4s.ptu"
PREFIX = sys.argv[4] if len(sys.argv) > 4 else "screenshot-gx020"
SPEED = sys.argv[5] if len(sys.argv) > 5 else "5"
MIN_T = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0   # vor den Bildern warten, bis T ≥ MIN_T s gesammelt


def wait_filled(pg):
    if MIN_T <= 0:
        return
    for _ in range(200):
        if pg.evaluate(f"typeof G !== 'undefined' && !!G.head && G.head.T_s >= {MIN_T}"):
            time.sleep(0.6)
            return
        time.sleep(0.1)
HER = "Demo_Synthetisch_T2_Heralded_K0_g2h_8s.ptu"
ROW_JS = """() => { const els = [document.querySelector('#viewBtn'), ...document.querySelectorAll('.chbtn')]
  .map(e => e.getBoundingClientRect());
  return { tops: els.map(r => Math.round(r.top)), right: Math.round(Math.max(...els.map(r => r.right))), vw: innerWidth,
           overflow: document.documentElement.scrollWidth > innerWidth }; }"""
SYM_JS = """() => { const c = document.querySelector('.hist-card').getBoundingClientRect(), g = (typeof G !== 'undefined') && G.geom;
  if (!g) return null; const cv = document.querySelector('#gnCanvas').getBoundingClientRect();
  return { left: Math.round(cv.left - c.left + g.x0), right: Math.round(c.right - (cv.left + g.x0 + g.side)) }; }"""

errors, report = [], []
with sync_playwright() as p:
    b = p.chromium.launch()
    for w, h in ((360, 780), (390, 844)):
        ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=3, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.on("console", lambda m: m.type == "error" and errors.append(f"{w}px console: {m.text}"))
        pg.on("pageerror", lambda e: errors.append(f"{w}px pageerror: {e}"))
        pg.goto(URL)
        pg.wait_for_selector("#histPlot canvas", timeout=20000)
        if w == 360:
            pg.select_option("#file", FILE)
            time.sleep(1.0)
            pg.select_option("#speed", SPEED)
            pg.click("#bStart")
        for v in ("hist", "corr", "g3", "g4", "trace"):
            pg.click(f'#viewBtn span[data-v="{v}"]')
            time.sleep(0.4)
            row = pg.evaluate(ROW_JS)
            report.append((w, v, "einzeilig" if len(set(row["tops"])) == 1 else f"MEHRZEILIG {row['tops']}",
                           f"rechts {row['right']}/{row['vw']}", "Überlauf!" if row["overflow"] else ""))
        time.sleep(9 if w == 360 else 3)
        pg.click('#viewBtn span[data-v="g3"]'); time.sleep(1.5)
        pg.click('#gnMode button[data-m="map"]'); time.sleep(1.2)
        wait_filled(pg)
        report.append((w, "g3-Ränder", pg.evaluate(SYM_JS)))
        pg.screenshot(path=str(OUT / f"{PREFIX}-g3-karte-{w}.png"), full_page=False)
        if w == 390:
            pg.click('#gnMode button[data-m="diag"]'); time.sleep(1.2)
            pg.screenshot(path=str(OUT / f"{PREFIX}-g3-diagonale-{w}.png"))
            pg.click('#gnMode button[data-m="map"]')
        pg.click('#viewBtn span[data-v="g4"]'); time.sleep(1.5)
        pg.click('#gnMode button[data-m="slice"]'); time.sleep(1.2)
        wait_filled(pg)
        pg.screenshot(path=str(OUT / f"{PREFIX}-g4-schnitt-{w}.png"))
        if w == 390:
            pg.evaluate("() => { const s = document.querySelector('#gnTau3'); s.value = String(Math.floor(+s.max / 2) + 8); s.dispatchEvent(new Event('input')); }")
            time.sleep(0.6)
            pg.screenshot(path=str(OUT / f"{PREFIX}-g4-schnitt-tau3-{w}.png"))
            pg.click('#gnMode button[data-m="diag"]'); time.sleep(1.2)
            pg.screenshot(path=str(OUT / f"{PREFIX}-g4-diagonale-{w}.png"))
            pg.click('#gnMode button[data-m="slice"]')
            pg.screenshot(path=str(OUT / f"{PREFIX}-info-{w}.png"), full_page=True)
        ctx.close()
    b.close()
for r in report:
    print(*r)
print("JS-Fehler:", errors or "keine")
