"""Server-Pfad im Rust-Kern (seit 1.3.0-dev): bit-identisch zu den NumPy-Fassungen (Dekoder, T2-Histogramm,
g²-Korrelation mit Tail, Zählraten) – auf Zufallsdaten mit Randfällen und auf allen Demodateien."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from harp import _core
from harp import histogram as H
from harp.ptu import RECORD_TYPES, Events, StreamDecoder
from harp.sources.base import AcqParams
from harp.sources.pure_ptu import PurePythonPtuSource

core = _core.CORE
pytestmark = pytest.mark.skipif(core is None, reason="harp_gx_core ≥ 1.3.0-dev nicht installiert")
DATA = Path(__file__).resolve().parent.parent / "data"


def _same_events(a: Events, b: Events):
    assert a.time.dtype == b.time.dtype and a.channel.dtype == b.channel.dtype and a.dtime.dtype == b.dtime.dtype
    np.testing.assert_array_equal(a.time, b.time)
    np.testing.assert_array_equal(a.channel, b.channel)
    np.testing.assert_array_equal(a.dtime, b.dtime)
    assert a.markers == b.markers


@pytest.mark.parametrize("rt", sorted(RECORD_TYPES))
def test_decoder_random_records(rt):
    rng = np.random.default_rng(rt & 0xFFFF)
    rec = rng.integers(0, 2 ** 32, 20000, dtype=np.uint64).astype(np.uint32)
    # gehäuft Sonderrecords (Overflow mit 0/1/n, Marker, Sync)
    sp = rng.random(rec.size) < 0.3
    rec[sp] |= np.uint32(1 << 31)
    if RECORD_TYPES[rt][2] == "pt":
        rec[rng.random(rec.size) < 0.2] |= np.uint32(0xF << 28)
    else:
        o = rng.random(rec.size) < 0.1
        rec[o] = (rec[o] | np.uint32(0xFE000000)) & np.uint32(0xFE000003)
    d1, d2 = StreamDecoder(rt), StreamDecoder(rt)
    d1.ofl = d2.ofl = 12345
    for part in np.array_split(rec, 3):
        _same_events(d1._decode_rust(core, part), d1_np := d2._decode_np(part))
        assert d1.ofl == d2.ofl
        assert len(d1_np) > 0


def _rand_events(rng, n, nch, first, t0=0, rate=1.0, ties=True):
    t = t0 + np.cumsum(rng.geometric(min(1.0, rate), n) - (1 if ties else 0)).astype(np.int64)
    c = rng.integers(first - 1 if first > 0 else 0, nch + 2, n).astype(np.int16)   # auch Kanäle außerhalb
    return Events(t, c, np.zeros(n, np.int32))


@pytest.mark.parametrize("first,start", [(1, 0), (1, 1), (1, 3), (0, 0)])
@pytest.mark.parametrize("binning,nbins", [(0, 1024), (3, 777), (9, 4096)])
def test_histogram_t2_equal(first, start, binning, nbins):
    rng = np.random.default_rng(binning * 10 + first + start)
    last_a = last_b = None
    t0 = 0
    for f in range(6):
        ev = _rand_events(rng, 0 if f == 2 else 5000, 4, first, t0, rate=0.002)
        if len(ev):
            t0 = int(ev.time[-1])
        if f == 4:   # Frame ohne Start-Ereignis
            ev = Events(ev.time, np.where(ev.channel == start, start + 1, ev.channel).astype(np.int16), ev.dtime)
        ha, last_a, sa = H.histogram_t2(ev, 4, binning, nbins, last_a, start, first)
        hb, last_b, sb = H._histogram_t2_np(ev, 4, binning, nbins, last_b, start, first)
        assert ha.dtype == hb.dtype
        np.testing.assert_array_equal(ha, hb)
        assert (last_a, sa) == (last_b, sb)


def test_histogram_t2_no_start_ever():
    ev = Events(np.arange(10, dtype=np.int64), np.full(10, 2, np.int16), np.zeros(10, np.int32))
    ra = H.histogram_t2(ev, 4, 0, 1024, None, 1, 1)
    rb = H._histogram_t2_np(ev, 4, 0, 1024, None, 1, 1)
    np.testing.assert_array_equal(ra[0], rb[0])
    assert ra[1:] == rb[1:]


@pytest.mark.parametrize("first,ref", [(1, 1), (1, 3), (0, 0), (0, 2), (1, 9)])
@pytest.mark.parametrize("bw,nbins", [(1, 2048), (7, 2048), (64, 101), (1000, 16)])
def test_correlate_equal_with_tail(first, ref, bw, nbins):
    rng = np.random.default_rng(bw + nbins + 10 * first + ref)
    ta = tb = None
    t0 = 0
    for f in range(8):
        n = [3000, 0, 1, 3000, 50, 3000, 2, 3000][f]
        ev = _rand_events(rng, n, 4, first, t0, rate=0.05 if f % 2 else 0.3)
        if n:
            t0 = int(ev.time[-1]) + (0 if f != 5 else 10 * bw * nbins)   # auch Lücke > W
        ca, ta = H.correlate(ev.time, ev.channel, 4, bw, nbins, ta, ref, first)
        cb, tb = H._correlate_np(ev.time, ev.channel, 4, bw, nbins, tb, ref, first)
        assert ca.dtype == cb.dtype
        np.testing.assert_array_equal(ca, cb)
        for x, y in zip(ta, tb):
            assert x.dtype == y.dtype
            np.testing.assert_array_equal(x, y)


def test_correlate_wide_window_parallel_blocks():
    rng = np.random.default_rng(7)
    ev = _rand_events(rng, 200_000, 4, 1, 0, rate=0.5)
    ca, ta = H.correlate(ev.time, ev.channel, 4, 1, 2048, None, 1, 1)
    cb, tb = H._correlate_np(ev.time, ev.channel, 4, 1, 2048, None, 1, 1)
    np.testing.assert_array_equal(ca, cb)
    np.testing.assert_array_equal(ta[0], tb[0])
    assert ca.sum() > 1_000_000


def test_counts_equal():
    rng = np.random.default_rng(3)
    ev = _rand_events(rng, 10000, 4, 1)
    for first in (0, 1):
        np.testing.assert_array_equal(H.counts_per_channel(ev, 4, first), H._counts_per_channel_np(ev, 4, first))


@pytest.mark.parametrize("path", sorted(DATA.glob("*.ptu")), ids=lambda p: p.stem[17:45])
def test_read_frame_equal_on_demo_files(path, monkeypatch):
    def run(c):
        monkeypatch.setattr(_core, "CORE", c)
        s = PurePythonPtuSource()
        s.open(path)
        s.configure(AcqParams(loop=False, corr_binning=9))
        out = []
        for _ in range(4):
            fr = s.read_frame(0.15)
            if fr is None:
                break
            out.append(fr)
        return out
    a, b = run(core), run(None)
    assert len(a) == len(b) > 0
    for x, y in zip(a, b):
        np.testing.assert_array_equal(x.hist, y.hist)
        np.testing.assert_array_equal(x.corr, y.corr)
        np.testing.assert_array_equal(x.counts, y.counts)
        np.testing.assert_array_equal(x.events[0], y.events[0])
        np.testing.assert_array_equal(x.events[1], y.events[1])
        assert x.sync_count == y.sync_count
