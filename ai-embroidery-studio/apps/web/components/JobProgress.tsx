"use client";
import { useEffect, useState } from "react";

export interface Progress { label: string; percent: number; startedAt: number; estimateS?: number | null }

// The server reports coarse steps (e.g. 10% when Ink/Stitch starts, 85% when it finishes). While a
// long step runs, the bar keeps moving towards the next step using the time estimate, and never
// claims more than the next step's value.
export default function JobProgress({ p }: { p: Progress }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, []);
  const elapsed = Math.max(0, (now - p.startedAt) / 1000);
  let shown = p.percent;
  if (p.percent >= 10 && p.percent < 85) {
    const t = p.estimateS && p.estimateS > 0 ? elapsed / p.estimateS : 1 - Math.exp(-elapsed / 90);
    shown = Math.max(p.percent, 10 + 72 * Math.min(1, t));
  }
  const remaining = p.estimateS ? Math.max(0, p.estimateS - elapsed) : null;
  return (
    <div className="space-y-1" role="status" aria-live="polite">
      <div className="flex justify-between text-xs text-muted">
        <span>{p.label}</span>
        <span>{fmt(elapsed)}{remaining !== null && remaining > 0 ? `・約剩 ${fmt(remaining)}` : ""}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-fabric">
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${Math.round(shown)}%` }} />
      </div>
    </div>
  );
}

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
