//! Rust-Rechenkern für ExSE Harp GX Mobil: Koinzidenzhistogramme g²/g³/g⁴ auf sortierten Zeitmarken (i64, ps).
//!
//! Gleiche Rechenvorschrift wie die Numba-Kerne in `harp/gx/kernels.py` (bit-identische Histogramme):
//! Für jede Start-Marke t = ta[i], i0 ≤ i < i1, werden alle Marken der anderen Kanäle mit t − W ≤ tx < t + W
//! besucht; Bin = (tx − t + W) / BW (NB·BW ≥ 2W). Die Start-Marken werden in P Blöcke geteilt (rayon,
//! je Block eigenes Histogramm), danach ganzzahlig summiert – das Ergebnis hängt nicht von P ab.
//! Die Python-Seite reicht C-zusammenhängende int64/float64-Felder (Buffer-Protokoll, abi3 ≥ 3.11) und ein
//! vorbelegtes Ausgabefeld; gerechnet wird ohne GIL.

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

#[cfg(feature = "gpu")]
mod gpu;

fn ro<'a>(b: &'a PyBuffer<i64>) -> PyResult<&'a [i64]> {
    if !b.is_c_contiguous() {
        return Err(PyValueError::new_err("Feld muss C-zusammenhängend sein"));
    }
    Ok(unsafe { std::slice::from_raw_parts(b.buf_ptr() as *const i64, b.item_count()) })
}

fn rw_i64<'a>(b: &'a PyBuffer<i64>, n: usize) -> PyResult<&'a mut [i64]> {
    if b.readonly() || !b.is_c_contiguous() || b.item_count() != n {
        return Err(PyValueError::new_err("Ausgabefeld: beschreibbar, C-zusammenhängend, passende Größe"));
    }
    Ok(unsafe { std::slice::from_raw_parts_mut(b.buf_ptr() as *mut i64, n) })
}

#[inline]
fn lower(t: &[i64], x: i64) -> usize {
    t.partition_point(|&v| v < x)
}

fn blocks(i0: usize, i1: usize) -> Vec<(usize, usize)> {
    let n = i1.saturating_sub(i0);
    let p = (rayon::current_num_threads() * 2).min(n / 2048 + 1).max(1);
    (0..p).map(|k| (i0 + n * k / p, i0 + n * (k + 1) / p)).filter(|(a, b)| b > a).collect()
}

fn check(w: i64, bw: i64, nb: usize, i0: usize, i1: usize, na: usize) -> PyResult<()> {
    if w <= 0 || bw <= 0 || nb == 0 || (nb as i64) * bw < 2 * w {
        return Err(PyValueError::new_err("Geometrie: W > 0, BW > 0 und NB·BW ≥ 2W nötig"));
    }
    if i0 > i1 || i1 > na {
        return Err(PyValueError::new_err("Startbereich i0…i1 außerhalb des Felds"));
    }
    Ok(())
}

fn reduce(parts: Vec<Vec<i64>>, out: &mut [i64]) {
    for h in parts {
        for (o, v) in out.iter_mut().zip(h) {
            *o += v;
        }
    }
}

fn g2_core(ta: &[i64], tb: &[i64], i0: usize, i1: usize, w: i64, bw: i64, nb: usize, out: &mut [i64]) {
    let parts: Vec<Vec<i64>> = blocks(i0, i1)
        .into_par_iter()
        .map(|(s0, s1)| {
            let mut h = vec![0i64; nb];
            let mut jb = lower(tb, ta[s0] - w);
            for &t in &ta[s0..s1] {
                while jb < tb.len() && tb[jb] < t - w {
                    jb += 1;
                }
                let mut j = jb;
                while j < tb.len() && tb[j] < t + w {
                    h[((tb[j] - t + w) / bw) as usize] += 1;
                    j += 1;
                }
            }
            h
        })
        .collect();
    reduce(parts, out);
}

fn g3_core(ta: &[i64], tb: &[i64], tc: &[i64], i0: usize, i1: usize, w: i64, bw: i64, nb: usize, out: &mut [i64]) {
    let parts: Vec<Vec<i64>> = blocks(i0, i1)
        .into_par_iter()
        .map(|(s0, s1)| {
            let mut h = vec![0i64; nb * nb];
            let mut jb = lower(tb, ta[s0] - w);
            let mut jc = lower(tc, ta[s0] - w);
            for &t in &ta[s0..s1] {
                while jb < tb.len() && tb[jb] < t - w {
                    jb += 1;
                }
                while jc < tc.len() && tc[jc] < t - w {
                    jc += 1;
                }
                let mut kc_end = jc;
                while kc_end < tc.len() && tc[kc_end] < t + w {
                    kc_end += 1;
                }
                let cs = &tc[jc..kc_end];
                let mut j = jb;
                while j < tb.len() && tb[j] < t + w {
                    let row = &mut h[((tb[j] - t + w) / bw) as usize * nb..][..nb];
                    for &x in cs {
                        row[((x - t + w) / bw) as usize] += 1;
                    }
                    j += 1;
                }
            }
            h
        })
        .collect();
    reduce(parts, out);
}

#[allow(clippy::too_many_arguments)]
fn g4_core(ta: &[i64], tb: &[i64], tc: &[i64], td: &[i64], i0: usize, i1: usize, w: i64, bw: i64, nb: usize,
           out: &mut [i64]) {
    let parts: Vec<Vec<i64>> = blocks(i0, i1)
        .into_par_iter()
        .map(|(s0, s1)| {
            let mut h = vec![0i64; nb * nb * nb];
            let mut jb = lower(tb, ta[s0] - w);
            let mut jc = lower(tc, ta[s0] - w);
            let mut jd = lower(td, ta[s0] - w);
            let mut zi: Vec<usize> = Vec::new();
            for &t in &ta[s0..s1] {
                while jb < tb.len() && tb[jb] < t - w {
                    jb += 1;
                }
                while jc < tc.len() && tc[jc] < t - w {
                    jc += 1;
                }
                while jd < td.len() && td[jd] < t - w {
                    jd += 1;
                }
                let mut ce = jc;
                while ce < tc.len() && tc[ce] < t + w {
                    ce += 1;
                }
                zi.clear();
                let mut m = jd;
                while m < td.len() && td[m] < t + w {
                    zi.push(((td[m] - t + w) / bw) as usize);
                    m += 1;
                }
                if zi.is_empty() || ce == jc {
                    continue;   // keine Beiträge (wie Numba: innere Schleifen leer)
                }
                let mut j = jb;
                while j < tb.len() && tb[j] < t + w {
                    let x = ((tb[j] - t + w) / bw) as usize;
                    for &yc in &tc[jc..ce] {
                        let base = (x * nb + ((yc - t + w) / bw) as usize) * nb;
                        let cell = &mut h[base..base + nb];
                        for &z in &zi {
                            cell[z] += 1;
                        }
                    }
                    j += 1;
                }
            }
            h
        })
        .collect();
    reduce(parts, out);
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn g2_hist(py: Python<'_>, ta: &Bound<'_, PyAny>, tb: &Bound<'_, PyAny>, i0: usize, i1: usize, w: i64, bw: i64,
           nb: usize, out: &Bound<'_, PyAny>) -> PyResult<()> {
    let (ba, bb, bo) = (PyBuffer::<i64>::get(ta)?, PyBuffer::<i64>::get(tb)?, PyBuffer::<i64>::get(out)?);
    let (a, b, o) = (ro(&ba)?, ro(&bb)?, rw_i64(&bo, nb)?);
    check(w, bw, nb, i0, i1, a.len())?;
    py.allow_threads(|| if i1 > i0 { g2_core(a, b, i0, i1, w, bw, nb, o) });
    Ok(())
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn g3_hist(py: Python<'_>, ta: &Bound<'_, PyAny>, tb: &Bound<'_, PyAny>, tc: &Bound<'_, PyAny>, i0: usize, i1: usize,
           w: i64, bw: i64, nb: usize, out: &Bound<'_, PyAny>) -> PyResult<()> {
    let (ba, bb, bc, bo) = (PyBuffer::<i64>::get(ta)?, PyBuffer::<i64>::get(tb)?, PyBuffer::<i64>::get(tc)?,
                            PyBuffer::<i64>::get(out)?);
    let (a, b, c, o) = (ro(&ba)?, ro(&bb)?, ro(&bc)?, rw_i64(&bo, nb * nb)?);
    check(w, bw, nb, i0, i1, a.len())?;
    py.allow_threads(|| if i1 > i0 { g3_core(a, b, c, i0, i1, w, bw, nb, o) });
    Ok(())
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn g4_hist(py: Python<'_>, ta: &Bound<'_, PyAny>, tb: &Bound<'_, PyAny>, tc: &Bound<'_, PyAny>, td: &Bound<'_, PyAny>,
           i0: usize, i1: usize, w: i64, bw: i64, nb: usize, out: &Bound<'_, PyAny>) -> PyResult<()> {
    let (ba, bb, bc, bd, bo) = (PyBuffer::<i64>::get(ta)?, PyBuffer::<i64>::get(tb)?, PyBuffer::<i64>::get(tc)?,
                                PyBuffer::<i64>::get(td)?, PyBuffer::<i64>::get(out)?);
    let (a, b, c, d, o) = (ro(&ba)?, ro(&bb)?, ro(&bc)?, ro(&bd)?, rw_i64(&bo, nb * nb * nb)?);
    check(w, bw, nb, i0, i1, a.len())?;
    py.allow_threads(|| if i1 > i0 { g4_core(a, b, c, d, i0, i1, w, bw, nb, o) });
    Ok(())
}

/// Anzahl Marken von tx in [t+d−w/2, t+d+w−w/2) je Start t (Zwei-Zeiger-Lauf, wie `_wc_nb`).
#[pyfunction]
fn window_counts(py: Python<'_>, ts: &Bound<'_, PyAny>, tx: &Bound<'_, PyAny>, d: i64, w: i64,
                 out: &Bound<'_, PyAny>) -> PyResult<()> {
    let (bs, bx) = (PyBuffer::<i64>::get(ts)?, PyBuffer::<i64>::get(tx)?);
    let bo = PyBuffer::<f64>::get(out)?;
    let (s, x) = (ro(&bs)?, ro(&bx)?);
    if bo.readonly() || !bo.is_c_contiguous() || bo.item_count() != s.len() {
        return Err(PyValueError::new_err("Ausgabefeld (float64) passt nicht"));
    }
    let o = unsafe { std::slice::from_raw_parts_mut(bo.buf_ptr() as *mut f64, s.len()) };
    let half = w.div_euclid(2);   // wie Python w // 2
    py.allow_threads(|| wc_core(s, x, d, w, half, o));
    Ok(())
}

/// Zwei-Zeiger-Lauf je Block; Blöcke parallel (jeder Block sucht seinen Startzeiger per Bisektion).
fn wc_core(s: &[i64], x: &[i64], d: i64, w: i64, half: i64, o: &mut [f64]) {
    if s.is_empty() {
        return;
    }
    let p = (rayon::current_num_threads() * 2).min(s.len() / 16_384 + 1).max(1);
    let chunk = s.len().div_ceil(p);
    o.par_chunks_mut(chunk).zip(s.par_chunks(chunk)).for_each(|(ob, sb)| {
        let mut lo = lower(x, sb[0] + d - half);
        let mut hi = lo;
        for (i, &t) in sb.iter().enumerate() {
            let a = t + d - half;
            let b = t + d + w - half;
            while lo < x.len() && x[lo] < a {
                lo += 1;
            }
            if hi < lo {
                hi = lo;
            }
            while hi < x.len() && x[hi] < b {
                hi += 1;
            }
            ob[i] = (hi - lo) as f64;
        }
    });
}

/// Kachel-Summen in einem Lauf: für jede Start-Marke t die Fensterzählungen n_j(t) aller Schlüssel j
/// (Kanal xs[j], Versatz ds[j], Fenster [t+d−w/2, t+d+w−w/2)), danach je Term Σ_t Π_{j∈Term} n_j(t).
/// Ganzzahlig (exakt); entspricht window_counts + Produkt + Summe in NumPy, solange < 2^53.
fn tile_core(s: &[i64], xs: &[&[i64]], ds: &[i64], w: i64, terms: &[Vec<usize>]) -> Vec<i64> {
    let half = w.div_euclid(2);
    let nk = xs.len();
    let nt = terms.len();
    if s.is_empty() || nt == 0 {
        return vec![0; nt];
    }
    let p = (rayon::current_num_threads() * 2).min(s.len() / 8_192 + 1).max(1);
    let chunk = s.len().div_ceil(p);
    s.par_chunks(chunk)
        .map(|sb| {
            let mut lo: Vec<usize> = (0..nk).map(|j| lower(xs[j], sb[0] + ds[j] - half)).collect();
            let mut hi = lo.clone();
            let mut n = vec![0i64; nk];
            let mut acc = vec![0i64; nt];
            for &t in sb {
                for j in 0..nk {
                    let x = xs[j];
                    let a = t + ds[j] - half;
                    let b = t + ds[j] + w - half;
                    let (mut l, mut h) = (lo[j], hi[j]);
                    while l < x.len() && x[l] < a {
                        l += 1;
                    }
                    if h < l {
                        h = l;
                    }
                    while h < x.len() && x[h] < b {
                        h += 1;
                    }
                    lo[j] = l;
                    hi[j] = h;
                    n[j] = (h - l) as i64;
                }
                for (q, term) in terms.iter().enumerate() {
                    let mut pr = 1i64;
                    for &j in term {
                        pr *= n[j];
                        if pr == 0 {
                            break;
                        }
                    }
                    acc[q] += pr;
                }
            }
            acc
        })
        .reduce(|| vec![0i64; nt], |mut a, b| {
            for (x, y) in a.iter_mut().zip(b) {
                *x += y;
            }
            a
        })
}

#[pyfunction]
fn tile_sums(py: Python<'_>, ts: &Bound<'_, PyAny>, xs: Vec<Bound<'_, PyAny>>, ds: Vec<i64>, w: i64,
             terms: Vec<Vec<usize>>) -> PyResult<Vec<i64>> {
    if xs.len() != ds.len() {
        return Err(PyValueError::new_err("xs und ds: gleiche Länge nötig"));
    }
    if terms.iter().flatten().any(|&j| j >= xs.len()) {
        return Err(PyValueError::new_err("Term verweist auf unbekannten Schlüssel"));
    }
    let bs = PyBuffer::<i64>::get(ts)?;
    let bx: Vec<PyBuffer<i64>> = xs.iter().map(PyBuffer::<i64>::get).collect::<PyResult<_>>()?;
    let s = ro(&bs)?;
    let x: Vec<&[i64]> = bx.iter().map(ro).collect::<PyResult<_>>()?;
    Ok(py.allow_threads(|| tile_core(s, &x, &ds, w, &terms)))
}

/// Thread-Zahl festlegen (nur vor der ersten Rechnung wirksam); gibt die aktive Zahl zurück.
#[pyfunction]
fn init_threads(n: usize) -> usize {
    if n > 0 {
        let _ = rayon::ThreadPoolBuilder::new().num_threads(n).build_global();
    }
    rayon::current_num_threads()
}

#[pyfunction]
fn n_threads() -> usize {
    rayon::current_num_threads()
}


/// Verteilt Zeitmarken nach Kanal in vorab passend große Ausgabefelder (ein Durchlauf, stabil).
/// lut[kanal] = Index in outs oder -1 (Kanal ignorieren).
#[pyfunction]
fn split_channels(py: Python<'_>, t: &Bound<'_, PyAny>, ch: &Bound<'_, PyAny>, lut: Vec<i64>,
                  outs: Vec<Bound<'_, PyAny>>) -> PyResult<()> {
    let tb = PyBuffer::<i64>::get(t)?;
    let cb = PyBuffer::<i16>::get(ch)?;
    let tv = ro(&tb)?;
    if !cb.is_c_contiguous() || cb.item_count() != tv.len() {
        return Err(PyValueError::new_err("Kanalfeld: C-zusammenhängend, gleiche Länge wie Zeitfeld"));
    }
    let cv = unsafe { std::slice::from_raw_parts(cb.buf_ptr() as *const i16, cb.item_count()) };
    let obs: Vec<PyBuffer<i64>> = outs.iter().map(|o| PyBuffer::<i64>::get(o)).collect::<PyResult<_>>()?;
    let mut ov: Vec<&mut [i64]> = Vec::with_capacity(obs.len());
    for b in &obs {
        ov.push(rw_i64(b, b.item_count())?);
    }
    if lut.iter().any(|&j| j >= ov.len() as i64) {
        return Err(PyValueError::new_err("lut verweist auf fehlendes Ausgabefeld"));
    }
    let ok = py.allow_threads(|| {
        let mut pos = vec![0usize; ov.len()];
        for (&tt, &c) in tv.iter().zip(cv) {
            if c < 0 || (c as usize) >= lut.len() { continue; }
            let j = lut[c as usize];
            if j < 0 { continue; }
            let j = j as usize;
            if pos[j] >= ov[j].len() { return false; }
            ov[j][pos[j]] = tt;
            pos[j] += 1;
        }
        pos.iter().zip(&ov).all(|(&p, o)| p == o.len())
    });
    if ok { Ok(()) } else { Err(PyValueError::new_err("Ausgabefeldgrößen passen nicht zu den Kanalzählungen")) }
}

// ------------------------------------------------------------------------------------------------ GPU (wgpu)
// Optional (cargo-Feature „gpu“, Standard an). Ohne Feature oder ohne Gerät liefern gpu_init/gpu_info None,
// die Python-Seite rechnet dann auf der CPU. Fehler im GPU-Pfad (auch Panics) werden zu RuntimeError.

#[cfg(feature = "gpu")]
fn info_dict<'py>(py: Python<'py>, i: &gpu::Info) -> PyResult<Bound<'py, pyo3::types::PyDict>> {
    let d = pyo3::types::PyDict::new(py);
    d.set_item("name", &i.name)?;
    d.set_item("backend", &i.backend)?;
    d.set_item("device_type", &i.device_type)?;
    d.set_item("driver", &i.driver)?;
    d.set_item("driver_info", &i.driver_info)?;
    d.set_item("vendor", i.vendor)?;
    Ok(d)
}

#[cfg_attr(not(feature = "gpu"), allow(dead_code))]
fn panic_msg(e: Box<dyn std::any::Any + Send>) -> String {
    e.downcast_ref::<&str>().map(|s| s.to_string())
        .or_else(|| e.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "unbekannt".into())
}

/// True, wenn der Kern mit GPU-Unterstützung (wgpu) gebaut wurde.
#[pyfunction]
fn gpu_compiled() -> bool {
    cfg!(feature = "gpu")
}

/// Alle Grafik-Adapter (zur Diagnose): Liste von dicts (+ "compute": nutzbar für Compute-Shader).
#[pyfunction]
#[pyo3(signature = (backend=None))]
fn gpu_adapters(py: Python<'_>, backend: Option<String>) -> PyResult<PyObject> {
    #[cfg(feature = "gpu")]
    {
        let list = py.allow_threads(|| std::panic::catch_unwind(|| gpu::adapters(backend.as_deref())))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("GPU-Panic: {}", panic_msg(e))))?;
        let out = pyo3::types::PyList::empty(py);
        for (i, ok) in &list {
            let d = info_dict(py, i)?;
            d.set_item("compute", *ok)?;
            out.append(d)?;
        }
        Ok(out.into_any().unbind())
    }
    #[cfg(not(feature = "gpu"))]
    {
        let _ = backend;
        Ok(pyo3::types::PyList::empty(py).into_any().unbind())
    }
}

/// GPU öffnen (bestes Gerät). allow_cpu: auch Software-Adapter (lavapipe/WARP) zulassen.
/// Rückgabe: dict mit Gerätedaten oder None (kein Gerät / ohne GPU gebaut).
#[pyfunction]
#[pyo3(signature = (allow_cpu=false, backend=None))]
fn gpu_init(py: Python<'_>, allow_cpu: bool, backend: Option<String>) -> PyResult<PyObject> {
    #[cfg(feature = "gpu")]
    {
        let r = py.allow_threads(|| std::panic::catch_unwind(|| gpu::Gpu::new(allow_cpu, backend.as_deref())))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("GPU-Panic: {}", panic_msg(e))))?
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        let mut g = gpu::GPU.lock().unwrap_or_else(|p| p.into_inner());
        *g = r;
        match g.as_ref() {
            Some(x) => Ok(info_dict(py, &x.info)?.into_any().unbind()),
            None => Ok(py.None()),
        }
    }
    #[cfg(not(feature = "gpu"))]
    {
        let _ = (allow_cpu, backend);
        Ok(py.None())
    }
}

/// Gerätedaten der geöffneten GPU oder None.
#[pyfunction]
fn gpu_info(py: Python<'_>) -> PyResult<PyObject> {
    #[cfg(feature = "gpu")]
    {
        let g = gpu::GPU.lock().unwrap_or_else(|p| p.into_inner());
        if let Some(x) = g.as_ref() {
            return Ok(info_dict(py, &x.info)?.into_any().unbind());
        }
    }
    Ok(py.None())
}

/// Zeitaufteilung des letzten GPU-Aufrufs: dict(prep_s, wait_s, dispatches, blocks) oder None.
#[pyfunction]
fn gpu_profile(py: Python<'_>) -> PyResult<PyObject> {
    #[cfg(feature = "gpu")]
    {
        let g = gpu::GPU.lock().unwrap_or_else(|p| p.into_inner());
        if let Some(x) = g.as_ref() {
            let d = pyo3::types::PyDict::new(py);
            d.set_item("prep_s", x.prof.0)?;
            d.set_item("wait_s", x.prof.1)?;
            d.set_item("dispatches", x.prof.2)?;
            d.set_item("blocks", x.prof.3)?;
            return Ok(d.into_any().unbind());
        }
    }
    Ok(py.None())
}

/// GPU schließen (Speicher freigeben).
#[pyfunction]
fn gpu_release() {
    #[cfg(feature = "gpu")]
    {
        let mut g = gpu::GPU.lock().unwrap_or_else(|p| p.into_inner());
        *g = None;
    }
}

#[allow(clippy::too_many_arguments, unused_variables)]
fn gpu_run(py: Python<'_>, ts: &[&Bound<'_, PyAny>], i0: usize, i1: usize, w: i64, bw: i64, nb: usize,
           out: &Bound<'_, PyAny>) -> PyResult<()> {
    let bufs: Vec<PyBuffer<i64>> = ts.iter().map(|x| PyBuffer::<i64>::get(x)).collect::<PyResult<_>>()?;
    let sl: Vec<&[i64]> = bufs.iter().map(ro).collect::<PyResult<_>>()?;
    let bo = PyBuffer::<i64>::get(out)?;
    let o = rw_i64(&bo, nb.pow((sl.len() - 1) as u32))?;
    check(w, bw, nb, i0, i1, sl[0].len())?;
    #[cfg(feature = "gpu")]
    {
        let r = py.allow_threads(|| {
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let mut g = gpu::GPU.lock().unwrap_or_else(|p| p.into_inner());
                match g.as_mut() {
                    Some(x) => x.hist(sl[0], &sl[1..], i0, i1, w, bw, nb, o),
                    None => Err("GPU nicht geöffnet (gpu_init)".into()),
                }
            }))
        });
        match r {
            Ok(Ok(())) => Ok(()),
            Ok(Err(e)) => Err(pyo3::exceptions::PyRuntimeError::new_err(e)),
            Err(e) => {
                *gpu::GPU.lock().unwrap_or_else(|p| p.into_inner()) = None;
                Err(pyo3::exceptions::PyRuntimeError::new_err(format!("GPU-Panic: {}", panic_msg(e))))
            }
        }
    }
    #[cfg(not(feature = "gpu"))]
    {
        let _ = o;
        Err(pyo3::exceptions::PyRuntimeError::new_err("ohne GPU-Unterstützung gebaut"))
    }
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn gpu_g2_hist(py: Python<'_>, ta: &Bound<'_, PyAny>, tb: &Bound<'_, PyAny>, i0: usize, i1: usize, w: i64, bw: i64,
               nb: usize, out: &Bound<'_, PyAny>) -> PyResult<()> {
    gpu_run(py, &[ta, tb], i0, i1, w, bw, nb, out)
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn gpu_g3_hist(py: Python<'_>, ta: &Bound<'_, PyAny>, tb: &Bound<'_, PyAny>, tc: &Bound<'_, PyAny>, i0: usize,
               i1: usize, w: i64, bw: i64, nb: usize, out: &Bound<'_, PyAny>) -> PyResult<()> {
    gpu_run(py, &[ta, tb, tc], i0, i1, w, bw, nb, out)
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn gpu_g4_hist(py: Python<'_>, ta: &Bound<'_, PyAny>, tb: &Bound<'_, PyAny>, tc: &Bound<'_, PyAny>,
               td: &Bound<'_, PyAny>, i0: usize, i1: usize, w: i64, bw: i64, nb: usize, out: &Bound<'_, PyAny>)
               -> PyResult<()> {
    gpu_run(py, &[ta, tb, tc, td], i0, i1, w, bw, nb, out)
}

#[pymodule]
fn harp_gx_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(g2_hist, m)?)?;
    m.add_function(wrap_pyfunction!(g3_hist, m)?)?;
    m.add_function(wrap_pyfunction!(g4_hist, m)?)?;
    m.add_function(wrap_pyfunction!(window_counts, m)?)?;
    m.add_function(wrap_pyfunction!(tile_sums, m)?)?;
    m.add_function(wrap_pyfunction!(split_channels, m)?)?;
    m.add_function(wrap_pyfunction!(init_threads, m)?)?;
    m.add_function(wrap_pyfunction!(n_threads, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_compiled, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_adapters, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_init, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_info, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_release, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_profile, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_g2_hist, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_g3_hist, m)?)?;
    m.add_function(wrap_pyfunction!(gpu_g4_hist, m)?)?;
    Ok(())
}
