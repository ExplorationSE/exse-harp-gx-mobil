"""GnRunner: GX-Rechenkern in einem eigenen Prozess (Worker).

Der Server schickt Zeitmarken-Blöcke (int64 ps, Kanal) über eine Queue; der Worker rechnet blockweise
(Numba nutzt dort alle Kerne, ohne die Ereignisschleife des Servers zu blockieren) und liefert
höchstens alle ``out_interval_s`` ein Ergebnis zurück (latest-only). Start per 'spawn' (wie unter Windows).
"""
from __future__ import annotations

import multiprocessing as mp
import queue
import time
from dataclasses import asdict

import numpy as np

from .engine import GnConfig, GnEngine


def _worker(inq, outq, out_interval_s: float) -> None:  # pragma: no cover - läuft im Kindprozess
    from . import kernels as K
    warm = K.warmup()
    outq.put(("ready", {"backend": K.BACKEND, "threads": K.n_threads(), "warmup_s": warm}))
    eng = GnEngine()
    last_out = 0.0
    dirty = False
    newest_stamp = 0.0
    tags_in = 0
    epoch = 0
    while True:
        try:
            msgs = [inq.get(timeout=0.1)]
        except queue.Empty:
            msgs = []
        while True:
            try:
                msgs.append(inq.get_nowait())
            except queue.Empty:
                break
        fed = False
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
            elif kind == "recal":
                eng.cfg.delays = {}
                eng.reset(full=True)
                eng.cal_done = not eng.cfg.auto_cal
                eng.cal_status, eng.cal_missing = "vorgegeben", []
                eng.clear_geo()
                dirty = True
            elif kind == "ev":
                eng.feed(m[1], m[2])
                newest_stamp = m[3]
                tags_in += m[1].size
                fed = True
        if fed:
            eng.process()
            dirty = True
        now = time.monotonic()
        if dirty and now - last_out >= out_interval_s:
            r = eng.result()
            r["stamp"] = newest_stamp
            r["epoch"] = epoch
            r["backlog"] = inq.qsize() if hasattr(inq, "qsize") else 0
            outq.put(("res", r))
            last_out = now
            dirty = False


class GnRunner:
    def __init__(self, out_interval_s: float = 0.5) -> None:
        self.out_interval_s = out_interval_s
        self.proc: mp.Process | None = None
        self.info: dict = {}
        self.latest: dict | None = None
        self.cfg: GnConfig | None = None
        self.epoch = 0      # Ergebnisse älterer Konfigurationen (z. B. vorige Datei) werden verworfen

    def _new_epoch(self) -> None:
        self.epoch += 1
        self.latest = None
        self._put(("epoch", self.epoch))

    def start(self) -> None:
        ctx = mp.get_context("spawn")
        self.inq = ctx.Queue()
        self.outq = ctx.Queue()
        self.proc = ctx.Process(target=_worker, args=(self.inq, self.outq, self.out_interval_s), daemon=True,
                                name="harp-gx-worker")
        self.proc.start()

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

    def feed(self, t: np.ndarray, ch: np.ndarray) -> None:
        if t.size:
            self._put(("ev", np.ascontiguousarray(t, np.int64), np.ascontiguousarray(ch, np.int16), time.monotonic()))

    def _put(self, m) -> None:
        if self.alive:
            self.inq.put(m)

    def poll(self) -> dict | None:
        """Neuestes Ergebnis (oder None, wenn keins neu ist)."""
        new = None
        while self.proc is not None:
            try:
                kind, payload = self.outq.get_nowait()
            except (queue.Empty, OSError, EOFError):
                break
            if kind == "ready":
                self.info = payload
            elif payload.get("epoch", self.epoch) == self.epoch:
                new = payload
        if new is not None:
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
