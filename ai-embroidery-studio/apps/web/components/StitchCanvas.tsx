"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Stitches } from "@/lib/api";

// Plays the stitch sequence decoded from the exported DST (not re-simulated from the SVG).
//   擬真  - each stitch drawn as a ~0.4 mm thread with sheen, shadow and needle holes on woven fabric
//   線條  - thin centre lines (shows the stitch path and spacing)
//   密度  - thread length per mm²: where the fabric gets stiff, puckers or needles may break
type Mode = "real" | "lines" | "density";
const THREAD_MM = 0.4;          // 40 wt embroidery thread is roughly 0.35-0.45 mm wide
const CELL_MM = 1;              // density grid
// Thread length per mm² of fabric. One layer of 0.4 mm tatami is ~2.5; underlay plus a top layer ~4.
const DENSITY_STOPS: [number, string][] = [[0, "rgba(0,0,0,0)"], [2, "rgba(80,170,90,.55)"], [4.5, "rgba(240,200,60,.7)"],
  [6.5, "rgba(240,130,40,.8)"], [9, "rgba(210,40,40,.85)"]];

export default function StitchCanvas({ data, fabricColor = "#efe9df" }: { data: Stitches; fabricColor?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const total = data.points.length / 4;
  const [pos, setPos] = useState(total);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [mode, setMode] = useState<Mode>("real");
  const [showJumps, setShowJumps] = useState(false);
  const [width, setWidth] = useState(320);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drawn = useRef<{ key: string; upTo: number }>({ key: "", upTo: 0 });

  useEffect(() => { setPos(total); setPlaying(false); setZoom(1); setPan({ x: 0, y: 0 }); }, [data, total]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const height = Math.round(Math.min(width * 1.1, Math.max(240, width * (data.heightMm / Math.max(data.widthMm, 1)) + 40)));
  const pad = 16, w = Math.max(data.widthMm, 1), h = Math.max(data.heightMm, 1);
  const k0 = Math.min((width - 2 * pad) / w, (height - 2 * pad) / h);
  const k = k0 * zoom;                                     // screen px per mm
  const ox = (width - w * k) / 2 + pan.x, oy = (height - h * k) / 2 + pan.y;

  const density = useMemo(() => densityGrid(data), [data]);

  const draw = useCallback((from: number, to: number, clear: boolean) => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const ctx = cv.getContext("2d")!;
    if (clear) {
      cv.width = width * dpr; cv.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      paintFabric(ctx, width, height, k, ox, oy, fabricColor, mode === "real");
    } else {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    const P = data.points;
    if (mode === "density") {
      if (clear) paintDensity(ctx, density, k, ox, oy);
      drawLines(ctx, P, from, to, k, ox, oy, data.colors, 0.6, "rgba(0,0,0,.25)", showJumps);
    } else if (mode === "lines") {
      drawLines(ctx, P, from, to, k, ox, oy, data.colors, Math.max(0.8, Math.min(2, 0.25 * k)), null, showJumps);
    } else {
      drawThread(ctx, P, from, to, k, ox, oy, data.colors, showJumps);
    }
  }, [data, width, height, k, ox, oy, mode, density, showJumps, fabricColor]);

  // Full redraw when the view changes; while playing forward only the new stitches are added
  // (later stitches lie on top of earlier ones, so drawing in order is exact).
  useEffect(() => {
    const key = `${width}|${height}|${k}|${ox}|${oy}|${mode}|${showJumps}|${data.revision}|${total}`;
    const n = Math.min(pos, total);
    if (drawn.current.key === key && n >= drawn.current.upTo) {
      if (n > drawn.current.upTo) draw(drawn.current.upTo, n, false);
    } else {
      draw(0, n, true);
    }
    drawn.current = { key, upTo: n };
  }, [draw, pos, total, width, height, k, ox, oy, mode, showJumps, data.revision]);

  useEffect(() => {
    if (!playing) return;
    let raf = 0, last = performance.now();
    const tick = (t: number) => {
      const step = Math.max(1, Math.round(((t - last) / 1000) * 400 * speed));
      last = t;
      setPos(p => {
        const next = Math.min(total, p + step);
        if (next >= total) setPlaying(false);
        return next;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, total]);

  // Drag to pan, wheel / pinch to zoom around the pointer.
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number; zoom: number } | null>(null);
  const zoomAt = (nz: number, cx: number, cy: number) => {
    const z = Math.min(12, Math.max(1, nz));
    const f = z / zoom;
    // keep the point under (cx, cy) fixed
    const cx0 = width / 2, cy0 = height / 2;
    setPan(p => (z === 1 ? { x: 0, y: 0 } : { x: (p.x - (cx - cx0)) * f + (cx - cx0), y: (p.y - (cy - cy0)) * f + (cy - cy0) }));
    setZoom(z);
  };
  const local = (e: { clientX: number; clientY: number }) => {
    const r = canvasRef.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <div className="inline-flex overflow-hidden rounded-md border border-line" role="group" aria-label="預覽模式">
          {([["real", "擬真"], ["lines", "線條"], ["density", "密度"]] as const).map(([m, label]) => (
            <button key={m} type="button" onClick={() => setMode(m)}
              className={`px-3 py-1 ${mode === m ? "bg-accent text-accent-ink" : "bg-panel"}`}>{label}</button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <button type="button" className="btn px-2 py-1" aria-label="縮小" onClick={() => zoomAt(zoom / 1.5, width / 2, height / 2)}>−</button>
          <span className="w-12 text-center tabular-nums">{Math.round(zoom * 100)}%</span>
          <button type="button" className="btn px-2 py-1" aria-label="放大" onClick={() => zoomAt(zoom * 1.5, width / 2, height / 2)}>＋</button>
        </div>
      </div>
      <div ref={wrapRef} className="w-full min-w-0">
        <canvas ref={canvasRef} style={{ width: "100%", maxWidth: width, height, touchAction: "none" }}
          className="block cursor-grab rounded-lg" aria-label="針跡預覽"
          onWheel={e => { const p = local(e); zoomAt(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), p.x, p.y); }}
          onPointerDown={e => { (e.target as Element).setPointerCapture(e.pointerId); pointers.current.set(e.pointerId, local(e)); }}
          onPointerMove={e => {
            const prev = pointers.current.get(e.pointerId);
            if (!prev) return;
            const cur = local(e);
            pointers.current.set(e.pointerId, cur);
            const pts = [...pointers.current.values()];
            if (pts.length === 2) {
              const d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
              if (!pinch.current) pinch.current = { dist: d, zoom };
              else zoomAt(pinch.current.zoom * d / pinch.current.dist, (pts[0].x + pts[1].x) / 2, (pts[0].y + pts[1].y) / 2);
            } else if (zoom > 1) {
              setPan(p => ({ x: p.x + cur.x - prev.x, y: p.y + cur.y - prev.y }));
            }
          }}
          onPointerUp={e => { pointers.current.delete(e.pointerId); if (pointers.current.size < 2) pinch.current = null; }}
          onPointerCancel={e => { pointers.current.delete(e.pointerId); pinch.current = null; }} />
      </div>
      {mode === "density" && (
        <div className="mt-2 space-y-1 text-xs text-muted">
          <div className="flex items-center gap-2">
            <span>疏</span>
            <span className="h-2 flex-1 rounded" style={{ background: `linear-gradient(90deg, ${DENSITY_STOPS.slice(1).map(s => s[1]).join(",")})` }} />
            <span>密</span>
          </div>
          <p>每 mm² 的線長。綠＝正常；橘紅＝太密，布會變硬、起皺，或斷針。
            {density.hotShare > 0.02 && <span className="text-warn">　約 {Math.round(density.hotShare * 100)}% 的繡面偏密。</span>}
          </p>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <button className="btn py-1" onClick={() => { if (!playing && pos >= total) setPos(0); setPlaying(!playing); }}>
          {playing ? "暫停" : "播放"}
        </button>
        <input type="range" min={0} max={total} value={pos} onChange={e => { setPlaying(false); setPos(+e.target.value); }}
          className="min-w-40 flex-1" aria-label="時間線" />
        <label className="flex items-center gap-1 whitespace-nowrap">速度
          <select className="field w-auto py-1" value={speed} onChange={e => setSpeed(+e.target.value)}>
            {[0.25, 0.5, 1, 2, 4, 8].map(s => <option key={s} value={s}>{s}x</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={showJumps} onChange={e => setShowJumps(e.target.checked)} />跳針</label>
      </div>
      <p className="mt-2 text-xs text-muted">
        由匯出的 DST 重新解碼。擬真模式依 0.4 mm 線寬繪製並模擬光澤與陰影，可縮放（滾輪／雙指）及拖曳查看細節；
        不是物理模擬，實際效果仍以試繡為準。
      </p>
    </div>
  );
}

// ---------- drawing ----------

function shade(hex: string, amt: number) {
  const n = /^#[0-9a-f]{6}$/i.test(hex) ? parseInt(hex.slice(1), 16) : 0x888888;
  const f = (c: number) => Math.round(amt < 0 ? c * (1 + amt) : c + (255 - c) * amt);
  return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`;
}

function paintFabric(ctx: CanvasRenderingContext2D, W: number, H: number, k: number, ox: number, oy: number,
  color: string, weave: boolean) {
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, W, H);
  if (!weave) return;
  // Plain weave: warp and weft yarns ~0.5 mm apart, only drawn when they are at least 3 px apart.
  const step = 0.5 * k;
  if (step < 3) return;
  ctx.save();
  ctx.lineWidth = Math.max(0.5, step * 0.35);
  ctx.strokeStyle = shade(color, -0.06);
  ctx.beginPath();
  for (let x = ((ox % step) + step) % step; x < W; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
  ctx.stroke();
  ctx.strokeStyle = shade(color, -0.1);
  ctx.globalAlpha = 0.6;
  ctx.beginPath();
  for (let y = ((oy % step) + step) % step; y < H; y += step) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
  ctx.stroke();
  ctx.restore();
}

function drawLines(ctx: CanvasRenderingContext2D, P: number[], from: number, to: number, k: number, ox: number, oy: number,
  colors: string[], lw: number, override: string | null, jumps: boolean) {
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  let px: number | null = null, py = 0;
  if (from > 0) { const i = from - 1; px = ox + P[i * 4] * k; py = oy + P[i * 4 + 1] * k; }
  for (let i = from; i < to; i++) {
    const x = ox + P[i * 4] * k, y = oy + P[i * 4 + 1] * k, cmd = P[i * 4 + 2], c = P[i * 4 + 3];
    if (cmd === 0 && px !== null) {
      ctx.strokeStyle = override ?? colors[c] ?? "#888"; ctx.lineWidth = lw;
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke();
    } else if (cmd === 1 && jumps && px !== null) {
      ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(210,50,50,.6)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke(); ctx.restore();
    }
    if (cmd !== 3) { px = x; py = y; }
  }
}

function drawThread(ctx: CanvasRenderingContext2D, P: number[], from: number, to: number, k: number, ox: number, oy: number,
  colors: string[], jumps: boolean) {
  const tw = Math.max(1, THREAD_MM * k);
  const detailed = tw >= 2.5;                           // sheen gradients only when the thread is wide enough to see
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  let px: number | null = null, py = 0;
  if (from > 0) { const i = from - 1; px = ox + P[i * 4] * k; py = oy + P[i * 4 + 1] * k; }
  const cache = new Map<number, { base: string; dark: string; light: string }>();
  const tone = (c: number) => {
    let t = cache.get(c);
    if (!t) { const b = colors[c] ?? "#888888"; t = { base: b, dark: shade(b, -0.38), light: shade(b, 0.42) }; cache.set(c, t); }
    return t;
  };
  for (let i = from; i < to; i++) {
    const x = ox + P[i * 4] * k, y = oy + P[i * 4 + 1] * k, cmd = P[i * 4 + 2], c = P[i * 4 + 3];
    if (cmd === 0 && px !== null) {
      const dx = x - px, dy = y - py, len = Math.hypot(dx, dy);
      if (len > 0.01) {
        const t = tone(c);
        // shadow cast onto the fabric / threads below
        ctx.strokeStyle = "rgba(0,0,0,.22)"; ctx.lineWidth = tw * 1.1;
        ctx.beginPath(); ctx.moveTo(px + tw * 0.18, py + tw * 0.25); ctx.lineTo(x + tw * 0.18, y + tw * 0.25); ctx.stroke();
        if (detailed) {
          // rounded thread: dark edges, highlight along the top
          const nx = -dy / len * tw / 2, ny = dx / len * tw / 2, mx = (px + x) / 2, my = (py + y) / 2;
          const g = ctx.createLinearGradient(mx - nx, my - ny, mx + nx, my + ny);
          g.addColorStop(0, t.dark); g.addColorStop(0.3, t.base); g.addColorStop(0.45, t.light);
          g.addColorStop(0.62, t.base); g.addColorStop(1, t.dark);
          ctx.strokeStyle = g;
        } else {
          ctx.strokeStyle = t.base;
        }
        ctx.lineWidth = tw;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke();
        if (detailed) {
          // needle penetration at the stitch end
          ctx.fillStyle = "rgba(0,0,0,.28)";
          ctx.beginPath(); ctx.arc(x, y, tw * 0.22, 0, Math.PI * 2); ctx.fill();
        }
      }
    } else if (cmd === 1 && jumps && px !== null) {
      ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(210,50,50,.6)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke(); ctx.restore();
    }
    if (cmd !== 3) { px = x; py = y; }
  }
}

// ---------- density ----------

interface Density { cols: number; rows: number; cells: Float32Array; hotShare: number }

function densityGrid(data: Stitches): Density {
  const cols = Math.max(1, Math.ceil(data.widthMm / CELL_MM)), rows = Math.max(1, Math.ceil(data.heightMm / CELL_MM));
  const cells = new Float32Array(cols * rows);
  const P = data.points;
  let px: number | null = null, py = 0;
  for (let i = 0; i < P.length / 4; i++) {
    const x = P[i * 4], y = P[i * 4 + 1], cmd = P[i * 4 + 2];
    if (cmd === 0 && px !== null) {
      const len = Math.hypot(x - px, y - py), n = Math.max(1, Math.ceil(len / 0.25));
      for (let s = 0; s < n; s++) {
        const t = (s + 0.5) / n, cx = Math.floor((px + (x - px) * t) / CELL_MM), cy = Math.floor((py + (y - py) * t) / CELL_MM);
        if (cx >= 0 && cy >= 0 && cx < cols && cy < rows) cells[cy * cols + cx] += len / n;
      }
    }
    if (cmd !== 3) { px = x; py = y; }
  }
  let covered = 0, hot = 0;
  for (const v of cells) { if (v > 1) covered++; if (v > 6.5) hot++; }
  return { cols, rows, cells, hotShare: covered ? hot / covered : 0 };
}

function densityColor(v: number) {
  for (let i = DENSITY_STOPS.length - 1; i >= 0; i--) if (v >= DENSITY_STOPS[i][0]) return DENSITY_STOPS[i][1];
  return DENSITY_STOPS[0][1];
}

function paintDensity(ctx: CanvasRenderingContext2D, d: Density, k: number, ox: number, oy: number) {
  const s = CELL_MM * k;
  for (let r = 0; r < d.rows; r++) for (let c = 0; c < d.cols; c++) {
    const v = d.cells[r * d.cols + c];
    if (v < 0.5) continue;
    ctx.fillStyle = densityColor(v);
    ctx.fillRect(ox + c * s, oy + r * s, Math.ceil(s), Math.ceil(s));
  }
}
