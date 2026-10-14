"""Live-Messung des GX-Pfads: Server (mit Worker) starten, je Demodatei abspielen und g(n)-Frames auswerten.

  python tools/gx_live_bench.py [--speed 1] [--secs 12] [--port 8790]

Gemessen je Datei: Durchsatz des Rechenkerns (Mtags/s, reine Rechenzeit im Worker), Echtzeit-Faktor
(verarbeitete Messzeit / Wanduhrzeit), Latenz (Frame gelesen → Ergebnis beim Server), Größe der Binär-Frames.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("HARP_GX_DISABLE", None)

import uvicorn  # noqa: E402
import websockets  # noqa: E402

from harp.config import load_config  # noqa: E402
from harp.gx.wire import decode  # noqa: E402
from harp.server import create_app  # noqa: E402


async def run(port: int, speed: float, secs: float, view: str, only: str | None):
    url = f"ws://127.0.0.1:{port}/ws"
    rows = []
    async with websockets.connect(url, max_size=None) as ws:
        async def cmd(c, p=None):
            await ws.send(json.dumps({"type": "command", "cmd": c, "params": p or {}}))
        await ws.send(json.dumps({"type": "view", "v": view}))
        await cmd("acquire_control")
        st = None
        while st is None:
            m = await ws.recv()
            if isinstance(m, str) and json.loads(m).get("type") == "status":
                st = json.loads(m)
        files = [f["name"] for f in st["files"] if only is None or only in f["name"]]
        for name in files:
            await cmd("open_file", {"name": name})
            await cmd("set", {"speed": speed, "loop": True})
            await cmd("start")
            t0 = time.monotonic(); last = None; sizes = []; lats = []
            while time.monotonic() - t0 < secs:
                m = await ws.recv()
                if isinstance(m, bytes):
                    h, arr = decode(m)
                    if time.monotonic() - t0 > 3:   # Einschwingen/Kalibrierung abwarten
                        sizes.append(len(m)); lats.append(h["latency_ms"])
                    last = (h, time.monotonic() - t0)
            await cmd("stop")
            if last is None:
                rows.append((name, None)); continue
            h, el = last
            tiles = {("h" if t.get("kind") == "g2h" else "g") + "".join(map(str, t["ch"])): t["g"] for t in h["tiles"]}
            rows.append((name, {"proc_mtags": h["proc_mtags"], "T_s": h["T_s"], "wall_s": round(el, 1),
                                "lat_ms_med": sorted(lats)[len(lats) // 2] if lats else None,
                                "lat_ms_max": max(lats) if lats else None,
                                "kB": round(sum(sizes) / len(sizes) / 1000, 1) if sizes else None,
                                "delays": h["delays"], "cal": h.get("cal_status"), "n4": h.get("n4"), "backlog": h["backlog"], "backend": h["backend"],
                                "threads": h["threads"], "tiles": tiles}))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8811)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--secs", type=float, default=12.0)
    ap.add_argument("--view", default="g3")
    ap.add_argument("--only")
    a = ap.parse_args()
    cfg = load_config()
    cfg.port = a.port
    cfg.autostart = False
    cfg.gx_enabled = True
    app = create_app(cfg)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=a.port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(100):
        if server.started or not th.is_alive():
            break
        time.sleep(0.1)
    if not server.started:
        sys.exit("Server startet nicht (Port belegt?)")
    time.sleep(1.0)
    svc = app.state.svc
    for _ in range(200):          # Worker bereit (Numba-Übersetzung beim ersten Start)
        svc.gn.poll()
        if svc.gn.info:
            break
        time.sleep(0.1)
    print("Worker:", svc.gn.info)
    rows = asyncio.run(run(a.port, a.speed, a.secs, a.view, a.only))
    for name, r in rows:
        print(name)
        print("   ", json.dumps(r, ensure_ascii=False, default=str))
    server.should_exit = True
    th.join(timeout=5)


if __name__ == "__main__":
    main()
