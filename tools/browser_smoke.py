"""Browser-Rauchtest aller Ansichten (Histo, Zeit, g², g³, g⁴) im echten Headless-Chromium (Playwright).

Prüft je Ansicht, dass Daten ankommen und sich aufsummieren und dass Kacheln, Hinweise und Infozeile gefüllt sind:
  * jeder Ansichtswechsel in jeder Reihenfolge (alle 20 geordneten Paare), Desktop-Breite und 390 px
  * nach einem Datei-Umlauf („Datei wiederholen“)
  * zwei Clients gleichzeitig in verschiedenen Ansichten, einer davon im Zuschauer-Modus („Nur Anzeige“)
  * Auswahlfelder: erste Änderung nach dem Start (auch mit automatischem Bereich) bleibt sichtbar und gilt

  python tools/browser_smoke.py [URL] [Screenshot-Ordner]
Rückgabe 0 = alles gut; Fehler werden einzeln ausgegeben.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

VIEWS = ["hist", "trace", "corr", "g3", "g4"]
NAMES = {"hist": "Histo", "trace": "Zeit", "corr": "g2", "g3": "g3", "g4": "g4"}

# Zustand einer Ansicht im Browser (nur lesen)
PROBE = r"""() => {
  const v = S.view, m = S.lastFrame || {};
  const lpMax = (k) => { const p = S.lp[k]; if (!p || !p.u || !p.u.data) return 0; let mx = 0;
    for (let i = 1; i < p.u.data.length; i++) { const p0 = p.u.series[i]; if (!p0.show) continue;
      for (const y of p.u.data[i]) if (y > mx) mx = y; } return mx; };
  const lpSum = (k) => { const p = S.lp[k]; if (!p || !p.raw) return 0; let s = 0; for (const r of p.raw) for (const y of r) s += y; return s; };
  const vis = (id) => { const e = $(id); return !!e && !e.hidden && e.getBoundingClientRect().height > 20; };
  const txt = (sel) => { const e = document.querySelector(sel); return e ? e.textContent.trim() : ""; };
  const cv = $("gnCanvas"); let painted = 0;
  if (cv && cv.width && cv.height && (v === "g3" || v === "g4")) {
    const d = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
    for (let i = 0; i < d.length; i += 4 * 97) if (d[i] + d[i + 1] + d[i + 2] > 60) painted++; }
  const info = txt("#infolist");
  return { view: v, t: m.t_file_s ?? null, acc: m.acc_time_s ?? null, seq: m.seq ?? null, lite: !!m.lite,
    histMax: lpMax("hist"), histSum: lpSum("hist"), corrMax: lpMax("corr"), corrSum: lpSum("corr"),
    traceN: S.trace && S.trace.data ? S.trace.data[0].length : 0,
    histVis: vis("histPlot"), traceVis: vis("tracePlot"), corrVis: vis("corrPlot"), gnVis: vis("gnPlot"),
    gnbar: !$("gnbar").hidden, big: txt("#gnBig .v"), bigE: txt("#gnBig .e"), notes: txt("#gnNotes"),
    tiles: document.querySelectorAll("#gnList > div").length,
    headView: G.head ? G.head.view : null, T: G.head ? G.head.T_s : null, map3: !!G.map3, cube4: !!G.cube4, painted,
    rates: [...document.querySelectorAll("#rates .rate .v")].map((e) => e.textContent.trim()),
    accinfo: txt("#accinfo"), info, hint: $("chartHint").hidden ? "" : txt("#chartHint"),
    ctrl: txt("#ctrlBtn") };
}"""

NUM = lambda s: any(ch.isdigit() for ch in s)   # noqa: E731


def view_ok(st: dict) -> list[str]:
    """Fehlerliste für einen Zustand; leer = Ansicht vollständig."""
    v, e = st["view"], []
    if st["t"] is None:
        e.append("kein Frame")
    if len(st["rates"]) < 2 or not all(NUM(r) for r in st["rates"]):
        e.append(f"Zählraten-Kacheln leer {st['rates']}")
    if "akkumuliert" not in st["accinfo"] and "Fenster" not in st["accinfo"]:
        e.append("Akkumulationszeit fehlt")
    for k in ("Frame", "Datenmenge", "Laufzeiten", "Rechenkern", "Clients"):
        if k not in st["info"]:
            e.append(f"Infozeile ohne {k}")
    if st["hint"]:
        e.append(f"Hinweis im Diagramm: {st['hint']}")
    if v == "hist":
        if not st["histVis"] or st["histMax"] <= 1:
            e.append(f"Histogramm leer (max {st['histMax']})")
    elif v == "trace":
        if not st["traceVis"] or st["traceN"] < 2:
            e.append(f"Zeitverlauf leer ({st['traceN']} Punkte)")
    elif v == "corr":
        if not st["corrVis"] or st["corrMax"] <= 1:
            e.append(f"g²-Kurve leer (max {st['corrMax']})")
        if not st["gnbar"] or not NUM(st["big"]) or st["tiles"] < 1:
            e.append(f"g²-Kacheln leer (groß '{st['big']}', {st['tiles']} Kacheln)")
        if "Fenster" not in st["notes"]:
            e.append("g²-Hinweiszeile leer")
    else:
        if not st["gnVis"] or st["headView"] != v or not (st["map3"] if v == "g3" else st["cube4"]) or st["painted"] < 20:
            e.append(f"{v}-Karte fehlt (Kopf {st['headView']}, bemalt {st['painted']})")
        if not st["gnbar"] or not NUM(st["big"]) or st["tiles"] < 1:
            e.append(f"{v}-Kacheln leer (groß '{st['big']}')")
        if "Fenster" not in st["notes"]:
            e.append(f"{v}-Hinweiszeile leer")
    return e


def wait_view(pg, timeout=4.5) -> tuple[dict, list[str]]:
    """Bis die Ansicht vollständig ist (ein Datei-Umlauf mitten drin leert g(n) kurz – daher etwas Zeit)."""
    t_end = time.time() + timeout
    while True:
        st = pg.evaluate(PROBE)
        err = view_ok(st)
        if not err or time.time() > t_end:
            return st, err
        time.sleep(0.15)


def accumulates(pg, v: str) -> list[str]:
    """Zwei Stichproben ≈ 0,8 s auseinander: Messzeit und Inhalt wachsen (oder Datei-Umlauf dazwischen)."""
    for _ in range(4):
        a = pg.evaluate(PROBE); time.sleep(0.8); b = pg.evaluate(PROBE)
        if b["t"] is None or a["t"] is None or b["t"] < a["t"] or (b["acc"] or 0) < (a["acc"] or 0) \
                or (a["T"] is not None and b["T"] is not None and b["T"] < a["T"]):
            continue   # Umlauf dazwischen (GX-Kopf folgt bis ≈ 1 Ergebnis später) → nochmal
        key = {"hist": "histSum", "corr": "corrSum", "trace": "traceN"}.get(v)
        grew = b["acc"] > a["acc"] and (key is None or b[key] > a[key])
        if v in ("g3", "g4", "corr"):
            grew = grew and b["T"] is not None and a["T"] is not None and b["T"] > a["T"]
        if grew:
            return []
        return [f"{NAMES[v]}: sammelt nicht ({a['acc']}→{b['acc']} s, T {a['T']}→{b['T']}"
                + (f", {key} {a[key]}→{b[key]}" if key else "") + ")"]
    return []


def euler_order() -> list[str]:
    """Folge, die jedes geordnete Ansichtspaar (a→b, a≠b) genau einmal enthält."""
    edges = {a: [b for b in VIEWS if b != a] for a in VIEWS}
    stack, path = ["hist"], []
    while stack:
        u = stack[-1]
        if edges[u]:
            stack.append(edges[u].pop(0))
        else:
            path.append(stack.pop())
    return path[::-1]


def run(url: str, shots: Path | None = None, widths=((1280, 900), (390, 844)), log=print) -> list[str]:
    from playwright.sync_api import sync_playwright
    fails: list[str] = []
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    def shot(pg, name):
        if shots:
            try:   # Bild nicht genau im Umlauf-Moment (Zeitverlauf hätte dann erst einen Punkt)
                pg.wait_for_function("S.lastFrame.t_file_s >= 0.6", timeout=6000)
                time.sleep(0.5)   # Infozeile wird nur jeden 3. Frame neu geschrieben
            except Exception:
                pass
            p = shots / f"{name}.png"
            pg.screenshot(path=str(p), full_page=True)
            log(f"  Bild {p}")

    with sync_playwright() as p:
        b = p.chromium.launch()

        def page(w, h, view="hist"):
            ctx = b.new_context(viewport={"width": w, "height": h})
            pg = ctx.new_page()
            errs: list[str] = []
            pg.on("pageerror", lambda ex: errs.append(str(ex)))
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.add_init_script(f"localStorage.setItem('harp.view', '{view}')")
            pg.goto(url)
            pg.wait_for_function("S.lastFrame && S.status", timeout=15000)
            return pg, errs

        # 1) alle Wechsel in jeder Reihenfolge, Desktop und 390 px
        order = euler_order()
        for w, h in widths:
            tag = f"{w}px"
            pg, errs = page(w, h)
            log(f"[{tag}] Reihenfolge: {' → '.join(NAMES[v] for v in order)}")
            seen = set()
            for i, v in enumerate(order):
                pg.evaluate(f"setView('{v}')")
                st, err = wait_view(pg)
                frm = NAMES[order[i - 1]] if i else "Start"
                fails += [f"[{tag}] {frm}→{NAMES[v]}: {x}" for x in err]
                log(f"  {frm:>5}→{NAMES[v]:<5} {'ok' if not err else 'FEHLER ' + '; '.join(err)}")
                if v not in seen:
                    seen.add(v)
                    fails += [f"[{tag}] {x}" for x in accumulates(pg, v)]
                    shot(pg, f"r3-{tag}-{NAMES[v]}")
            # 2) nach einem Datei-Umlauf: Umlauf abwarten, dann jede Ansicht erneut
            t0 = pg.evaluate("S.lastFrame.seq")
            pg.wait_for_function("(s) => S.lastFrame.seq > s && S.lastFrame.t_file_s < 0.35", arg=t0, timeout=20000)
            log(f"[{tag}] nach Datei-Umlauf (t = {pg.evaluate('S.lastFrame.t_file_s')} s)")
            for v in VIEWS:
                pg.evaluate(f"setView('{v}')")
                st, err = wait_view(pg)
                fails += [f"[{tag}] nach Umlauf {NAMES[v]}: {x}" for x in err]
                log(f"  {NAMES[v]:<5} {'ok' if not err else 'FEHLER ' + '; '.join(err)}")
                if v == "corr":
                    shot(pg, f"r3-{tag}-nach-Umlauf-g2")
            fails += [f"[{tag}] JS-Fehler: {x}" for x in errs]
            pg.context.close()

        # 3) zwei Clients, verschiedene Ansichten; B im Zuschauer-Modus
        A, ea = page(1280, 900, "g3")
        B, eb = page(390, 844, "corr")
        A.evaluate("send('acquire_control')")
        A.wait_for_function("S.mine", timeout=5000)
        B.wait_for_function("$('ctrlBtn').textContent.includes('Nur Anzeige')", timeout=5000)
        log("[2 Clients] A steuert (Desktop), B nur Anzeige (390 px)")
        for va, vb in (("g3", "corr"), ("g4", "hist"), ("corr", "g4"), ("trace", "g3"), ("hist", "trace"), ("g3", "g4")):
            A.evaluate(f"setView('{va}')"); B.evaluate(f"setView('{vb}')")
            for nm, pg, v in (("A", A, va), ("B", B, vb)):
                st, err = wait_view(pg)
                fails += [f"[2 Clients] {nm} {NAMES[v]}: {x}" for x in err]
                log(f"  {nm} {NAMES[v]:<5} {'ok' if not err else 'FEHLER ' + '; '.join(err)}")
            if (va, vb) == ("g3", "corr"):
                shot(A, "r3-2clients-A-g3"); shot(B, "r3-2clients-B-g2-zuschauer")
        if "Nur Anzeige" not in B.evaluate("$('ctrlBtn').textContent"):
            fails.append("[2 Clients] B ist nicht im Zuschauer-Modus")

        # 4) Auswahlfelder: erste Änderung nach dem Start (Bereich mit automatischem Wert in der Liste)
        A.evaluate("send('release_control')")
        fails += select_checks(A, log)
        fails += [f"[2 Clients] JS-Fehler: {x}" for x in ea + eb]
        b.close()
    return fails


SEL_JS = r"""(id) => { const e = $(id); return { value: e.value, text: e.selectedOptions[0] ? e.selectedOptions[0].textContent : null,
  server: String(S.status.settings[id]) }; }"""


def select_checks(pg, log=print) -> list[str]:
    """Jedes Auswahlfeld einmal ändern (Fokus bleibt drin, wie nach einer echten Auswahl): Anzeige = Server-Wert."""
    fails = []
    for sid in ("gn_range_ps", "gn_win_ps", "corr_binning", "binning", "hist_len_code", "display_points", "refresh_ms"):
        opts = pg.evaluate(f"[...$('{sid}').options].map(o => o.value)")
        cur = pg.evaluate(f"$('{sid}').value")
        pick = {"gn_range_ps": "2500000", "gn_win_ps": "10000"}.get(sid)
        if pick not in opts:
            pick = next((o for o in opts if o != cur), None)
        if pick is None:
            continue
        pg.focus(f"#{sid}")
        pg.select_option(f"#{sid}", pick)
        try:
            pg.wait_for_function("([id, v]) => String(S.status.settings[id]) === v", arg=[sid, pick], timeout=5000)
        except Exception:
            pass
        time.sleep(0.8)   # weitere Statusmeldungen (automatischer Bereich, andere Clients) abwarten
        st = pg.evaluate(SEL_JS, sid)
        ok = st["value"] == pick and st["server"] == pick
        log(f"  Auswahl {sid}: gewählt {pick} → Anzeige {st['value']} ({st['text']}), Server {st['server']}"
            f" {'ok' if ok else 'FEHLER'}")
        if not ok:
            fails.append(f"Auswahl {sid}: gewählt {pick}, angezeigt {st['value']} ({st['text']}), Server {st['server']}")
        pg.click("#controls h2")   # Fokus verlassen
    return fails


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    f = run(url, out)
    print(json.dumps({"fehler": f}, ensure_ascii=False, indent=1))
    sys.exit(1 if f else 0)
