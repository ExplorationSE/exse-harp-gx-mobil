//! GPU-Pfad (wgpu: DirectX 12 / Vulkan / Metal) für g²/g³/g⁴-Histogramme.
//!
//! Gleiche Rechenvorschrift wie die CPU-Kerne in lib.rs, bit-identische Ergebnisse:
//!  * Start-Marken (Kanal a, i0…i1) werden in Blöcke zu ≤ 256 Marken geteilt; jeder Block bekommt je
//!    Partnerkanal den Ausschnitt [t_erste − W, t_letzte + W) als Überlapp (wie die rayon-Blöcke).
//!  * Zeiten werden je Block relativ zu basis = t_erste − W als i32 übertragen (Spannweite < 2^30 ps,
//!    2W ≤ 2^30 ps) → keine 64-bit-Arithmetik/Atomics auf der GPU nötig (Intel-iGPU-tauglich).
//!  * Eine Arbeitsgruppe (64 Threads) je Block, eine Start-Marke je Thread; Fensterränder per Bisektion;
//!    Histogramm-Bins als atomare u32-Paare (lo/hi mit Übertrag) → exakt.
//!  * Arbeit wird in Teil-Dispatches begrenzt (Speicher, geschätzte Tupelzahl), damit kein einzelner
//!    Dispatch lange läuft (Windows-TDR) – Fehler/Geräteverlust → Err, die Python-Seite fällt auf die CPU zurück.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use rayon::prelude::*;

const WG: usize = 64;
const BLK: usize = 256;
const SPAN_MAX: i64 = 1 << 30;
const WORK_MAX: f64 = 4.0e7;        // geschätzte Histogramm-Inkremente je Teil-Dispatch
const ELEMS_MAX: usize = 1 << 24;   // ≤ 64 MB Zeiten je Teil-Dispatch

#[derive(Clone, Debug)]
pub struct Info {
    pub name: String,
    pub backend: String,
    pub device_type: String,
    pub driver: String,
    pub driver_info: String,
    pub vendor: u32,
}

pub struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    bgl: wgpu::BindGroupLayout,
    pipes: [wgpu::ComputePipeline; 3],
    params: wgpu::Buffer,
    times: Option<(wgpu::Buffer, u64)>,
    blocks: Option<(wgpu::Buffer, u64)>,
    hist: Option<(wgpu::Buffer, wgpu::Buffer, u64)>,
    lost: Arc<AtomicBool>,
    err: Arc<Mutex<Option<String>>>,
    max_elems: usize,
    max_groups: u32,
    pub info: Info,
    /// letzte Messung: (Vorbereitung CPU [s], Warten auf GPU inkl. Rückübertragung [s], Teil-Dispatches, Blöcke)
    pub prof: (f64, f64, usize, usize),
}

pub static GPU: Mutex<Option<Gpu>> = Mutex::new(None);

fn type_name(t: wgpu::DeviceType) -> &'static str {
    match t {
        wgpu::DeviceType::DiscreteGpu => "diskret",
        wgpu::DeviceType::IntegratedGpu => "integriert",
        wgpu::DeviceType::VirtualGpu => "virtuell",
        wgpu::DeviceType::Cpu => "cpu",
        wgpu::DeviceType::Other => "andere",
    }
}

fn rank(i: &wgpu::AdapterInfo) -> (u8, u8) {
    let t = match i.device_type {
        wgpu::DeviceType::DiscreteGpu => 0,
        wgpu::DeviceType::IntegratedGpu => 1,
        wgpu::DeviceType::VirtualGpu => 2,
        wgpu::DeviceType::Other => 3,
        wgpu::DeviceType::Cpu => 4,
    };
    let b = match i.backend {
        wgpu::Backend::Dx12 => 0,
        wgpu::Backend::Vulkan => 1,
        wgpu::Backend::Metal => 1,
        _ => 5,
    };
    (t, b)
}

fn backends(pref: Option<&str>) -> wgpu::Backends {
    match pref.map(|s| s.to_ascii_lowercase()) {
        Some(s) if s == "dx12" => wgpu::Backends::DX12,
        Some(s) if s == "vulkan" => wgpu::Backends::VULKAN,
        Some(s) if s == "metal" => wgpu::Backends::METAL,
        _ => wgpu::Backends::DX12 | wgpu::Backends::VULKAN | wgpu::Backends::METAL,
    }
}

fn instance(pref: Option<&str>) -> wgpu::Instance {
    wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: backends(pref),
        flags: wgpu::InstanceFlags::empty(),
        ..Default::default()
    })
}

fn usable(a: &wgpu::Adapter) -> bool {
    a.get_downlevel_capabilities().flags.contains(wgpu::DownlevelFlags::COMPUTE_SHADERS)
}

pub fn adapters(pref: Option<&str>) -> Vec<(Info, bool)> {
    let inst = instance(pref);
    inst.enumerate_adapters(backends(pref))
        .into_iter()
        .map(|a| (info_of(&a.get_info()), usable(&a)))
        .collect()
}

fn info_of(i: &wgpu::AdapterInfo) -> Info {
    Info {
        name: i.name.clone(),
        backend: format!("{:?}", i.backend).to_lowercase(),
        device_type: type_name(i.device_type).into(),
        driver: i.driver.clone(),
        driver_info: i.driver_info.clone(),
        vendor: i.vendor,
    }
}

impl Gpu {
    /// Bestes Gerät wählen (diskret > integriert > virtuell; Software-Adapter nur mit allow_cpu).
    pub fn new(allow_cpu: bool, pref: Option<&str>) -> Result<Option<Gpu>, String> {
        let inst = instance(pref);
        let mut ads: Vec<wgpu::Adapter> = inst
            .enumerate_adapters(backends(pref))
            .into_iter()
            .filter(|a| usable(a) && (allow_cpu || a.get_info().device_type != wgpu::DeviceType::Cpu))
            .collect();
        ads.sort_by_key(|a| rank(&a.get_info()));
        let Some(ad) = ads.into_iter().next() else { return Ok(None) };
        let info = info_of(&ad.get_info());
        let al = ad.limits();
        let mut lim = wgpu::Limits::downlevel_defaults();
        lim.max_storage_buffer_binding_size = al.max_storage_buffer_binding_size;
        lim.max_buffer_size = al.max_buffer_size;
        lim.max_compute_workgroups_per_dimension = al.max_compute_workgroups_per_dimension;
        let (device, queue) = pollster::block_on(ad.request_device(&wgpu::DeviceDescriptor {
            label: Some("harp-gx"),
            required_features: wgpu::Features::empty(),
            required_limits: lim.clone(),
            memory_hints: wgpu::MemoryHints::Performance,
            trace: wgpu::Trace::Off,
        }))
        .map_err(|e| format!("request_device: {e}"))?;
        let lost = Arc::new(AtomicBool::new(false));
        let err = Arc::new(Mutex::new(None::<String>));
        {
            let l = lost.clone();
            device.set_device_lost_callback(move |_r, _m| l.store(true, Ordering::SeqCst));
            let e = err.clone();
            device.on_uncaptured_error(Box::new(move |x| {
                if let Ok(mut g) = e.lock() {
                    *g = Some(x.to_string());
                }
            }));
        }
        device.push_error_scope(wgpu::ErrorFilter::Validation);
        let module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("gx.wgsl"),
            source: wgpu::ShaderSource::Wgsl(include_str!("gx.wgsl").into()),
        });
        let ent = |i: u32, ty: wgpu::BufferBindingType| wgpu::BindGroupLayoutEntry {
            binding: i,
            visibility: wgpu::ShaderStages::COMPUTE,
            ty: wgpu::BindingType::Buffer { ty, has_dynamic_offset: false, min_binding_size: None },
            count: None,
        };
        let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("gx"),
            entries: &[
                ent(0, wgpu::BufferBindingType::Uniform),
                ent(1, wgpu::BufferBindingType::Storage { read_only: true }),
                ent(2, wgpu::BufferBindingType::Storage { read_only: true }),
                ent(3, wgpu::BufferBindingType::Storage { read_only: false }),
            ],
        });
        let pl = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("gx"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });
        let mk = |ep: &str| {
            device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some(ep),
                layout: Some(&pl),
                module: &module,
                entry_point: Some(ep),
                compilation_options: Default::default(),
                cache: None,
            })
        };
        let pipes = [mk("g2"), mk("g3"), mk("g4")];
        if let Some(e) = pollster::block_on(device.pop_error_scope()) {
            return Err(format!("Shader/Pipeline: {e}"));
        }
        let params = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("params"),
            size: 32,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let max_elems = ((lim.max_storage_buffer_binding_size as u64 / 4).min(lim.max_buffer_size / 4) as usize)
            .min(ELEMS_MAX);
        Ok(Some(Gpu {
            device,
            queue,
            bgl,
            pipes,
            params,
            times: None,
            blocks: None,
            hist: None,
            lost,
            err,
            max_elems,
            max_groups: lim.max_compute_workgroups_per_dimension.max(1),
            info,
            prof: (0.0, 0.0, 0, 0),
        }))
    }

    fn storage(dev: &wgpu::Device, slot: &mut Option<(wgpu::Buffer, u64)>, bytes: u64, label: &str) {
        let need = bytes.max(16).next_power_of_two();
        if slot.as_ref().map_or(true, |(_, s)| *s < need) {
            *slot = Some((
                dev.create_buffer(&wgpu::BufferDescriptor {
                    label: Some(label),
                    size: need,
                    usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                }),
                need,
            ));
        }
    }

    fn check(&self) -> Result<(), String> {
        if self.lost.load(Ordering::SeqCst) {
            return Err("GPU-Gerät verloren (Treiber-Reset)".into());
        }
        if let Some(e) = self.err.lock().ok().and_then(|mut g| g.take()) {
            return Err(format!("GPU-Fehler: {e}"));
        }
        Ok(())
    }

    /// Histogramm der Ordnung k = 2, 3, 4 (others: 1, 2 oder 3 Partnerkanäle) → zu `out` addiert.
    #[allow(clippy::too_many_arguments)]
    pub fn hist(&mut self, ta: &[i64], others: &[&[i64]], i0: usize, i1: usize, w: i64, bw: i64, nb: usize,
                out: &mut [i64]) -> Result<(), String> {
        self.check()?;
        let m = others.len();
        let nbins = nb.pow(m as u32);
        if 2 * w > SPAN_MAX {
            return Err("Fenster zu groß für 32-bit-Relativzeiten (2W > 2^30 ps)".into());
        }
        if nbins as u64 * 8 > self.max_elems as u64 * 4 {
            return Err("Histogramm zu groß für die GPU".into());
        }
        if i1 <= i0 {
            return Ok(());
        }
        // --- Blöcke bilden (≤ BLK Start-Marken, Spannweite < SPAN_MAX) und Ausschnitte bestimmen
        struct B { s0: usize, s1: usize, lo: [usize; 3], hi: [usize; 3], est: f64, len: usize }
        let t_start = Instant::now();
        let mut blocks: Vec<B> = Vec::with_capacity((i1 - i0) / BLK + 1);
        let mut lo_p = [0usize; 3];
        let mut hi_p = [0usize; 3];
        let mut s = i0;
        while s < i1 {
            let t0 = ta[s];
            let mut e = s + 1;
            let lim = (s + BLK).min(i1);
            while e < lim && ta[e] - t0 < SPAN_MAX {
                e += 1;
            }
            let t1 = ta[e - 1];
            let mut lo = [0usize; 3];
            let mut hi = [0usize; 3];
            let mut est = (e - s) as f64;
            let mut len = e - s;
            for (k, x) in others.iter().enumerate() {
                let (mut l, mut h) = (lo_p[k], hi_p[k].max(lo_p[k]));
                while l < x.len() && x[l] < t0 - w { l += 1; }
                if h < l { h = l; }
                while h < x.len() && x[h] < t1 + w { h += 1; }
                lo_p[k] = l; hi_p[k] = h; lo[k] = l; hi[k] = h;
                len += h - l;
                est *= ((h - l) as f64 * (2 * w) as f64 / ((t1 - t0 + 2 * w) as f64)).max(1.0);
            }
            if len > self.max_elems {
                return Err("Block zu groß für den GPU-Puffer".into());
            }
            blocks.push(B { s0: s, s1: e, lo, hi, est, len });
            s = e;
        }
        // --- Histogramm-Puffer leeren
        let hbytes = (nbins * 8) as u64;
        let need = hbytes.max(16).next_power_of_two();
        if self.hist.as_ref().map_or(true, |(_, _, s)| *s < need) {
            let hb = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("hist"),
                size: need,
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            let rb = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("readback"),
                size: need,
                usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            self.hist = Some((hb, rb, need));
        }
        self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        self.device.push_error_scope(wgpu::ErrorFilter::OutOfMemory);
        {
            let mut enc = self.device.create_command_encoder(&Default::default());
            enc.clear_buffer(&self.hist.as_ref().unwrap().0, 0, Some(hbytes));
            self.queue.submit([enc.finish()]);
        }
        // --- Teil-Dispatches
        let pipe = m - 1;
        let mut c0 = 0usize;
        let mut ndisp = 0usize;
        let mut tm: Vec<i32> = Vec::new();
        let mut desc: Vec<u32> = Vec::new();
        while c0 < blocks.len() {
            let (mut c1, mut work, mut elems) = (c0, 0.0f64, 0usize);
            while c1 < blocks.len()
                && (c1 == c0 || (work + blocks[c1].est <= WORK_MAX && elems + blocks[c1].len <= self.max_elems))
            {
                work += blocks[c1].est;
                elems += blocks[c1].len;
                c1 += 1;
            }
            // gepackte Relativzeiten je Block parallel füllen (rayon; disjunkte Teilstücke)
            tm.clear();
            tm.resize(elems, 0);
            desc.clear();
            desc.reserve((c1 - c0) * 8);
            let mut parts: Vec<(&B, &mut [i32])> = Vec::with_capacity(c1 - c0);
            {
                let mut rest: &mut [i32] = &mut tm[..];
                let mut off = 0usize;
                for b in &blocks[c0..c1] {
                    let (head, tail) = rest.split_at_mut(b.len);
                    rest = tail;
                    desc.push(off as u32);
                    desc.push((b.s1 - b.s0) as u32);
                    let mut o = off + (b.s1 - b.s0);
                    for k in 0..3 {
                        if k < m {
                            desc.push(o as u32);
                            desc.push((b.hi[k] - b.lo[k]) as u32);
                            o += b.hi[k] - b.lo[k];
                        } else {
                            desc.push(0);
                            desc.push(0);
                        }
                    }
                    off += b.len;
                    parts.push((b, head));
                }
            }
            parts.into_par_iter().for_each(|(b, dst)| {
                let base = ta[b.s0] - w;
                let mut p = 0usize;
                for &t in &ta[b.s0..b.s1] {
                    dst[p] = (t - base) as i32;
                    p += 1;
                }
                for k in 0..m {
                    for &t in &others[k][b.lo[k]..b.hi[k]] {
                        dst[p] = (t - base) as i32;
                        p += 1;
                    }
                }
            });
            let nblk = (c1 - c0) as u32;
            let gx = nblk.min(self.max_groups);
            let gy = nblk.div_ceil(gx);
            if gy > self.max_groups {
                return Err("zu viele Arbeitsgruppen".into());
            }
            Self::storage(&self.device, &mut self.times, (tm.len() * 4) as u64, "times");
            Self::storage(&self.device, &mut self.blocks, (desc.len() * 4) as u64, "blocks");
            let (tb, _) = self.times.as_ref().unwrap();
            let (bb, _) = self.blocks.as_ref().unwrap();
            self.queue.write_buffer(tb, 0, bytemuck_i32(&tm));
            self.queue.write_buffer(bb, 0, bytemuck_u32(&desc));
            let p: [u32; 8] = [w as i32 as u32, bw as i32 as u32, nb as u32, nblk, gx, 0, 0, 0];
            self.queue.write_buffer(&self.params, 0, bytemuck_u32(&p));
            let bg = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: None,
                layout: &self.bgl,
                entries: &[
                    wgpu::BindGroupEntry { binding: 0, resource: self.params.as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 1, resource: bb.as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 2, resource: tb.as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 3, resource: self.hist.as_ref().unwrap().0.as_entire_binding() },
                ],
            });
            let mut enc = self.device.create_command_encoder(&Default::default());
            {
                let mut cp = enc.begin_compute_pass(&Default::default());
                cp.set_pipeline(&self.pipes[pipe]);
                cp.set_bind_group(0, &bg, &[]);
                cp.dispatch_workgroups(gx, gy, 1);
            }
            self.queue.submit([enc.finish()]);
            ndisp += 1;
            c0 = c1;
        }
        // --- Auslesen
        let t_prep = t_start.elapsed().as_secs_f64();
        let (hb, rb, _) = self.hist.as_ref().unwrap();
        let mut enc = self.device.create_command_encoder(&Default::default());
        enc.copy_buffer_to_buffer(hb, 0, rb, 0, hbytes);
        self.queue.submit([enc.finish()]);
        let oom = pollster::block_on(self.device.pop_error_scope());
        let val = pollster::block_on(self.device.pop_error_scope());
        if let Some(e) = oom.or(val) {
            return Err(format!("GPU: {e}"));
        }
        let sl = rb.slice(0..hbytes);
        let (tx, rx) = std::sync::mpsc::channel();
        sl.map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        self.device.poll(wgpu::PollType::Wait).map_err(|e| format!("poll: {e}"))?;
        match rx.recv() {
            Ok(Ok(())) => {}
            Ok(Err(e)) => return Err(format!("map: {e}")),
            Err(_) => return Err("map: keine Antwort".into()),
        }
        {
            let data = sl.get_mapped_range();
            for (o, c) in out.iter_mut().zip(data.chunks_exact(8)) {
                let lo = u32::from_le_bytes([c[0], c[1], c[2], c[3]]) as u64;
                let hi = u32::from_le_bytes([c[4], c[5], c[6], c[7]]) as u64;
                *o += ((hi << 32) | lo) as i64;
            }
        }
        rb.unmap();
        self.prof = (t_prep, t_start.elapsed().as_secs_f64() - t_prep, ndisp, blocks.len());
        self.check()
    }
}

fn bytemuck_i32(v: &[i32]) -> &[u8] {
    unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, std::mem::size_of_val(v)) }
}

fn bytemuck_u32(v: &[u32]) -> &[u8] {
    unsafe { std::slice::from_raw_parts(v.as_ptr() as *const u8, std::mem::size_of_val(v)) }
}

#[allow(dead_code)]
const _: () = assert!(WG == 64);
