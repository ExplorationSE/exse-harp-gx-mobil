"""g³/g⁴-Frames per Push (seit 1.3.0): sofort nach jedem Ergebnis, nur die sichtbare Ansicht, Bandbreite je
Client begrenzt, Frames ohne unsichtbare Kurven, ehrliche Latenz-Zeitstempel."""
import asyncio
import json
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

from harp import server as S
from harp.config import Config
from harp.gx import wire
from harp.server import Client, HarpService
from tools.generate_gx import generate


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("gxp")
    return {"thermal_pulsed": generate("thermal_pulsed", d / "tp.ptu", 3, seed=33)}


class WS:
    def __init__(self):
        self.txt, self.bins = [], []

    async def send_text(self, t):
        self.txt.append(json.loads(t))

    async def send_bytes(self, b):
        self.bins.append(b)

    async def close(self, code=1000):
        pass


def make(svc, view):
    c = Client(WS(), "test", on_dead=svc.remove_client)
    c.view = view
    svc.clients[c.id] = c
    c.start()
    return c


def fake_result():
    rng = np.random.default_rng(1)
    m3, c4 = 1 + rng.random((129, 129)), 1 + rng.random((33, 33, 33))
    t = time.monotonic()
    return {"tiles": [], "stats": {"tags": 10, "proc_s": 1.0}, "T_s": 1.0, "range_ps": 900_000, "range4_ps": 900_000,
            "bw3_ps": 1, "bw4_ps": 1, "n3": 5, "n4": 5, "delays": {}, "cal_done": True, "backend": "rust",
            "wire": {"g3": wire.encode_body({"map3": m3}), "g4": wire.encode_body({"cube4": c4})},
            "t_frame": t - 0.02, "t_in": t - 0.015, "t_proc": t - 0.008, "t_res": t - 0.005, "t_srv": t - 0.004,
            "stamp": t - 0.02, "epoch": 0}, m3, c4


def test_wire_assemble_equals_encode():
    a = {"map3": 1 + np.random.default_rng(2).random((9, 9))}
    assert wire.assemble({"x": 1}, *wire.encode_body(a)) == wire.encode({"x": 1}, a)


def test_token_bucket_limits_average_rate():
    c = Client(WS(), "t")
    t, sent = 0.0, 0
    c.gx_t = t
    for _ in range(100):                     # 10 s lang alle 0,1 s ein 50-kB-Frame bei 200 kB/s
        t += 0.1
        sent += c.gx_allow(50_000, t, kbps=200)
    assert 38 <= sent <= 42                  # ≈ 200 kB/s · 10 s / 50 kB = 40


def test_push_only_visible_view_and_honest_latency():
    async def main():
        svc = HarpService(Config(log_dir=Path(tempfile.mkdtemp())))
        r, m3, c4 = fake_result()
        svc.gn_last = r
        g4, g3, hist = make(svc, "g4"), make(svc, "g3"), make(svc, "hist")
        svc.gn_broadcast()
        svc.gn_broadcast()                   # sofort danach: über dem Budget (g⁴), Kopf für „hist“ erst nach 0,5 s
        await asyncio.sleep(0.05)
        h4, a4 = wire.decode(g4.ws.bins[0])
        h3, a3 = wire.decode(g3.ws.bins[0])
        assert list(a4) == ["cube4"] and list(a3) == ["map3"]          # nur die sichtbare Karte
        assert np.allclose(a4["cube4"], c4, rtol=3e-4) and np.allclose(a3["map3"], m3, rtol=3e-4)
        assert len(hist.ws.bins) == 1 and wire.decode(hist.ws.bins[0])[1] == {}   # nur Kopf
        assert len(g4.ws.bins) == 1 and len(g3.ws.bins) == 1           # direkt danach: über dem Budget
        assert h4["t_frame"] <= h4["t_in"] <= h4["t_proc"] <= h4["t_res"] <= h4["t_srv"] <= h4["t_send"]
        assert abs(h4["latency_ms"] - (h4["t_send"] - h4["t_frame"]) * 1000) < 0.2
        # Budget: mehr als ≈ 200 kB/s werden übersprungen
        for _ in range(20):
            svc.gn_broadcast()
        await asyncio.sleep(0.05)
        assert len(g4.ws.bins) == 1
        g4.gx_t -= 1.0                       # 1 s später: Budget wieder da
        svc.gn_broadcast()
        await asyncio.sleep(0.05)
        assert len(g4.ws.bins) == 2
        for c in (g4, g3, hist):
            c.stop()
    asyncio.run(main())


def test_lite_frames_and_full_frame_on_view_switch():
    async def main():
        svc = HarpService(Config(log_dir=Path(tempfile.mkdtemp())))

        def build(*a):
            svc._frame_msg = {"type": "frame", "seq": 1, "hist": [[1, 2]], "corr": [[3]], "rates": [1.0]}
            return json.dumps(svc._frame_msg)
        svc.build_frame = build
        g4, hist = make(svc, "g4"), make(svc, "hist")
        await svc.broadcast_frame(None, None, None, 0, 0)
        await asyncio.sleep(0.05)
        lite, full = g4.ws.txt[-1], hist.ws.txt[-1]
        assert lite["lite"] and "hist" not in lite and "corr" not in lite and lite["rates"] == [1.0]
        assert full["hist"] == [[1, 2]] and not full.get("lite")
        for c in (g4, hist):
            c.stop()
    asyncio.run(main())


def test_server_pushes_gx_frames_at_frame_rate(tmp_path, files):
    """Ende zu Ende: g³-Frames kommen deutlich öfter als früher (2 Hz) und mit kurzer Latenz."""
    from fastapi.testclient import TestClient
    d = tmp_path / "data"; d.mkdir()
    (d / "tp.ptu").write_bytes(Path(files["thermal_pulsed"]).read_bytes())
    cfg = Config(data_dir=d, default_file="tp.ptu", log_dir=tmp_path / "logs", autostart=True,
                 defaults={"refresh_ms": 150, "speed": 1.0})
    cfg.gx_enabled = True
    with TestClient(S.create_app(cfg)) as cl, cl.websocket_connect("/ws") as ws:
        ws.send_json({"type": "view", "v": "g3"})
        t0, heads, lite_seen = time.monotonic(), [], False
        while time.monotonic() - t0 < 90 and len(heads) < 12:
            m = ws.receive()
            if m.get("bytes"):
                h, a = wire.decode(m["bytes"])
                if "map3" in a and h.get("t_frame"):
                    heads.append((time.monotonic(), h))
            elif m.get("text") and m["text"].startswith('{"type":"frame"'):
                lite_seen |= bool(json.loads(m["text"]).get("lite"))
        ws.send_json({"type": "view", "v": "hist"})
        full = None
        for _ in range(50):
            m = ws.receive()
            if m.get("text") and m["text"].startswith('{"type":"frame"'):
                f = json.loads(m["text"])
                if not f.get("lite"):
                    full = f
                    break
    assert len(heads) >= 12 and lite_seen and full is not None and "hist" in full
    last = heads[-8:]
    rate = (len(last) - 1) / (last[-1][0] - last[0][0])
    assert rate > 2.5, rate                                       # früher ≈ 1,6–2 Hz
    for _, h in last:
        assert h["t_frame"] <= h["t_res"] <= h["t_srv"] <= h["t_send"]
        assert 0 < h["latency_ms"] < 1000
