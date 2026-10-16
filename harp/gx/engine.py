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
CAL_MIN_T_PS = 2e12     # Kalibrierung nach 2 s Messzeit
MIN_COUNTS = 10         # darunter: Kachel gilt als „sammelt Daten“ (kein Zahlenwert)
# Automatische Fenster-/Bereichswahl (nur cw): grobe g²-Kurve ±5 µs, 10 ns, nach 0,5 s Messzeit
GEO_W = 5_000_000
GEO_BW = 10_000
GEO_NB = 2 * GEO_W // GEO_BW
GEO_MIN_T_PS = 0.5e12
GEO_WIN_FRAC = 6        # Fenster = FWHM/6
GEO_RANGE_FRAC = 3      # Bereich = ±3·FWHM
GEO_Q_PER_S = 100.0     # ohne Merkmal: Fenster so, dass ≈ 100 Quadrupel/s anfallen
GEO_WIN_MAX = 1_000_000
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
    auto_geom: bool = False     # cw: Fenster/Bereich einmalig aus der g²-Breite (bzw. Statistik) wählen
    backend: str | None = None


def _wc(ts, tx, d, w):
    return np.searchsorted(tx, ts + d + w / 2, "left") - np.searchsorted(tx, ts + d - w / 2, "left")


class GnEngine:
    def __init__(self, cfg: GnConfig | None = None) -> None:
        self.cfg = cfg or GnConfig()
        self.cal_done = not self.cfg.auto_cal or bool(self.cfg.delays)
        self.geo: dict | None = None
        self.geo_h = np.zeros(GEO_NB, np.int64)
        self.geo_T = 0.0
        self.reset(full=True)

    def _geo_active(self) -> bool:
        return self.cfg.auto_geom and self.cfg.period_ps <= 0 and self.geo is None

    def clear_geo(self) -> None:
        self.geo = None
        self.geo_h = np.zeros(GEO_NB, np.int64)
        self.geo_T = 0.0

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
        r = max(r, self._calgeom()[0] + 2 * dmax + 1000)
        if self._geo_active():
            r = max(r, GEO_W + 2 * dmax + 1000)
        return int(r)

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
        if not t.size:
            self._tmax = getattr(self, "_tmax", 0)
            return
        for k, x in K.split_channels(t, ch, self.cfg.channels, self.cfg.backend).items():
            self.buf[k] = np.concatenate([self.buf[k], x]) if k in self.buf else x
        self._tmax = int(t.max())

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
        # je Start-Kanal ein Aufruf: Schlüssel (Kanal, Pulsabstand) → Fensterzählungen, Terme = Produkte
        plan: dict[int, tuple[dict, list]] = {}
        for order in (2, 3, 4):
            for combo in itertools.combinations(sorted(chans), order):
                a, others = combo[0], combo[1:]
                keys, terms = plan.setdefault(a, ({}, []))
                sets = [(0,) * len(others)] + (list(SIDE_SETS) if P > 0 else [])
                for si, ks in enumerate(sets):
                    terms.append((combo, si, [keys.setdefault((x, k), len(keys)) for x, k in zip(others, ks)]))
        for a, (keys, terms) in plan.items():
            ts = cor[a][rng[a][0]:rng[a][1]]
            kl = list(keys)
            sums = K.tile_sums(ts, [cor[x] for x, _ in kl], [k * P for _, k in kl], w, [t[2] for t in terms], be)
            side: dict[tuple, float] = {}
            for (combo, si, _), v in zip(terms, sums):
                if si == 0:
                    self.center[combo] = self.center.get(combo, 0.0) + v
                else:
                    side[combo] = side.get(combo, 0.0) + v
            for combo, s in side.items():
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
        # Automatische Fenster-/Bereichswahl (cw)
        if self._geo_active():
            for a, b in itertools.combinations(sorted(chans), 2):
                ra = self.buf[a]
                i0, i1 = np.searchsorted(ra, self.done + d[a]), np.searchsorted(ra, horizon + d[a])
                self.geo_h += K.g2_hist(ra, self.buf[b], int(i0), int(i1), GEO_W, GEO_BW, GEO_NB, be)
            self.geo_T += span
            if self.geo_T >= GEO_MIN_T_PS:
                self._autogeom(chans)
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

    @staticmethod
    def _feature(h: np.ndarray, sm: int, nsig: float = 8.0):
        """Signifikantestes Merkmal (Peak/Dip) einer g²-Kurve: (Index, Halbwertsbreite in Bins) oder None."""
        h = h.astype(float)
        s = np.convolve(h, np.ones(sm) / sm, "same")[sm:-sm] if sm > 1 else h
        n = s.size
        edge = np.concatenate([s[: n // 10], s[-n // 10:]])
        base = float(np.median(edge))
        dev = s - base
        i = int(np.argmax(np.abs(dev)))
        sig = np.sqrt(max(base, 1.0) / sm)
        if abs(dev[i]) < nsig * sig or abs(dev[i]) < 0.1 * max(base, 1.0):
            return None
        half = abs(dev[i]) / 2
        sg = np.sign(dev[i])
        lo = i
        while lo > 0 and sg * dev[lo - 1] > half:
            lo -= 1
        hi = i
        while hi < n - 1 and sg * dev[hi + 1] > half:
            hi += 1
        return i + sm, hi - lo + 1

    def _autogeom(self, chans) -> None:
        """Fenster/Bereich für cw einmalig festlegen.
        Schmales Merkmal (feine Kalibrierkurve oder FWHM < 50 ns) → Standardwerte bleiben.
        Breites Merkmal → Fenster = FWHM/6, Bereich = ±3·FWHM. Kein Merkmal (z. B. Laser) → Fenster
        nach Statistik (≈ 100 Quadrupel/s), nur mit ≥ 3 Datenkanälen."""
        c = self.cfg
        old = (c.win_ps, c.range_ps)
        fwhm = None
        narrow = any(self._feature(h, 2 * CAL_SMOOTH, 6.0) is not None for h in self.cal.values()) if self.cal else False
        f = self._feature(self.geo_h, 3)
        if f is not None:
            fwhm = f[1] * GEO_BW
        basis = "Standard"
        if f is not None and fwhm >= 50_000 and not narrow:
            w = int(min(GEO_WIN_MAX, max(c.win_ps, fwhm / GEO_WIN_FRAC)))
            rg = int(min(5e7, max(c.range_ps, GEO_RANGE_FRAC * fwhm)))
            basis = "g2-Breite"
        elif narrow or f is not None:
            w, rg = old
            if fwhm is None:
                fwhm = 0
            basis = "Standard"
        else:
            data = [k for k in chans if k >= 1]
            T = max(self.T, 1.0) / 1e12
            r = sorted((self.n.get(k, 0) / T for k in data), reverse=True)
            if len(r) >= 3 and min(r[:3]) > 0:
                rr = r[:4] if len(r) >= 4 else r[:3]
                k = len(rr) - 1           # Anzahl Fensterfaktoren
                prod = float(np.prod(rr))
                w = (GEO_Q_PER_S / prod) ** (1 / k) * 1e12
                w = int(min(GEO_WIN_MAX, max(c.win_ps, w)))
                rg = int(min(5e7, max(c.range_ps, 3 * w)))
                basis = "Statistik"
            else:
                w, rg = old
        w = int(float(f"{w:.2g}")); rg = int(float(f"{rg:.2g}"))
        self.geo = {"basis": basis, "fwhm_ps": (None if fwhm is None else float(fwhm)), "win_ps": w,
                    "range_ps": rg, "changed": (w, rg) != old}
        if (w, rg) != old:
            c.win_ps, c.range_ps = w, rg
            self.reset(full=False)

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
        new = {k: v for k, v in delays.items() if v != 0.0}
        changed = new != self.cfg.delays
        self.cfg.delays = new
        self.cal_done = True
        self.cal_found = rel
        self._cal_changed = changed
        miss = sorted(k for k in chans if k not in delays)
        self.cal_status = "ok" if not miss else ("kein_merkmal" if len(delays) == 1 else "teilweise")
        if self.cal_status == "kein_merkmal" and self.geo and (self.geo.get("fwhm_ps") or 0) >= 30_000:
            self.cal_status = "unnoetig"   # breite Korrelation (≫ Kabelversatz): Laufzeiten vernachlässigbar
        self.cal_missing = miss if len(delays) > 1 else []
        if changed:
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
                "cal_missing": list(getattr(self, "cal_missing", [])), "geo": self.geo,
                "win_ps": c.win_ps, "range_set_ps": c.range_ps, "range_ps": self._w(c.nb3)[0], "range4_ps": self._w(c.nb4)[0],
                "bw3_ps": self._w(c.nb3)[1], "bw4_ps": self._w(c.nb4)[1], "n3": int(self.map3.sum()),
                "n4": int(self.cube4.sum()), "stats": dict(self.stats), "backend": K.active_backend(c.backend),
                "threads": K.n_threads(c.backend), "gpu_name": (K.GPU_INFO or {}).get("name"),
                "engine_note": K.FALLBACK_NOTE or K.gpu_note()}

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
