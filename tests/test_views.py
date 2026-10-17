"""Jede Ansicht bekommt, was sie braucht (seit 1.3.0-dev3).

Hintergrund: in 1.3.0-dev2 zeigte die g²-Ansicht nach jedem Datei-Umlauf „–“ und „0.0 s“ (leeres GX-Ergebnis direkt
nach dem Reset, Kopf nur mit 2 Hz), und Auswahlfelder zeigten nach der ersten Änderung die erste Option (5 ns).
Geprüft werden hier die Server-Nachrichten je Ansicht; tests/test_browser_smoke.py prüft dasselbe im Browser.
"""
import asyncio
import json
import tempfile
import time
from pathlib import Path

import pytest

from harp import server as S
from harp.config import Config
from harp.gx import wire
from harp.server import HarpService
from tests.test_gx_push import WS, fake_result, make
from tools.generate_gx import generate

VIEWS = ["hist", "trace", "corr", "g3", "g4"]
FRAME_KEYS = {"seq", "t_file_s", "progress", "acc_time_s", "mode", "bin_width_ps", "rebin_factor", "n_bins_full",
              "n_bins", "channels", "has_histogram", "first_channel", "hist_kind", "rates", "sync_rate",
              "total_counts", "calc_ms", "payload_bytes_prev", "payload_kBps", "corr_channels", "corr_ref",
              "corr_bin_ps", "corr_x0_ps", "corr_n_bins"}
HEAD_KEYS = {"tiles", "T_s", "win_ps", "range_ps", "period_ps", "delays", "cal_done", "cal_status", "geo", "backend",
             "latency_ms", "proc_mtags", "combo3", "combo4", "n3", "n4"}


@pytest.fixture(scope="module")
def cw_file(tmp_path_factory):
    d = tmp_path_factory.mktemp("views")
    return generate("thermal_cw", d / "Thermisch_cw.ptu", 1.5, seed=21)   # kurz: Umläufe im Test


def euler_order():
    edges = {a: [b for b in VIEWS if b != a] for a in VIEWS}
    stack, path = ["hist"], []
    while stack:
        u = stack[-1]
        if edges[u]:
            stack.append(edges[u].pop(0))
        else:
            path.append(stack.pop())
    return path[::-1]


def test_euler_order_covers_every_switch():
    o = euler_order()
    pairs = {(a, b) for a, b in zip(o, o[1:])}
    assert len(pairs) == 20 and all(a != b for a, b in pairs)


def test_lite_frame_keeps_everything_but_curves():
    msg = {"type": "frame", "seq": 3, "hist": [[1]], "corr": [[2]], "rates": [5.0], "acc_time_s": 1.0,
           "corr_channels": [2], "corr_ref": 1, "corr_x0_ps": -5, "calc_ms": 1.0, "total_counts": [7]}
    lite = json.loads(HarpService.lite_frame(msg))
    assert lite["lite"] is True and "hist" not in lite and "corr" not in lite
    assert {k: v for k, v in lite.items() if k != "lite"} == {k: v for k, v in msg.items() if k not in ("hist", "corr")}
    # Quelle ohne Korrelation: "corr": None bleibt, damit die g²-Ansicht den Hinweis zeigt
    assert json.loads(HarpService.lite_frame({**msg, "corr": None}))["corr"] is None


def test_each_client_view_gets_its_data():
    """Fünf Clients in fünf Ansichten gleichzeitig: Kurven nur wo sichtbar, g²-Kacheln bei jedem Ergebnis."""
    async def main():
        svc = HarpService(Config(log_dir=Path(tempfile.mkdtemp())))

        def build(*a):
            svc._frame_msg = {"type": "frame", "seq": 1, "hist": [[1, 2]], "corr": [[3, 4]], "rates": [1.0],
                              "acc_time_s": 0.3, "corr_channels": [2]}
            return json.dumps(svc._frame_msg)
        svc.build_frame = build
        cl = {v: make(svc, v) for v in VIEWS}
        r, _, _ = fake_result()
        r["tiles"] = [{"ch": [1, 2], "g": 1.9, "n": 100, "err": 0.01}]
        svc.gn_last = r
        await svc.broadcast_frame(None, None, None, 0, 0)
        for _ in range(3):        # drei Ergebnisse kurz hintereinander
            svc.gn_broadcast()
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
        for v, c in cl.items():
            f = c.ws.txt[-1]
            if v in ("hist", "corr"):
                assert f["hist"] == [[1, 2]] and f["corr"] == [[3, 4]] and not f.get("lite"), v
            else:
                assert f["lite"] and "hist" not in f and f["rates"] == [1.0] and f["acc_time_s"] == 0.3, v
            heads = [wire.decode(b) for b in c.ws.bins]
            assert heads, v
            h, arrays = heads[0]
            assert HEAD_KEYS <= set(h), (v, HEAD_KEYS - set(h))
            assert h["tiles"][0]["g"] == 1.9
            assert list(arrays) == {"g3": ["map3"], "g4": ["cube4"]}.get(v, []), v
        assert len(cl["corr"].ws.bins) == 3                # g²: jede Aktualisierung (Kacheln/Messzeit)
        assert len(cl["hist"].ws.bins) == len(cl["trace"].ws.bins) == 1   # Histo/Zeit: nur Infozeile, ≈ 2 Hz
        # Ansichtswechsel: g²-Kopf sofort (nicht erst beim nächsten Takt)
        c = cl["trace"]
        n = len(c.ws.bins)
        c.view = "corr"
        svc.gn_send_view(c)
        await asyncio.sleep(0.05)
        assert len(c.ws.bins) == n + 1
        for c in cl.values():
            c.stop()
    asyncio.run(main())


def _collect(ws, seconds):
    t0, frames, heads = time.monotonic(), [], []
    while time.monotonic() - t0 < seconds:
        m = ws.receive()
        if m.get("bytes"):
            heads.append(wire.decode(m["bytes"]))
        elif m.get("text"):
            d = json.loads(m["text"])
            if d.get("type") == "frame":
                frames.append(d)
    return frames, heads


def _check_view(v, frames, heads):
    assert frames, v
    full = [f for f in frames if not f.get("lite")]
    for f in frames:
        assert FRAME_KEYS <= set(f), (v, FRAME_KEYS - set(f))   # Zählraten, Messzeit, Infozeile in jeder Ansicht
        assert len(f["rates"]) == 4 and min(f["rates"]) > 0
    if v in ("hist", "corr"):
        assert full and full[-1]["hist"] and full[-1]["corr"], v
        assert sum(map(sum, full[-1]["corr"])) > 0 and sum(map(sum, full[-1]["hist"])) > 0
    else:
        assert any(f.get("lite") for f in frames), v
    assert heads, v
    for h, a in heads:
        assert HEAD_KEYS <= set(h)
        # nie ein leeres Ergebnis (gerade zurückgesetzt) – das zeigte „–“ und „0.0 s“
        assert h["T_s"] > 0 and h["tiles"], (v, h["T_s"], len(h["tiles"]))
    if v == "corr":
        pair = [t for t in heads[-1][0]["tiles"] if t["ch"] == [1, 2]]
        assert pair and pair[0]["g"] and pair[0]["g"] > 1.2   # thermisch: g² ≈ 2
    if v in ("g3", "g4"):
        assert any(("map3" if v == "g3" else "cube4") in a for _, a in heads), v


def test_all_views_end_to_end_every_switch_and_after_loop(tmp_path, cw_file):
    from fastapi.testclient import TestClient
    d = tmp_path / "data"; d.mkdir()
    (d / "cw.ptu").write_bytes(Path(cw_file).read_bytes())
    cfg = Config(data_dir=d, default_file="cw.ptu", log_dir=tmp_path / "logs", autostart=True,
                 defaults={"refresh_ms": 150, "speed": 1.0, "loop": True})
    cfg.gx_enabled = True
    with TestClient(S.create_app(cfg)) as cl, cl.websocket_connect("/ws") as ws:
        _collect(ws, 2.5)                                  # Worker warm, erste GX-Ergebnisse
        wraps, last_t = 0, None
        for v in euler_order():
            ws.send_json({"type": "view", "v": v})
            _collect(ws, 0.3)                              # Wechsel abwarten (noch alte Ansicht unterwegs)
            frames, heads = _collect(ws, 1.1)
            for f in frames:
                if last_t is not None and f["t_file_s"] < last_t:
                    wraps += 1
                last_t = f["t_file_s"]
            _check_view(v, frames, heads)
            acc = [f["acc_time_s"] for f in frames]
            assert any(b > a for a, b in zip(acc, acc[1:])), (v, acc)   # sammelt
        assert wraps >= 3                                  # mehrere Datei-Umläufe abgedeckt
