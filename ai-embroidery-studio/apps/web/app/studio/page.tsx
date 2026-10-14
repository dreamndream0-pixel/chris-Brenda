"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, getDevUser, type Project } from "@/lib/api";
import { errorMessage, fabricLabel, PROJECT_STATUS } from "@/lib/labels";

export default function StudioPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!getDevUser()) { setError(errorMessage("not_authenticated")); return; }
    api.listProjects().then(setProjects).catch((e: ApiError) => setError(errorMessage(e.code)));
  }, []);

  const shown = useMemo(() => (projects ?? []).filter(p => p.name.toLowerCase().includes(query.toLowerCase())), [projects, query]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">我的專案</h1>
        <div className="flex gap-2">
          <input className="field w-48" placeholder="搜尋專案" value={query} onChange={e => setQuery(e.target.value)} aria-label="搜尋專案" />
          <Link href="/studio/new" className="btn btn-primary">＋ 新增專案</Link>
        </div>
      </div>
      {error && <p className="card p-4 text-bad">{error}</p>}
      {projects && shown.length === 0 && (
        <div className="card p-8 text-center text-muted">
          {projects.length === 0 ? "還沒有專案。上傳一個 SVG 開始吧。" : "沒有符合的專案。"}
        </div>
      )}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map(p => (
          <li key={p.id}>
            <Link href={`/studio/${p.id}`} className="card block p-4 hover:border-accent">
              <div className="flex items-start justify-between gap-2">
                <h2 className="font-medium">{p.name}</h2>
                <span className="rounded-full border border-line px-2 py-0.5 text-xs">{PROJECT_STATUS[p.status] ?? p.status}</span>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-y-1 text-sm">
                <dt className="text-muted">尺寸</dt><dd>{p.widthMm && p.heightMm ? `${p.widthMm} × ${p.heightMm} mm` : "—"}</dd>
                <dt className="text-muted">線色</dt><dd>{p.colorCount ?? "—"}</dd>
                <dt className="text-muted">針數</dt><dd>{p.stitchCount?.toLocaleString() ?? "未編譯"}</dd>
                <dt className="text-muted">布料</dt><dd>{fabricLabel(p.fabricPreset)}</dd>
                <dt className="text-muted">更新</dt><dd>{new Date(p.updatedAt).toLocaleString("zh-TW")}</dd>
              </dl>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
