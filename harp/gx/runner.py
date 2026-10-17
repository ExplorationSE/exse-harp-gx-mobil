"""GnRunner: GX-Rechenkern in einem eigenen Prozess (Worker).

Der Server schickt Zeitmarken-Blöcke (int64 ps, Kanal) über eine Queue; der Worker rechnet blockweise
(Numba nutzt dort alle Kerne, ohne die Ereignisschleife des Servers zu blockieren) und liefert nach jedem
gerechneten Block (höchstens alle ``out_interval_s``) ein Ergebnis zurück. Start per 'spawn' (wie unter Windows).

Seit 1.3.0-dev2: Der Worker kodiert die Karten g³/g⁴ selbst (``wire.encode_body``, dieselben Bytes wie zuvor im
Server) und schickt nur die komprimierten Nutzdaten statt der float64-Felder. Ein Lese-Thread im Server-Prozess
holt die Ergebnisse sofort ab und weckt den Server (``notify``), statt dass die Server-Schleife einmal je Frame
nachsieht. Zeitstempel (time.monotonic, systemweit): ``t_frame`` Ende der Messzeit des neuesten enthaltenen Frames,
``t_res`` Ergebnis im Worker fertig, ``t_srv`` im Server angekommen.
"""
from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
from collections import deque
from dataclasses import asdict

import numpy as np

from . import wire
from .engine import GnConfig, GnEngine


def _worker(inq, outq, out_interval_s: float) -> None:  # pragma: no cover - läuft im Kindprozess
    from . import kernels as K
    warm = K.warmup()
    outq.put(("ready", {**K.info(), "warmup_s": warm}))
    eng = GnEngine()
    last_out = 0.0
    dirty = False
    newest_stamp = 0.0
    newest_in = t_proc = 0.0
    tags_in = 0
    epoch = 0
    while True:
        # Ergebnis fällig, aber Mindestabstand noch nicht um: nur so lange warten (nicht pauschal 0,1 s)
        wait = max(0.0, out_interval_s - (time.monotonic() - last_out)) if dirty else 0.1
        try:
            msgs = [inq.get(timeout=wait)] if wait > 0 else [inq.get_nowait()]
        except queue.Empty:
            msgs = []
        while True:
            try:
                msgs.append(inq.get_nowait())
            except queue.Empty:
                break
        fed = False
        t_in = time.monotonic()
        for m in msgs:
            kind = m[0]
            if kind == "epoch":
                epoch = m[1]
                continue
            if kind == "stop":
                return
            if kind == "cfg":
                d = dict(m[1])
                if d.get("delays") is None:
                    d["delays"] = dict(eng.cfg.delays)
                    keep_cal = True
                else:
                    keep_cal = False
                cfg = GnConfig(**d)
                cal = (eng.cal_done, getattr(eng, "cal_status", "vorgegeben"), list(getattr(eng, "cal_missing", [])))
                eng.configure(cfg)
                if keep_cal:
                    eng.cal_done, eng.cal_status, eng.cal_missing = cal
                dirty = True
            elif kind == "reset":
                eng.reset(full=m[1])
                dirty = True
                newest_stamp = newest_in = t_proc = time.monotonic()   # Stand: direkt nach dem Zurücksetzen
            elif kind == "recal":
                eng.cfg.delays = {}
                eng.reset(full=True)
                eng.cal_done = not eng.cfg.auto_cal
                eng.cal_status, eng.cal_missing = "vorgegeben", []
                eng.clear_geo()
                dirty = True
                newest_stamp = newest_in = t_proc = time.monotonic()   # Stand: direkt nach dem Zurücksetzen
            elif kind == "ev":
                eng.feed(m[1], m[2])
                newest_stamp = m[3]
                newest_in = t_in
                tags_in += m[1].size
                fed = True
        if fed:
            eng.process()
            t_proc = time.monotonic()
            dirty = True
        now = time.monotonic()
        if dirty and now - last_out >= out_interval_s:
            r = eng.result()
            r["wire"] = {"g3": wire.encode_body({"map3": r.pop("map3")}),
                         "g4": wire.encode_body({"cube4": r.pop("cube4")})}
            r["stamp"] = newest_stamp
            r["t_frame"] = newest_stamp
            r["epoch"] = epoch
            r["backlog"] = inq.qsize() if hasattr(inq, "qsize") else 0
            r["t_in"], r["t_proc"] = newest_in, t_proc   # Block im Worker angekommen / gerechnet
            r["t_res"] = time.monotonic()
            outq.put(("res", r))
            last_out = now
            dirty = False


class GnRunner:
    t_stamps = True   # Ergebnisse tragen t_frame/t_res/t_srv (für tools/latency_gx.py)

    def __init__(self, out_interval_s: float = 0.5) -> None:
        self.out_interval_s = out_interval_s
        self._inbox: deque = deque()
        self._reader: threading.Thread | None = None
        self._notify = None
        self.proc: mp.Process | None = None
        self.info: dict = {}
        self.latest: dict | None = None
        self.cfg: GnConfig | None = None
        self.epoch = 0      # Ergebnisse älterer Konfigurationen (z. B. vorige Datei) werden verworfen

    def _new_epoch(self) -> None:
        self.epoch += 1
        self.latest = None
        self._put(("epoch", self.epoch))

    def start(self, notify=None) -> None:
        """Worker starten. notify (optional, thread-sicher aufrufbar): wird nach jedem eingetroffenen Ergebnis
        aus einem Lese-Thread gerufen; der Aufrufer holt es dann mit poll() ab (Push statt Abfragen im Takt)."""
        ctx = mp.get_context("spawn")
        self.inq = ctx.Queue()
        self.outq = ctx.Queue()
        self.proc = ctx.Process(target=_worker, args=(self.inq, self.outq, self.out_interval_s), daemon=True,
                                name="harp-gx-worker")
        self.proc.start()
        if notify is not None:
            self._notify = notify
            self._reader = threading.Thread(target=self._read, args=(self.proc, self.outq), daemon=True,
                                            name="harp-gx-reader")
            self._reader.start()

    def _read(self, proc, outq) -> None:
        while self.proc is proc:
            try:
                m = outq.get(timeout=0.5)
            except queue.Empty:
                if not proc.is_alive():
                    return
                continue
            except (OSError, EOFError, ValueError):
                return
            if m[0] == "res":
                m[1]["t_srv"] = time.monotonic()
            self._inbox.append(m)
            try:
                self._notify()
            except Exception:  # noqa: BLE001 - z. B. Ereignisschleife schon beendet
                return

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.is_alive()

    def configure(self, cfg: GnConfig, keep_delays: bool = True) -> None:
        self.cfg = cfg
        self._new_epoch()
        d = asdict(cfg)
        if keep_delays:
            d["delays"] = None
        self._put(("cfg", d))

    def reset(self, full: bool = False) -> None:
        self._new_epoch()
        self._put(("reset", full))

    def recalibrate(self) -> None:
        self._new_epoch()
        self._put(("recal",))

    def feed(self, t: np.ndarray, ch: np.ndarray, t_frame: float | None = None) -> None:
        """t_frame: Ende der Messzeit dieses Frames (time.monotonic); Standard: jetzt."""
        if t.size:
            self._put(("ev", np.ascontiguousarray(t, np.int64), np.ascontiguousarray(ch, np.int16),
                       time.monotonic() if t_frame is None else t_frame))

    def _put(self, m) -> None:
        if self.alive:
            self.inq.put(m)

    def poll(self) -> dict | None:
        """Neuestes Ergebnis (oder None, wenn keins neu ist)."""
        new = None
        while self.proc is not None:
            try:
                if self._reader is not None:
                    kind, payload = self._inbox.popleft()
                else:
                    kind, payload = self.outq.get_nowait()
                    if kind == "res":
                        payload["t_srv"] = time.monotonic()
            except (IndexError, queue.Empty, OSError, EOFError):
                break
            if kind == "ready":
                self.info = payload
            elif payload.get("epoch", self.epoch) == self.epoch:
                new = payload
        if new is not None:
            # Server-seitige Latenz bis hier; der Server setzt beim Absenden die endgültige (bis zum Client-Versand)
            new["latency_s"] = time.monotonic() - new.get("stamp", time.monotonic())
            self.latest = new
        return new

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self.inq.put(("stop",))
            self.proc.join(timeout=3)
        except Exception:
            pass
        if self.proc.is_alive():
            self.proc.terminate()
        self.proc = None
        self._reader = None
        self._inbox.clear()
