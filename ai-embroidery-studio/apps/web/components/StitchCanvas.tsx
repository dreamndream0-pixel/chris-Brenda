"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Stitches } from "@/lib/api";

// Plays the stitch sequence decoded from the exported DST (not re-simulated from the SVG).
export default function StitchCanvas({ data }: { data: Stitches }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const total = data.points.length / 4;
  const [pos, setPos] = useState(total);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [showPoints, setShowPoints] = useState(false);
  const [showJumps, setShowJumps] = useState(true);
  const [width, setWidth] = useState(320);

  useEffect(() => { setPos(total); setPlaying(false); }, [data, total]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const height = Math.round(Math.min(width * 0.75, Math.max(220, width * (data.heightMm / Math.max(data.widthMm, 1)) + 40)));

  const draw = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = width * dpr; cv.height = height * dpr;
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const pad = 20, w = Math.max(data.widthMm, 1), h = Math.max(data.heightMm, 1);
    const k = Math.min((width - 2 * pad) / w, (height - 2 * pad) / h);
    const ox = (width - w * k) / 2, oy = (height - h * k) / 2;
    const P = data.points, n = Math.min(pos, total);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const lw = Math.max(0.8, Math.min(3, 0.3 * k));
    let px: number | null = null, py = 0;
    for (let i = 0; i < n; i++) {
      const x = ox + P[i * 4] * k, y = oy + P[i * 4 + 1] * k, cmd = P[i * 4 + 2], c = P[i * 4 + 3];
      if (cmd === 0 && px !== null) {
        ctx.strokeStyle = data.colors[c] ?? "#888"; ctx.lineWidth = lw;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke();
        if (showPoints) { ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(x - 1, y - 1, 2, 2); }
      } else if (cmd === 1 && showJumps && px !== null) {
        ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(210,50,50,.6)"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke(); ctx.restore();
      }
      if (cmd !== 3) { px = x; py = y; }
    }
  }, [data, pos, total, width, height, showPoints, showJumps]);

  useEffect(draw, [draw]);

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

  return (
    <div>
      <div ref={wrapRef} className="w-full min-w-0">
        <canvas ref={canvasRef} style={{ width: "100%", maxWidth: width, height }} className="block rounded-lg bg-fabric" aria-label="針跡預覽" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <button className="btn py-1" onClick={() => { if (!playing && pos >= total) setPos(0); setPlaying(!playing); }}>
          {playing ? "暫停" : "播放"}
        </button>
        <input type="range" min={0} max={total} value={pos} onChange={e => { setPlaying(false); setPos(+e.target.value); }}
          className="min-w-40 flex-1" aria-label="時間線" />
        <label className="flex items-center gap-1 whitespace-nowrap">速度
          <select className="field w-auto py-1" value={speed} onChange={e => setSpeed(+e.target.value)}>
            {[0.25, 0.5, 1, 2, 4].map(s => <option key={s} value={s}>{s}x</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={showPoints} onChange={e => setShowPoints(e.target.checked)} />針點</label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={showJumps} onChange={e => setShowJumps(e.target.checked)} />跳針</label>
      </div>
      <p className="mt-2 text-xs text-muted">由匯出的 DST 重新解碼播放；僅 2D 示意，不代表布料張力。</p>
    </div>
  );
}
