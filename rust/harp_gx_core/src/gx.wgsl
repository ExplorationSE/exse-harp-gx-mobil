// GPU-Kerne (WGSL, wgpu) für g²/g³/g⁴-Koinzidenzhistogramme – gleiche Rechenvorschrift wie lib.rs (CPU).
//
// Zeiten sind 32-bit-Relativzeiten je Block: rel = t − basis, basis = t_erste_Startmarke − W.
// Ein Block = eine Arbeitsgruppe; er enthält ≤ 256 Start-Marken (Kanal a) und je Partnerkanal den
// Ausschnitt [t_erste − W, t_letzte + W) (Überlapp ±W, wie die CPU-Blöcke). Spannweite + 2W < 2^31.
// Bin = (tx − t + W) / BW ist von der Basis unabhängig → ganzzahlig identisch zur CPU.
// Histogramm: je Bin zwei u32 (lo, hi) mit Übertrag → exakt bis 2^64 (keine 64-bit-Atomics nötig).

struct Params {
    w: i32,
    bw: i32,
    nb: u32,
    nblocks: u32,
    gx: u32,
    p0: u32,
    p1: u32,
    p2: u32,
}

@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> blk: array<u32>;          // je Block 8 Werte: (off, len) für a, b, c, d
@group(0) @binding(2) var<storage, read> tm: array<i32>;           // gepackte Relativzeiten
@group(0) @binding(3) var<storage, read_write> h: array<atomic<u32>>;

const WG: u32 = 64u;

fn inc(i: u32) {
    let o = atomicAdd(&h[2u * i], 1u);
    if (o == 0xffffffffu) {
        atomicAdd(&h[2u * i + 1u], 1u);
    }
}

// erster Index k in [0, n) mit tm[off + k] >= x (sonst n)
fn lower(off: u32, n: u32, x: i32) -> u32 {
    var lo = 0u;
    var hi = n;
    loop {
        if (lo >= hi) { break; }
        let mid = (lo + hi) / 2u;
        if (tm[off + mid] < x) { lo = mid + 1u; } else { hi = mid; }
    }
    return lo;
}

fn bin(x: i32, t: i32) -> u32 {
    return u32((x - t + P.w) / P.bw);
}

@compute @workgroup_size(64)
fn g2(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let b = wid.x + wid.y * P.gx;
    if (b >= P.nblocks) { return; }
    let d = b * 8u;
    let ao = blk[d]; let an = blk[d + 1u];
    let bo = blk[d + 2u]; let bn = blk[d + 3u];
    for (var i = li; i < an; i += WG) {
        let t = tm[ao + i];
        var j = lower(bo, bn, t - P.w);
        loop {
            if (j >= bn) { break; }
            let x = tm[bo + j];
            if (x >= t + P.w) { break; }
            let q = bin(x, t);
            if (q < P.nb) { inc(q); }
            j += 1u;
        }
    }
}

@compute @workgroup_size(64)
fn g3(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let b = wid.x + wid.y * P.gx;
    if (b >= P.nblocks) { return; }
    let d = b * 8u;
    let ao = blk[d]; let an = blk[d + 1u];
    let bo = blk[d + 2u]; let bn = blk[d + 3u];
    let co = blk[d + 4u]; let cn = blk[d + 5u];
    let nb = P.nb;
    for (var i = li; i < an; i += WG) {
        let t = tm[ao + i];
        let c0 = lower(co, cn, t - P.w);
        let c1 = lower(co, cn, t + P.w);
        if (c1 == c0) { continue; }
        var j = lower(bo, bn, t - P.w);
        loop {
            if (j >= bn) { break; }
            let x = tm[bo + j];
            if (x >= t + P.w) { break; }
            let row = bin(x, t) * nb;
            for (var k = c0; k < c1; k += 1u) {
                let q = row + bin(tm[co + k], t);
                if (q < nb * nb) { inc(q); }
            }
            j += 1u;
        }
    }
}

@compute @workgroup_size(64)
fn g4(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let b = wid.x + wid.y * P.gx;
    if (b >= P.nblocks) { return; }
    let d = b * 8u;
    let ao = blk[d]; let an = blk[d + 1u];
    let bo = blk[d + 2u]; let bn = blk[d + 3u];
    let co = blk[d + 4u]; let cn = blk[d + 5u];
    let eo = blk[d + 6u]; let en = blk[d + 7u];
    let nb = P.nb;
    let n3 = nb * nb * nb;
    for (var i = li; i < an; i += WG) {
        let t = tm[ao + i];
        let c0 = lower(co, cn, t - P.w);
        let c1 = lower(co, cn, t + P.w);
        let e0 = lower(eo, en, t - P.w);
        let e1 = lower(eo, en, t + P.w);
        if (c1 == c0 || e1 == e0) { continue; }
        var j = lower(bo, bn, t - P.w);
        loop {
            if (j >= bn) { break; }
            let x = tm[bo + j];
            if (x >= t + P.w) { break; }
            let bx = bin(x, t) * nb;
            for (var k = c0; k < c1; k += 1u) {
                let base = (bx + bin(tm[co + k], t)) * nb;
                for (var m = e0; m < e1; m += 1u) {
                    let q = base + bin(tm[eo + m], t);
                    if (q < n3) { inc(q); }
                }
            }
            j += 1u;
        }
    }
}
