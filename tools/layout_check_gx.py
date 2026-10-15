"""Prüft, dass Diagramm und Leiste darunter in allen Ansichten auf derselben Höhe liegen (360/390/1280 px).
   python tools/layout_check_gx.py   (Server auf Port 8812)"""
import time, json
from playwright.sync_api import sync_playwright
J = """() => { const r=(s)=>{const e=document.querySelector(s); if(!e||e.hidden||!e.offsetParent) return null; const b=e.getBoundingClientRect(); return [Math.round(b.top),Math.round(b.height)];};
  return {chart:r('.chartwrap'),readout:r('#readout'),bar:r('#gnbar'),big:r('#gnBig'),ctrl:r('#controls')}; }"""
with sync_playwright() as p:
    b=p.chromium.launch(); errs=[]
    for w,h in ((360,780),(390,844),(1280,800)):
        pg=b.new_page(viewport={"width":w,"height":h},device_scale_factor=2)
        pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: m.type=="error" and errs.append(m.text))
        pg.goto("http://127.0.0.1:8812/"); pg.wait_for_selector("#histPlot canvas"); time.sleep(3)
        for v,mode in (("hist",None),("corr",None),("g3","map"),("g3","diag"),("g4","slice"),("g4","diag"),("trace",None)):
            pg.click(f'#viewBtn span[data-v="{v}"]'); time.sleep(0.8)
            if mode: pg.click(f'#gnMode button[data-m="{mode}"]'); time.sleep(1.0)
            print(w,v,mode,pg.evaluate(J))
    print("Fehler:",errs); b.close()
