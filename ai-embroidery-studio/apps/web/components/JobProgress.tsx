"use client";
import { useEffect, useState } from "react";

export interface Progress {
  label: string; percent: number; startedAt: number;
  stepStartedAt?: number;      // when `percent` last changed
  estimateS?: number | null;   // expected time for the long engine step (compile only)
  hint?: string | null;
}

// The server reports coarse steps (e.g. 10% when Ink/Stitch starts, 85% when it finishes). While a
// long step runs, the bar keeps creeping towards the next step: by the time estimate when there is
// one, otherwise asymptotically, so it never claims to be done before the server says so.
export default function JobProgress({ p }: { p: Progress }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, []);
  const elapsed = Math.max(0, (now - p.startedAt) / 1000);
  const inStep = Math.max(0, (now - (p.stepStartedAt ?? p.startedAt)) / 1000);
  let shown = p.percent;
  if (p.estimateS && p.estimateS > 0 && p.percent >= 10 && p.percent < 85) {
    shown = Math.max(p.percent, 10 + 72 * Math.min(1, elapsed / p.estimateS));
  } else if (p.percent < 95) {
    shown = p.percent + (95 - p.percent) * 0.6 * (1 - Math.exp(-inStep / 30));
  }
  const remaining = p.estimateS ? Math.max(0, p.estimateS - elapsed) : null;
  return (
    <div className="space-y-1" role="status" aria-live="polite">
      <div className="flex justify-between gap-2 text-xs text-muted">
        <span>{p.label}</span>
        <span className="whitespace-nowrap">{fmt(elapsed)}{remaining !== null && remaining > 0 ? `・約剩 ${fmt(remaining)}` : ""}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-fabric">
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${Math.round(shown)}%` }} />
      </div>
      {p.hint && <p className="text-xs text-muted">{p.hint}</p>}
    </div>
  );
}

// Keeps stepStartedAt in sync: a new percent starts a new step.
export function nextProgress(prev: Progress | null, label: string, percent: number, extra: Partial<Progress> = {}): Progress {
  const now = Date.now();
  const startedAt = prev?.startedAt ?? extra.startedAt ?? now;
  const stepStartedAt = prev && prev.percent === percent ? prev.stepStartedAt ?? now : now;
  return { ...prev, ...extra, label, percent, startedAt, stepStartedAt };
}

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
