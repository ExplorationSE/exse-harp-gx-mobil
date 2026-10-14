"""GnEngine: fortlaufende (Streaming-)Berechnung von g⁽²⁾, g⁽³⁾, g⁽⁴⁾ aus Zeitmarken-Blöcken.

Blockverarbeitung mit Überlapp: Start-Marken werden erst ausgewertet, wenn ihr Fenster ±M vollständig
vorliegt (M = max. Reichweite: Kartenbereich, Seitenpeaks). Ein Rest von M bleibt als Überlapp im Puffer.
Ergebnis ist damit unabhängig von der Blockgröße (Test: tests/test_gx_engine.py).

Kabel-Laufzeiten: korrigierte Zeit = Rohzeit − delay[Kanal]. Automatische Kalibrierung: aus den
g⁽²⁾-Kurven aller Kanalpaare (±20 ns, 50 ps, geglättet 1 ns) wird je Paar das signifikanteste Merkmal
(Peak oder Dip) gesucht; die Laufzeiten folgen per Breitensuche ab dem Bezugskanal.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

import numpy as np

from . import kernels as K

CAL_W = 20_000          # ±20 ns
CAL_BW = 50             # 50 ps
CAL_NB = 2 * CAL_W // CAL_BW
CAL_SMOOTH = 20         # 1 ns
CAL_MIN_T_PS = 2e12
MIN_COUNTS = 10       # darunter: Kachel gilt als „sammelt Daten“ (kein Zahlenwert)     # Kalibrierung nach 2 s Messzeit
SIDE_SETS = [(1, 2, 3), (-1, -2, -3), (2, 3, 1), (-2, -3, -1)]


@dataclass
class GnConfig:
    channels: list[int] = field(default_factory=lambda: [1, 2, 3, 4])
    combo3: tuple[int, int, int] = (1, 2, 3)
    combo4: tuple[int, int, int, int] = (1, 2, 3, 4)
    range_ps: int = 25_000      # Kartenbereich ±range
    nb3: int = 129             # ungerade → mittlerer Bin zentriert auf τ = 0
    nb4: int = 33
    win_ps: int = 2_000         # Koinzidenzfenster der Kacheln (Breite)
    period_ps: float = 0.0      # > 0: gepulst → Seitenpeak-Normierung
    delays: dict[int, float] = field(default_factory=dict)
    auto_cal: bool = True
    backend: str | None = None


def _wc(ts, tx, d, w):
    return np.searchsorted(tx, ts + d + w / 2, "left") - np.searchsorted(tx, ts + d - w / 2, "left")


class GnEngine:
    def __init__(self, cfg: GnConfig | None = None) -> None:
        self.cfg = cfg or GnConfig()
        self.cal_done = not self.cfg.auto_cal or bool(self.cfg.delays)
        self.reset(full=True)

    # ------------------------------------------------------------ Konfiguration
    def configure(self, cfg: GnConfig) -> None:
        geom = (cfg.range_ps, cfg.nb3, cfg.nb4, cfg.win_ps, cfg.period_ps, tuple(cfg.combo3), tuple(cfg.combo4),
                tuple(sorted(cfg.delays.items())), tuple(cfg.channels))
        old = (self.cfg.range_ps, self.cfg.nb3, self.cfg.nb4, self.cfg.win_ps, self.cfg.period_ps,
               tuple(self.cfg.combo3), tuple(self.cfg.combo4), tuple(sorted(self.cfg.delays.items())),
               tuple(self.cfg.channels))
        if cfg.delays != self.cfg.delays:
            # Laufzeiten vorgegeben → keine Auto-Kalibrierung; leer → neu kalibrieren (falls auto_cal)
            self.cal_done = bool(cfg.delays) or not cfg.auto_cal
            self.cal_status, self.cal_missing = "vorgegeben", []
            self.cal = {}
            self.cal_T = 0.0
        self.cfg = cfg
        if geom != old:
            self.reset(full=False)

    @property
    def W3(self):
        return self._w(self.cfg.nb3)

    def _w(self, nb):
        bw = 2 * max(1, int(round(self.cfg.range_ps / nb)))   # gerade Binbreite → W = bw·nb/2 ganzzahlig
        return bw * nb // 2, bw

    @property
    def reach(self) -> int:
        r = self.cfg.range_ps + self.cfg.win_ps
        if self.cfg.period_ps > 0:
            r = max(r, int(3 * self.cfg.period_ps + self.cfg.win_ps))
        dmax = max([abs(v) for v in self.cfg.delays.values()], default=0)
        return int(max(r, self._calgeom()[0] + 2 * dmax + 1000))

    def reset(self, full: bool = False) -> None:
        """Akkumulatoren leeren. full=True: auch Puffer und Kalibrierung (neue Datei / Rücksprung)."""
        c = self.cfg
        if full:
            self.buf: dict[int, np.ndarray] = {}
            self.done: int | None = None
            self.cal = {}
            self.cal_T = 0.0
            self._tmax = 0
        self.T = 0.0
        self.n = {}
        self.map3 = np.zeros((c.nb3, c.nb3), np.int64)
        self.cube4 = np.zeros((c.nb4, c.nb4, c.nb4), np.int64)
        self.center: dict[tuple, float] = {}
        self.side: dict[tuple, float] = {}
        self.stats = {"tags": 0, "proc_s": 0.0, "batches": 0}

    # ------------------------------------------------------------ Daten
    def feed(self, t: np.ndarray, ch: np.ndarray) -> None:
        t = np.asarray(t, np.int64); ch = np.asarray(ch)
        for k in np.unique(ch):
            k = int(k)
            if k not in self.cfg.channels:
                continue
            x = t[ch == k]
            self.buf[k] = np.concatenate([self.buf[k], x]) if k in self.buf else x
        self._tmax = int(t.max()) if t.size else getattr(self, "_tmax", 0)

    def _corr(self, k):
        return self.buf[k] - int(round(self.cfg.delays.get(k, 0.0)))

    def process(self) -> bool:
        """Wertet alle vollständig abgedeckten Start-Marken aus. True, wenn etwas berechnet wurde."""
        chans = [k for k in self.cfg.channels if k in self.buf and self.buf[k].size]
        if len(chans) < 2:
            return False
        M = self.reach
        d = {k: int(round(self.cfg.delays.get(k, 0.0))) for k in chans}
        tmax = self._tmax
        horizon = min(tmax - d[k] for k in chans) - M
        if self.done is None:
            self.done = min(int(self.buf[k][0]) - d[k] for k in chans) + M
        if horizon <= self.done:
            return False
        t0 = time.perf_counter()
        cor = {k: self.buf[k] - d[k] for k in chans}
        rng = {k: (int(np.searchsorted(cor[k], self.done)), int(np.searchsorted(cor[k], horizon))) for k in chans}
        ntags = sum(i1 - i0 for i0, i1 in rng.values())
        span = horizon - self.done
        self.T += span
        for k in chans:
            self.n[k] = self.n.get(k, 0) + rng[k][1] - rng[k][0]
        be = self.cfg.backend
        c3, c4 = tuple(self.cfg.combo3), tuple(self.cfg.combo4)
        if all(k in cor for k in c3) and len(set(c3)) == 3:
            W, BW = self._w(self.cfg.nb3)
            a = c3[0]
            self.map3 += K.g3_hist(cor[a], cor[c3[1]], cor[c3[2]], *rng[a], W, BW, self.cfg.nb3, be)
        if all(k in cor for k in c4) and len(set(c4)) == 4:
            W, BW = self._w(self.cfg.nb4)
            a = c4[0]
            self.cube4 += K.g4_hist(cor[a], cor[c4[1]], cor[c4[2]], cor[c4[3]], *rng[a], W, BW, self.cfg.nb4, be)
        # Kacheln: alle Kombinationen (Paare, Tripel, Quadrupel) bei τ = 0
        w = self.cfg.win_ps
        P = self.cfg.period_ps
        wc_cache: dict[tuple, np.ndarray] = {}

        def wc(a, x, k):   # Fensterzählungen je Start-Marke, einmal je (Start, Kanal, Pulsabstand)
            key = (a, x, k)
            if key not in wc_cache:
                ts = cor[a][rng[a][0]:rng[a][1]]
                wc_cache[key] = K.window_counts(ts, cor[x], k * P, w, be)
            return wc_cache[key]

        for order in (2, 3, 4):
            for combo in itertools.combinations(sorted(chans), order):
                a, others = combo[0], combo[1:]
                prod = wc(a, others[0], 0).copy()
                for x in others[1:]:
                    prod *= wc(a, x, 0)
                self.center[combo] = self.center.get(combo, 0.0) + float(prod.sum())
                if P > 0:
                    s = 0.0
                    for ks in SIDE_SETS:
                        prod = wc(a, others[0], ks[0]).copy()
                        for x, k in zip(others[1:], ks[1:]):
                            prod *= wc(a, x, k)
                        s += float(prod.sum())
                    self.side[combo] = self.side.get(combo, 0.0) + s / len(SIDE_SETS)
        # Kalibrierung (Rohzeiten, alle Paare)
        if not self.cal_done:
            for a, b in itertools.combinations(sorted(chans), 2):
                ra = self.buf[a]
                i0, i1 = np.searchsorted(ra, self.done + d[a]), np.searchsorted(ra, horizon + d[a])
                cw_, cbw, cnb = self._calgeom()
                h = K.g2_hist(ra, self.buf[b], int(i0), int(i1), cw_, cbw, cnb, be)
                self.cal[(a, b)] = self.cal.get((a, b), 0) + h
            self.cal_T += span
            if self.cal_T >= CAL_MIN_T_PS:
                self._calibrate(chans)
        # Überlapp behalten
        keep_from = horizon - M
        for k in chans:
            i = int(np.searchsorted(cor[k], keep_from))
            if i:
                self.buf[k] = self.buf[k][i:]
        self.done = horizon
        dt = time.perf_counter() - t0
        self.stats["tags"] += ntags
        self.stats["proc_s"] += dt
        self.stats["batches"] += 1
        self.stats["last_ms"] = dt * 1000
        self.stats["last_tags"] = ntags
        return True

    def _calgeom(self):
        P = self.cfg.period_ps
        W = CAL_W if P <= 0 else int(min(max(CAL_W, 1.5 * P), 5e6))
        bw = max(CAL_BW, int(np.ceil(2 * W / 60000)))
        nb = 2 * W // bw
        return nb * bw // 2, bw, nb

    def _calibrate(self, chans) -> None:
        rel = {}
        W, bw, nb = self._calgeom()
        tau_c = (np.arange(nb) + 0.5) * bw - W
        P = self.cfg.period_ps
        sm = max(1, int(round(1000 / bw)))
        ker = np.ones(sm)
        for (a, b), h in self.cal.items():
            h = h.astype(float)
            if P > 0:   # gepulst: auf eine Periode falten → Kamm-Phase (funktioniert auch bei Antibunching)
                ph = np.mod(tau_c + P / 2, P) - P / 2
                fb = max(1, int(round(P / bw)))
                x = np.bincount(np.clip(((ph + P / 2) / P * fb).astype(int), 0, fb - 1), weights=h, minlength=fb)
                xc = (np.arange(fb) + 0.5) * P / fb - P / 2
                s = np.convolve(np.concatenate([x[-sm:], x, x[:sm]]), ker, "same")[sm:-sm]
                i = int(np.argmax(s))
                if s[i] < 6 * np.sqrt(np.median(s) + 1) + np.median(s):
                    continue
                lo, hi = i - sm, i + sm + 1
                idx = np.arange(lo, hi) % fb
                wgt = np.clip(x[idx] - np.median(x), 0, None)
                if wgt.sum() <= 0:
                    continue
                off = (xc[i] + (np.arange(lo, hi) - i) * (P / fb))
                rel[(a, b)] = float((off * wgt).sum() / wgt.sum())
                continue
            s = np.convolve(h, ker, "same")
            core = s[sm:-sm]
            med = np.median(core)
            dev = core - med
            i = int(np.argmax(np.abs(dev)))
            if abs(dev[i]) > 6 * np.sqrt(med + 1) and abs(dev[i]) > 0.15 * (med + 1):
                j = i + sm
                r = sm if dev[i] > 0 else 4 * sm      # Dips sind breit (Antibunching) → breiterer Schwerpunkt
                sl = slice(max(0, j - r), min(nb, j + r + 1))
                wgt = np.clip(np.sign(dev[i]) * (h[sl] - med / sm), 0, None)
                rel[(a, b)] = float((tau_c[sl] * wgt).sum() / wgt.sum()) if wgt.sum() > 0 else float(tau_c[j])
        ref = min(chans, key=lambda k: (k == 0, k))
        delays = {ref: 0.0}
        changed = True
        while changed:
            changed = False
            for (a, b), tau in rel.items():
                if a in delays and b not in delays:
                    delays[b] = delays[a] + tau; changed = True
                elif b in delays and a not in delays:
                    delays[a] = delays[b] - tau; changed = True
        delays = {k: round(v / 10) * 10.0 for k, v in delays.items()}
        self.cfg.delays = {k: v for k, v in delays.items() if v != 0.0}
        self.cal_done = True
        self.cal_found = rel
        miss = sorted(k for k in chans if k not in delays)
        self.cal_status = "ok" if not miss else ("kein_merkmal" if len(delays) == 1 else "teilweise")
        self.cal_missing = miss if len(delays) > 1 else []
        self.reset(full=False)

    # ------------------------------------------------------------ Ergebnis
    def result(self) -> dict:
        c = self.cfg
        T = self.T
        tiles = []
        for combo, cnt in self.center.items():
            if c.period_ps > 0:
                side = self.side.get(combo, 0.0)
                g = cnt / side if side > 0 else float("nan")
            else:
                acc = self.n.get(combo[0], 0) * np.prod([self.n.get(x, 0) / T * c.win_ps if T > 0 else 0
                                                          for x in combo[1:]])
                g = cnt / acc if acc > 0 else float("nan")
            if cnt < MIN_COUNTS:
                g = float("nan")
            tiles.append({"ch": list(combo), "g": g, "n": cnt, "low": cnt < MIN_COUNTS,
                          "err": (g / np.sqrt(cnt) if cnt > 0 and np.isfinite(g) else None)})
        for combo, cnt in self.center.items():   # Heralded g²: K0 als Herald
            if len(combo) == 3 and combo[0] == 0:
                n1 = self.center.get((0, combo[1]), 0.0); n2 = self.center.get((0, combo[2]), 0.0)
                nh = self.n.get(0, 0)
                g = nh * cnt / (n1 * n2) if n1 > 0 and n2 > 0 and cnt >= MIN_COUNTS else float("nan")
                tiles.append({"ch": list(combo), "g": g, "n": cnt, "low": cnt < MIN_COUNTS, "kind": "g2h",
                              "err": (g / np.sqrt(cnt) if cnt > 0 and np.isfinite(g) else None)})
        return {"T_s": T / 1e12, "tiles": tiles, "map3": self._norm(self.map3, c.combo3, c.nb3),
                "cube4": self._norm(self.cube4, c.combo4, c.nb4), "delays": dict(c.delays),
                "cal_done": self.cal_done,
                "cal_status": (getattr(self, "cal_status", "vorgegeben") if self.cal_done else "läuft"),
                "cal_missing": list(getattr(self, "cal_missing", [])), "range_ps": self._w(c.nb3)[0], "range4_ps": self._w(c.nb4)[0],
                "bw3_ps": self._w(c.nb3)[1], "bw4_ps": self._w(c.nb4)[1], "n3": int(self.map3.sum()),
                "n4": int(self.cube4.sum()), "stats": dict(self.stats), "backend": c.backend or K.BACKEND}

    def _norm(self, h: np.ndarray, combo, nb) -> np.ndarray:
        """cw: g = N / (N_a · Π N_x/T · BW). Gepulst: zusätzlich auf die mittlere Seitenpeak-Höhe skaliert."""
        T = self.T
        W, BW = self._w(nb)
        acc = self.n.get(combo[0], 0) * np.prod([self.n.get(x, 0) / T * BW if T > 0 else 0 for x in combo[1:]])
        g = np.full(h.shape, np.nan, np.float32)
        if acc <= 0:
            return g
        g = (h / acc).astype(np.float32)
        g[h == 0] = np.nan
        P = self.cfg.period_ps
        if P > 0:
            m = h.ndim
            vals = []
            ks_all = [k for k in (1, -1, 2, -2, 3, -3) if abs(k * P) + BW <= W]
            for ks in itertools.islice(itertools.permutations(ks_all, m), 24):
                idx = [int((k * P + W) // BW) for k in ks]
                if all(0 <= i < nb for i in idx):
                    sl = tuple(slice(max(0, i - 1), i + 2) for i in idx)
                    v = np.nanmax(np.where(np.isnan(g[sl]), -1, g[sl]))
                    if v > 0:
                        vals.append(v)
            if vals:
                g = g / np.float32(np.mean(vals))
        return g
