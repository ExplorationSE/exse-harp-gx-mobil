//! Server-Pfad je Frame (seit 1.3.0): PTU-Dekodierung, T2-Start-Stopp-Histogramm, g²-Kreuzkorrelation zum
//! Referenzkanal und Zählraten. Gleiche Rechenvorschrift wie die NumPy-Fassungen in `harp/ptu.py` und
//! `harp/histogram.py` (bit-identische Ergebnisse; die Tests vergleichen beide), aber in einem Durchlauf ohne
//! Zwischenfelder. Eingaben sind C-zusammenhängende Felder (Buffer-Protokoll), Ausgaben vorbelegte Felder.

use pyo3::buffer::{Element, PyBuffer};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

fn view<'a, T: Element>(b: &'a PyBuffer<T>, what: &str) -> PyResult<&'a [T]> {
    if !b.is_c_contiguous() {
        return Err(PyValueError::new_err(format!("{what}: Feld muss C-zusammenhängend sein")));
    }
    Ok(unsafe { std::slice::from_raw_parts(b.buf_ptr() as *const T, b.item_count()) })
}

fn view_mut<'a, T: Element>(b: &'a PyBuffer<T>, n: usize, what: &str) -> PyResult<&'a mut [T]> {
    if b.readonly() || !b.is_c_contiguous() || b.item_count() != n {
        return Err(PyValueError::new_err(format!("{what}: beschreibbar, C-zusammenhängend, Größe {n} nötig")));
    }
    Ok(unsafe { std::slice::from_raw_parts_mut(b.buf_ptr() as *mut T, n) })
}

// ------------------------------------------------------------------------------------------- PTU-Dekodierung

/// Dekodiert einen Block T2/T3-Records (wie `StreamDecoder.decode`). family: 0 = PicoHarp 300, 1 = HydraHarp V1,
/// 2 = alle neueren; t3: T3-Modus. Schreibt die Photonen (T2: auch Sync als Kanal 0) nach out_t/out_c/out_d
/// (Größe = Anzahl Records) und gibt (Anzahl, neue Overflow-Korrektur, Marker) zurück.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
pub fn ptu_decode(py: Python<'_>, rec: &Bound<'_, PyAny>, family: u8, t3: bool, wrap: i64, ofl: i64,
                  out_t: &Bound<'_, PyAny>, out_c: &Bound<'_, PyAny>, out_d: &Bound<'_, PyAny>)
                  -> PyResult<(usize, i64, i64)> {
    let rb = PyBuffer::<u32>::get(rec)?;
    let r = view(&rb, "Records")?;
    let n = r.len();
    let (bt, bc, bd) = (PyBuffer::<i64>::get(out_t)?, PyBuffer::<i16>::get(out_c)?, PyBuffer::<i32>::get(out_d)?);
    let (ot, oc, od) = (view_mut(&bt, n, "out_t")?, view_mut(&bc, n, "out_c")?, view_mut(&bd, n, "out_d")?);
    if family > 2 {
        return Err(PyValueError::new_err("family: 0, 1 oder 2"));
    }
    Ok(py.allow_threads(|| {
        let (mut cum, mut k, mut markers) = (ofl, 0usize, 0i64);
        for &x in r {
            if family == 0 {
                let ch = (x >> 28) as i16;
                let special = ch == 15;
                let (low, dt, is_ofl) = if t3 {
                    let dt = ((x >> 16) & 0xFFF) as i32;
                    ((x & 0xFFFF) as i64, dt, special && dt == 0)
                } else {
                    let low = (x & 0x0FFF_FFFF) as i64;
                    (low, 0i32, special && (low & 0xF) == 0)
                };
                if is_ofl {
                    cum += wrap;
                }
                if special {
                    if !is_ofl {
                        markers += 1;
                    }
                    continue;
                }
                ot[k] = cum + low;
                oc[k] = if t3 { ch } else { ch + 1 };
                od[k] = dt;
                k += 1;
            } else {
                let special = (x >> 31) != 0;
                let ch = ((x >> 25) & 0x3F) as i16;
                let low = if t3 { (x & 0x3FF) as i64 } else { (x & 0x1FF_FFFF) as i64 };
                if special && ch == 0x3F {
                    cum += if family == 1 || low == 0 { wrap } else { low * wrap };
                }
                if special && (1..=15).contains(&ch) {
                    markers += 1;
                }
                if t3 {
                    if special {
                        continue;
                    }
                    ot[k] = cum + low;
                    oc[k] = ch + 1;
                    od[k] = ((x >> 10) & 0x7FFF) as i32;
                } else {
                    let sync = special && ch == 0;
                    if special && !sync {
                        continue;
                    }
                    ot[k] = cum + low;
                    oc[k] = if sync { 0 } else { ch + 1 };
                    od[k] = 0;
                }
                k += 1;
            }
        }
        (k, cum, markers)
    }))
}

// ------------------------------------------------------------------------------- T2-Start-Stopp-Histogramm

/// Wie `histogram_t2`: Zeit seit dem letzten Start-Ereignis (Kanal start_ch) je Kanal first..=nch, Bin = dt >> binning.
/// Addiert in out (uint64, rows·nbins). Rückgabe (neuer letzter Start oder None, hat_start).
#[pyfunction]
#[pyo3(signature = (t, c, nch, first, start_ch, binning, nbins, last_sync, out))]
#[allow(clippy::too_many_arguments)]
pub fn t2_hist(py: Python<'_>, t: &Bound<'_, PyAny>, c: &Bound<'_, PyAny>, nch: i64, first: i64, start_ch: i64,
               binning: u32, nbins: usize, last_sync: Option<i64>, out: &Bound<'_, PyAny>)
               -> PyResult<(Option<i64>, bool)> {
    let (tb, cb, ob) = (PyBuffer::<i64>::get(t)?, PyBuffer::<i16>::get(c)?, PyBuffer::<u64>::get(out)?);
    let (tv, cv) = (view(&tb, "t")?, view(&cb, "c")?);
    if tv.len() != cv.len() || nch < first || first < 0 || binning > 62 {
        return Err(PyValueError::new_err("t2_hist: Parameter passen nicht"));
    }
    let rows = (nch - first + 1) as usize;
    let o = view_mut(&ob, rows * nbins, "out")?;
    if tv.is_empty() {
        return Ok((last_sync, last_sync.is_some()));
    }
    Ok(py.allow_threads(|| {
        // Start-Zeiten (mit dem letzten Start des Vorgänger-Frames vorn), wie np.concatenate([[last], sync_t])
        let mut starts: Vec<i64> = Vec::new();
        if let Some(ls) = last_sync {
            starts.push(ls);
        }
        let has_new = cv.iter().any(|&x| x as i64 == start_ch);
        if !has_new && last_sync.is_none() {
            return (None, false);
        }
        for (&x, &ch) in tv.iter().zip(cv) {
            if ch as i64 == start_ch {
                starts.push(x);
            }
        }
        // k = searchsorted(starts, t, 'right') − 1: letzter Start mit Zeit ≤ t (Zeiten aufsteigend)
        let mut p: isize = -1;
        for (&x, &ch) in tv.iter().zip(cv) {
            let ch = ch as i64;
            if ch == start_ch || ch < first || ch > nch {
                continue;
            }
            while ((p + 1) as usize) < starts.len() && starts[(p + 1) as usize] <= x {
                p += 1;
            }
            if p < 0 {
                continue;
            }
            let b = (x - starts[p as usize]) >> binning;
            if b < 0 || b as usize >= nbins {
                continue;
            }
            o[(ch - first) as usize * nbins + b as usize] += 1;
        }
        (starts.last().copied(), true)
    }))
}

// ------------------------------------------------------------------------------------------- Zählraten

/// Ereignisse je Kanal first..=nch (int64, rows).
#[pyfunction]
pub fn chan_counts(py: Python<'_>, c: &Bound<'_, PyAny>, nch: i64, first: i64, out: &Bound<'_, PyAny>)
                   -> PyResult<()> {
    let (cb, ob) = (PyBuffer::<i16>::get(c)?, PyBuffer::<i64>::get(out)?);
    let cv = view(&cb, "c")?;
    if nch < first || first < 0 {
        return Err(PyValueError::new_err("chan_counts: nch ≥ first ≥ 0 nötig"));
    }
    let o = view_mut(&ob, (nch - first + 1) as usize, "out")?;
    py.allow_threads(|| {
        let n = o.len();
        for &x in cv {
            let j = x as i64 - first;
            if j >= 0 && (j as usize) < n {
                o[j as usize] += 1;
            }
        }
    });
    Ok(())
}

// ------------------------------------------------------------------------------- g²-Kreuzkorrelation

/// Wie `correlate`: Tail (tail_t/tail_c, Ereignisse des Vorgänger-Frames, zeitlich vor dem Frame) und aktuelle
/// Ereignisse (t/c, nur Kanäle first..=nch zählen). Für jeden Kanal j ≠ ref alle Paare (a auf ref, b auf j) mit
/// τ = b − a ∈ [−W, +W), W = (nbins/2)·bw; ein Paar zählt, wenn a oder b im aktuellen Frame liegt.
/// Addiert in out (uint64, rows·nbins). Rückgabe (k_tail, i_cur) für den neuen Tail = tail[k_tail:] + gefilterte
/// aktuelle Ereignisse ab Index i_cur; None, wenn es gar keine Ereignisse gibt (Tail bleibt).
#[pyfunction]
#[allow(clippy::too_many_arguments)]
pub fn corr_hist(py: Python<'_>, t: &Bound<'_, PyAny>, c: &Bound<'_, PyAny>, tail_t: &Bound<'_, PyAny>,
                 tail_c: &Bound<'_, PyAny>, nch: i64, first: i64, refc: i64, bw: i64, nbins: usize,
                 out: &Bound<'_, PyAny>) -> PyResult<Option<(usize, usize)>> {
    let (tb, cb) = (PyBuffer::<i64>::get(t)?, PyBuffer::<i16>::get(c)?);
    let (ttb, tcb) = (PyBuffer::<i64>::get(tail_t)?, PyBuffer::<i64>::get(tail_c)?);
    let ob = PyBuffer::<u64>::get(out)?;
    let (tv, cv, ttv, tcv) = (view(&tb, "t")?, view(&cb, "c")?, view(&ttb, "tail_t")?, view(&tcb, "tail_c")?);
    if tv.len() != cv.len() || ttv.len() != tcv.len() || nch < first || first < 0 || bw <= 0 || nbins == 0 {
        return Err(PyValueError::new_err("corr_hist: Parameter passen nicht"));
    }
    let rows = (nch - first + 1) as usize;
    let o = view_mut(&ob, rows * nbins, "out")?;
    let w = (nbins / 2) as i64 * bw;
    Ok(py.allow_threads(|| {
        // je Kanal: Zeiten (Tail zuerst) und Anzahl der Tail-Ereignisse
        let mut lists: Vec<Vec<i64>> = vec![Vec::new(); rows];
        let mut ntail = vec![0usize; rows];
        for (&x, &ch) in ttv.iter().zip(tcv) {
            if ch >= first && ch <= nch {
                lists[(ch - first) as usize].push(x);
            }
        }
        for (j, l) in lists.iter().enumerate() {
            ntail[j] = l.len();
        }
        let mut last: Option<i64> = ttv.last().copied();
        for (&x, &ch) in tv.iter().zip(cv) {
            let ch = ch as i64;
            if ch >= first && ch <= nch {
                lists[(ch - first) as usize].push(x);
                last = Some(x);
            }
        }
        let ri = refc - first;
        if ri >= 0 && (ri as usize) < rows && !lists[ri as usize].is_empty() {
            let a = &lists[ri as usize];
            let na_tail = ntail[ri as usize];
            let jobs: Vec<(usize, usize, usize)> = (0..rows)
                .filter(|&j| j as i64 != ri && !lists[j].is_empty())
                .flat_map(|j| {
                    let n = lists[j].len();
                    let p = (n / 16384 + 1).min(rayon::current_num_threads() * 2).max(1);
                    (0..p).map(move |k| (j, n * k / p, n * (k + 1) / p)).filter(|(_, s, e)| e > s)
                })
                .collect();
            let parts: Vec<(usize, Vec<u64>)> = jobs
                .into_par_iter()
                .map(|(j, s0, s1)| {
                    let b = &lists[j];
                    let nbt = ntail[j];
                    let mut h = vec![0u64; nbins];
                    // lo: erstes a > b − w, hi: erstes a > b + w  (searchsorted 'right')
                    let mut lo = a.partition_point(|&v| v <= b[s0] - w);
                    let mut hi = lo;
                    for (ib, &x) in b.iter().enumerate().take(s1).skip(s0) {
                        while lo < a.len() && a[lo] <= x - w {
                            lo += 1;
                        }
                        if hi < lo {
                            hi = lo;
                        }
                        while hi < a.len() && a[hi] <= x + w {
                            hi += 1;
                        }
                        // b im Tail: nur a aus dem aktuellen Frame
                        let start = if ib < nbt { lo.max(na_tail) } else { lo };
                        for &y in &a[start.min(hi)..hi] {
                            let q = (x - y + w).div_euclid(bw);
                            if q >= 0 && (q as usize) < nbins {
                                h[q as usize] += 1;
                            }
                        }
                    }
                    (j, h)
                })
                .collect();
            for (j, h) in parts {
                for (dst, v) in o[j * nbins..(j + 1) * nbins].iter_mut().zip(h) {
                    *dst += v;
                }
            }
        }
        let last = last?;
        let thr = last - w;
        let k_tail = ttv.partition_point(|&v| v < thr);
        let i_cur = tv.partition_point(|&v| v < thr);
        Some((k_tail, i_cur))
    }))
}
