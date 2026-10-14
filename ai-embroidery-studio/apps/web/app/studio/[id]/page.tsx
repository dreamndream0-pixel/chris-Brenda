"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import RasterOptionsFields, { DEFAULT_RASTER, toAnalyzeOptions, type RasterChoice } from "@/components/RasterOptionsFields";
import StitchCanvas from "@/components/StitchCanvas";
import { api, ApiError, waitForJob, type FabricPreset, type Job, type ProjectDetail, type RegionPatch, type Stitches } from "@/lib/api";
import { errorMessage, FABRICS, fabricLabel, JOB_STATUS, PROJECT_STATUS, warningLabel } from "@/lib/labels";

const DOWNLOADS: { kind: string; label: string }[] = [
  { kind: "export_zip", label: "工廠交件 ZIP" },
  { kind: "dst", label: "DST" },
  { kind: "pes", label: "PES" },
  { kind: "design_svg", label: "Ink/Stitch SVG" },
  { kind: "spec_txt", label: "規格表" },
];

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [stitches, setStitches] = useState<Stitches | null>(null);
  const [width, setWidth] = useState(0);
  const [height, setHeight] = useState(0);
  const [lock, setLock] = useState(true);
  const [fabric, setFabric] = useState<FabricPreset>("woven_cotton");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compileResult, setCompileResult] = useState<Job["result"]>(null);
  const [regionEdits, setRegionEdits] = useState<Record<string, Omit<RegionPatch, "id">>>({});
  const [paletteEdits, setPaletteEdits] = useState<Record<string, string>>({});
  const [previews, setPreviews] = useState<{ source_preview?: string; quantized_preview?: string }>({});
  const [raster, setRaster] = useState<RasterChoice>(DEFAULT_RASTER);

  const load = useCallback(async () => {
    try {
      const d = await api.getProject(id);
      setDetail(d);
      setRegionEdits({}); setPaletteEdits({});
      if (d.design) {
        setWidth(d.design.sizeMm.width); setHeight(d.design.sizeMm.height);
        setLock(d.design.lockAspect); setFabric(d.design.fabricPreset);
        const r = d.design.raster;
        if (r) {
          setRaster({ colors: r.autoColors ? null : r.colors.length, bgMode: "auto", bgHex: r.backgroundHex ?? "#ffffff" });
          setPreviews(await api.previews(id, d.project.currentRevision));
        } else setPreviews({});
      }
      const lastCompile = d.jobs.find(j => j.kind === "compile" && j.status === "ready" && j.revision === d.project.compiledRevision);
      setCompileResult(lastCompile?.result ?? null);
      setStitches(d.project.compiledRevision ? await api.stitches(id, d.project.compiledRevision) : null);
    } catch (e) {
      setError(errorMessage(e instanceof ApiError ? e.code : "unknown"));
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (!detail) return <p className="text-muted">{error ?? "載入中…"}</p>;
  const { project, design } = detail;
  if (!design) return <p className="card p-4">這個專案還沒有成功匯入的設計。<Link className="underline" href="/studio/new">重新上傳</Link></p>;

  const regionPatches: RegionPatch[] = Object.entries(regionEdits).map(([rid, e]) => ({ id: rid, ...e }));
  const palettePatches = Object.entries(paletteEdits).map(([cid, hex]) => ({ id: cid, hex }));
  const dirty = width !== design.sizeMm.width || (!lock && height !== design.sizeMm.height)
    || lock !== design.lockAspect || fabric !== design.fabricPreset || regionPatches.length > 0 || palettePatches.length > 0;
  const regionValue = <K extends keyof Omit<RegionPatch, "id">>(rid: string, key: K, fallback: NonNullable<RegionPatch[K]>) =>
    (regionEdits[rid]?.[key] ?? fallback) as NonNullable<RegionPatch[K]>;
  const editRegion = (rid: string, patch: Omit<RegionPatch, "id">) =>
    setRegionEdits(prev => ({ ...prev, [rid]: { ...prev[rid], ...patch } }));
  const visibleCount = design.regions.filter(reg => !regionValue(reg.id, "hidden", !!reg.hidden)).length;
  const aspect = design.geometry.viewBox[3] / design.geometry.viewBox[2];
  const shownHeight = lock ? Math.round(width * aspect * 100) / 100 : height;
  const compiled = project.compiledRevision;
  const stale = compiled !== null && compiled !== project.currentRevision;
  const colors = Object.fromEntries(design.palette.map(c => [c.id, paletteEdits[c.id] ?? c.hex]));
  const regionWarnings = [...new Set(design.regions.flatMap(r => r.warnings))];
  const artifactsFor = (rev: number | null) => detail.artifacts.filter(a => a.revision === rev);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setError(null);
    try { await fn(); } catch (e) { setError(errorMessage(e instanceof ApiError ? e.code : "unknown")); }
    finally { setBusy(null); }
  };

  const saveAndCompile = () => run("儲存設定", async () => {
    let revision = project.currentRevision;
    if (dirty) {
      const res = await api.patchDesign(id, { baseRevision: revision, lockAspect: lock, fabricPreset: fabric,
        sizeMm: { width, height: lock ? undefined : height },
        regions: regionPatches.length ? regionPatches : undefined, palette: palettePatches.length ? palettePatches : undefined });
      revision = res.revision;
    }
    setBusy("排隊中");
    const job = await waitForJob(await api.compile(id, revision), j => setBusy(JOB_STATUS[j.status] ?? j.status));
    if (job.status === "failed") setError(errorMessage(job.errorCode));
    await load();
  });

  const reanalyze = () => run("重新分析", async () => {
    if (!design.source?.uploadId) return;
    const job = await waitForJob(await api.analyze(id, design.source.uploadId, { ...toAnalyzeOptions(raster), widthMm: width }),
      j => setBusy(JOB_STATUS[j.status] ?? j.status));
    if (job.status === "failed") { setError(errorMessage(job.errorCode)); return; }
    await load();
  });

  const exportZip = () => run("打包中", async () => {
    if (compiled === null) return;
    const job = await waitForJob(await api.exportZip(id, compiled), j => setBusy(JOB_STATUS[j.status] ?? j.status));
    if (job.status === "failed") { setError(errorMessage(job.errorCode)); return; }
    await load();
  });

  const download = (artifactId: string) => run("產生下載連結", async () => {
    const { url } = await api.downloadUrl(id, artifactId);
    window.location.assign(url);
  });

  const r = compileResult as { stitches?: number; widthMm?: number; heightMm?: number; colorChanges?: number; jumps?: number; trims?: number; warnings?: string[] } | null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/studio" className="text-sm text-muted">← 我的專案</Link>
          <h1 className="text-2xl font-semibold">{project.name}</h1>
          <p className="text-sm text-muted">
            {PROJECT_STATUS[project.status]} · 目前 revision {project.currentRevision}
            {design.source?.filename ? ` · ${design.source.filename}` : ""}
          </p>
        </div>
      </div>

      {error && <p className="card border-bad p-3 text-bad" role="alert">{error}</p>}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="card min-w-0 p-4">
          {stale && (
            <p className="mb-3 rounded-md border border-warn px-3 py-2 text-sm text-warn">
              預覽來自 revision {compiled}，目前設定是 revision {project.currentRevision}，請重新編譯。
            </p>
          )}
          {stitches ? <StitchCanvas data={stitches} /> : (
            <div className="flex h-64 items-center justify-center rounded-lg bg-fabric text-muted">尚未編譯。調整右側設定後按「儲存並編譯」。</div>
          )}
          {r && (
            <dl className="mt-4 grid grid-cols-3 gap-3 text-sm sm:grid-cols-6">
              {[["針數", r.stitches?.toLocaleString()], ["寬", `${r.widthMm} mm`], ["高", `${r.heightMm} mm`],
                ["線色", stitches?.summary.color_blocks], ["換色", r.colorChanges], ["跳針／剪線", `${r.jumps} / ${r.trims}`]]
                .map(([k, v]) => <div key={k as string}><dt className="text-muted">{k}</dt><dd className="font-medium">{v ?? "—"}</dd></div>)}
            </dl>
          )}
        </section>

        <aside className="space-y-4">
          <div className="card space-y-3 p-4">
            <h2 className="font-medium">尺寸與布料</h2>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-sm">寬（mm）
                <input type="number" className="field mt-1" min={5} max={300} step={0.5} value={width} onChange={e => setWidth(+e.target.value)} />
              </label>
              <label className="text-sm">高（mm）
                <input type="number" className="field mt-1" min={5} max={300} step={0.5} value={shownHeight} disabled={lock} onChange={e => setHeight(+e.target.value)} />
              </label>
            </div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={lock} onChange={e => { setLock(e.target.checked); setHeight(shownHeight); }} />鎖定比例</label>
            <label className="block text-sm">布料
              <select className="field mt-1" value={fabric} onChange={e => setFabric(e.target.value as FabricPreset)}>
                {FABRICS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
              </select>
            </label>
            {fabric !== design.fabricPreset && <p className="text-xs text-muted">更換布料會把所有區域參數重設為「{fabricLabel(fabric)}」預設值。</p>}
            <button className="btn btn-primary w-full justify-center" disabled={!!busy} onClick={saveAndCompile}>
              {busy ?? (dirty ? "儲存並編譯" : stale || compiled === null ? "編譯" : "重新編譯")}
            </button>
          </div>

          <div className="card space-y-2 p-4">
            <h2 className="font-medium">匯出</h2>
            {compiled === null ? <p className="text-sm text-muted">編譯成功後才能匯出。</p> : (
              <>
                <button className="btn w-full justify-center" disabled={!!busy || stale} onClick={exportZip}>
                  產生工廠交件包（revision {compiled}）
                </button>
                <ul className="space-y-1 text-sm">
                  {DOWNLOADS.map(d => {
                    const a = artifactsFor(compiled).find(x => x.kind === d.kind);
                    return a ? (
                      <li key={d.kind} className="flex items-center justify-between">
                        <span>{d.label}</span>
                        <button className="underline" onClick={() => download(a.id)} disabled={!!busy}>下載</button>
                      </li>
                    ) : null;
                  })}
                </ul>
                <p className="text-xs text-muted">DST 不含線色；請以規格表的線色順序上線。技術匯出成功不代表免試繡。</p>
              </>
            )}
          </div>

          {design.raster && (
            <div className="card space-y-3 p-4">
              <h2 className="font-medium">圖片轉向量</h2>
              <div className="grid grid-cols-2 gap-2 text-xs text-muted">
                {([["source_preview", "原圖"], ["quantized_preview", `分色結果（${design.raster.colors.length} 色）`]] as const).map(([k, label]) => (
                  <figure key={k} className="space-y-1">
                    {previews[k] ? <img src={previews[k]} alt={label} className="aspect-square w-full rounded border border-line bg-fabric object-contain" />
                      : <div className="aspect-square rounded border border-line bg-fabric" />}
                    <figcaption>{label}</figcaption>
                  </figure>
                ))}
              </div>
              <RasterOptionsFields value={raster} onChange={setRaster} />
              <button className="btn w-full justify-center" disabled={!!busy} onClick={reanalyze}>以這些設定重新分析</button>
              <p className="text-xs text-muted">重新分析會產生新版本，並取代下方對區域的手動修改。</p>
            </div>
          )}

          <div className="card space-y-3 p-4">
            <h2 className="font-medium">線色</h2>
            <ul className="flex flex-wrap gap-3 text-sm">
              {design.palette.map((c, i) => (
                <li key={c.id} className="flex items-center gap-1.5">
                  <input type="color" value={colors[c.id]} aria-label={`線色 ${i + 1}`}
                    onChange={e => setPaletteEdits(prev => ({ ...prev, [c.id]: e.target.value }))}
                    className="h-7 w-9 cursor-pointer rounded border border-line" />
                  <code className="text-xs text-muted">{colors[c.id]}</code>
                </li>
              ))}
            </ul>
          </div>

          <div className="card space-y-2 p-4">
            <h2 className="font-medium">區域（{visibleCount}/{design.regions.length} 繡製）</h2>
            <ul className="max-h-80 space-y-2 overflow-auto text-sm">
              {design.regions.map(reg => {
                const hidden = regionValue(reg.id, "hidden", !!reg.hidden);
                const colorId = regionValue(reg.id, "colorId", reg.colorId);
                return (
                  <li key={reg.id} className={`flex items-center gap-2 ${hidden ? "opacity-50" : ""}`}>
                    <input type="checkbox" checked={!hidden} aria-label={`繡製 ${reg.name}`}
                      disabled={!hidden && visibleCount <= 1}
                      onChange={e => editRegion(reg.id, { hidden: !e.target.checked })} />
                    <span className="inline-block h-3.5 w-3.5 rounded-sm border border-line" style={{ background: colors[colorId] }} />
                    <span className="min-w-0 flex-1 truncate">{reg.name}</span>
                    {design.palette.length > 1 && (
                      <select className="field w-auto px-1 py-0.5 text-xs" value={colorId} aria-label={`${reg.name} 線色`}
                        onChange={e => editRegion(reg.id, { colorId: e.target.value })}>
                        {design.palette.map((c, i) => <option key={c.id} value={c.id}>色 {i + 1}</option>)}
                      </select>
                    )}
                    <select className="field w-auto px-1 py-0.5 text-xs" value={regionValue(reg.id, "stitchType", reg.stitchType)}
                      aria-label={`${reg.name} 針法`} onChange={e => editRegion(reg.id, { stitchType: e.target.value as "fill" | "running" })}>
                      <option value="fill">填針</option>
                      <option value="running">平針</option>
                    </select>
                  </li>
                );
              })}
            </ul>
            <p className="text-xs text-muted">平針會沿區域外框走一圈，內部不填滿。取消勾選＝不繡這個區域。</p>
            {(regionPatches.length > 0 || palettePatches.length > 0) && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-warn">有未儲存的修改，按「儲存並編譯」套用。</span>
                <button className="underline" onClick={() => { setRegionEdits({}); setPaletteEdits({}); }}>還原</button>
              </div>
            )}
          </div>

          {[...design.warnings, ...regionWarnings, ...(r?.warnings ?? [])].length > 0 && (
            <div className="card space-y-1 p-4 text-sm">
              <h2 className="font-medium">提醒</h2>
              <ul className="list-disc space-y-1 pl-5 text-warn">
                {[...new Set([...design.warnings, ...regionWarnings, ...(r?.warnings ?? [])])].map(w => <li key={w}>{warningLabel(w)}</li>)}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
