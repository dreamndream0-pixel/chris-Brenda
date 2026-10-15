"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import RasterOptionsFields, { DEFAULT_RASTER, toAnalyzeOptions, type RasterChoice } from "@/components/RasterOptionsFields";
import JobProgress, { nextProgress, type Progress } from "@/components/JobProgress";
import RegionMap, { RegionThumb } from "@/components/RegionMap";
import StitchCanvas from "@/components/StitchCanvas";
import { api, ApiError, waitForJob, type AppConfig, type DetailLevel, type FabricPreset, type Job, type ProjectDetail, type RegionPatch, type Stitches, type StitchType } from "@/lib/api";
import { DETAIL_LEVELS, errorMessage, FABRICS, fabricLabel, JOB_STATUS, jobLabel, planReason, PROJECT_STATUS, STITCH_LABEL, warningLabel } from "@/lib/labels";

const DETAIL_COST: Record<DetailLevel, number> = { standard: 1, fine: 1.15, ultra: 1.35 };

// Expected compile time from this project's last successful compile, scaled by stitched area and detail.
function estimateCompileS(jobs: Job[], widthMm: number, heightMm: number, detail: DetailLevel, prevDetail: DetailLevel): number | null {
  const last = jobs.find(j => j.kind === "compile" && j.status === "ready" && j.createdAt && j.updatedAt && j.result);
  if (!last) return null;
  const took = (Date.parse(last.updatedAt!) - Date.parse(last.createdAt!)) / 1000;
  const r = last.result as { widthMm?: number; heightMm?: number };
  if (!(took > 0) || !r.widthMm || !r.heightMm) return null;
  const scale = (widthMm * heightMm) / (r.widthMm * r.heightMm);
  return Math.max(5, took * scale * DETAIL_COST[detail] / DETAIL_COST[prevDetail]);
}

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
  // Text, not numbers: a cleared number field would otherwise snap to "0" and typing gives "08".
  const [widthText, setWidthText] = useState("");
  const [heightText, setHeightText] = useState("");
  const [level, setLevel] = useState<DetailLevel>("standard");
  const [progress, setProgress] = useState<Progress | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [lock, setLock] = useState(true);
  const [fabric, setFabric] = useState<FabricPreset>("woven_cotton");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compileResult, setCompileResult] = useState<Job["result"]>(null);
  const [regionEdits, setRegionEdits] = useState<Record<string, Omit<RegionPatch, "id">>>({});
  const [paletteEdits, setPaletteEdits] = useState<Record<string, string>>({});
  const [previews, setPreviews] = useState<{ source_preview?: string; quantized_preview?: string }>({});
  const [raster, setRaster] = useState<RasterChoice>(DEFAULT_RASTER);
  const [config, setConfig] = useState<AppConfig | null>(null);

  useEffect(() => { api.config().then(setConfig).catch(() => setConfig(null)); }, []);

  const load = useCallback(async () => {
    try {
      const d = await api.getProject(id);
      setDetail(d);
      setRegionEdits({}); setPaletteEdits({});
      if (d.design) {
        setWidthText(String(d.design.sizeMm.width)); setHeightText(String(d.design.sizeMm.height));
        setLevel(d.design.detailLevel ?? "standard");
        setLock(d.design.lockAspect); setFabric(d.design.fabricPreset);
        const r = d.design.raster;
        if (r) {
          const opts = r.options;
          setRaster({ colors: opts ? opts.colors ?? null : r.autoColors ? null : r.colors.length,
            bgMode: opts?.removeBackground === false ? "keep" : opts?.backgroundHex ? "manual" : "auto",
            bgHex: opts?.backgroundHex ?? r.backgroundHex ?? "#ffffff",
            backgroundScope: opts?.backgroundScope ?? "edge", detailMode: opts?.detailMode ?? "preserve" });
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
  const width = Number(widthText), height = Number(heightText);
  const savedLevel = design.detailLevel ?? "standard";
  const dirty = width !== design.sizeMm.width || (!lock && height !== design.sizeMm.height)
    || lock !== design.lockAspect || fabric !== design.fabricPreset || level !== savedLevel
    || regionPatches.length > 0 || palettePatches.length > 0;
  const regionValue = <K extends keyof Omit<RegionPatch, "id">>(rid: string, key: K, fallback: NonNullable<RegionPatch[K]>) =>
    (regionEdits[rid]?.[key] ?? fallback) as NonNullable<RegionPatch[K]>;
  const editRegion = (rid: string, patch: Omit<RegionPatch, "id">) =>
    setRegionEdits(prev => ({ ...prev, [rid]: { ...prev[rid], ...patch } }));
  const visibleCount = design.regions.filter(reg => !regionValue(reg.id, "hidden", !!reg.hidden)).length;
  const aspect = design.geometry.viewBox[3] / design.geometry.viewBox[2];
  const shownHeight = lock ? Math.round(width * aspect * 100) / 100 : height;
  // With the aspect locked, typing either side fills in the other one.
  const editSize = (side: "w" | "h", raw: string, forceLock = false) => {
    const text = raw.replace(/[^\d.]/g, "");
    const v = Number(text);
    const other = (x: number) => (text && Number.isFinite(x) && x > 0 ? String(Math.round(x * 100) / 100) : "");
    if (side === "w") { setWidthText(text); if (lock || forceLock) setHeightText(other(v * aspect)); }
    else { setHeightText(text); if (lock) setWidthText(other(v / aspect)); }
  };
  const inRange = (v: number) => Number.isFinite(v) && v >= 5 && v <= 300;
  const sizeOk = inRange(width) && inRange(shownHeight);
  const compiled = project.compiledRevision;
  const stale = compiled !== null && compiled !== project.currentRevision;
  const colors = Object.fromEntries(design.palette.map(c => [c.id, paletteEdits[c.id] ?? c.hex]));
  const regionWarnings = [...new Set(design.regions.flatMap(r => r.warnings))];
  const artifactsFor = (rev: number | null) => detail.artifacts.filter(a => a.revision === rev);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setError(null);
    try { await fn(); } catch (e) { setError(errorMessage(e instanceof ApiError ? e.code : "unknown")); }
    finally { setBusy(null); setProgress(null); }
  };

  // Follow a job: button label plus progress bar.
  const track = (estimateS: number | null = null) => {
    setProgress(nextProgress(null, JOB_STATUS.queued, 0, { estimateS }));
    return (j: Job) => {
      const label = jobLabel(j);
      setBusy(label);
      setProgress(prev => nextProgress(prev, label, j.progress));
    };
  };

  const saveAndCompile = () => run("儲存設定", async () => {
    let revision = project.currentRevision;
    if (dirty) {
      const res = await api.patchDesign(id, { baseRevision: revision, lockAspect: lock, fabricPreset: fabric, detailLevel: level,
        sizeMm: { width, height: lock ? undefined : height },
        regions: regionPatches.length ? regionPatches : undefined, palette: palettePatches.length ? palettePatches : undefined });
      revision = res.revision;
    }
    setBusy("排隊中");
    const onUpdate = track(estimateCompileS(detail.jobs, width, shownHeight, level, savedLevel));
    const job = await waitForJob(await api.compile(id, revision), onUpdate);
    if (job.status === "failed") setError(errorMessage(job.errorCode));
    await load();
  });

  const aiReview = () => run("AI 分析中", async () => {
    const job = await waitForJob(await api.aiPlan(id, project.currentRevision), track());
    if (job.status === "failed") { setError(errorMessage(job.errorCode)); return; }
    await load();
  });

  const reanalyze = () => run("重新分析", async () => {
    if (!design.source?.uploadId) return;
    const job = await waitForJob(await api.analyze(id, design.source.uploadId, { ...toAnalyzeOptions(raster), widthMm: width }),
      track());
    if (job.status === "failed") { setError(errorMessage(job.errorCode)); return; }
    await load();
  });

  const exportZip = () => run("打包中", async () => {
    if (compiled === null) return;
    const job = await waitForJob(await api.exportZip(id, compiled), track());
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
                <input type="text" inputMode="decimal" className="field mt-1" value={widthText}
                  onChange={e => editSize("w", e.target.value)} />
              </label>
              <label className="text-sm">高（mm）
                <input type="text" inputMode="decimal" className="field mt-1" value={heightText}
                  onChange={e => editSize("h", e.target.value)} />
              </label>
            </div>
            {!sizeOk && <p className="text-xs text-bad">寬高需在 5–300 mm 之間。</p>}
            {sizeOk && Math.min(width, shownHeight) < 50 && (
              <p className="text-xs text-warn">小於 50 mm 時細字和細線容易糊掉；需要細節請放大到 60 mm 以上。</p>
            )}
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={lock} onChange={e => { setLock(e.target.checked); if (e.target.checked) editSize("w", widthText, true); }} />鎖定比例</label>
            {lock && <p className="text-xs text-muted">填寬或高其中一個，另一個依圖形比例自動計算。</p>}
            <label className="block text-sm">布料
              <select className="field mt-1" value={fabric} onChange={e => setFabric(e.target.value as FabricPreset)}>
                {FABRICS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
              </select>
            </label>
            {fabric !== design.fabricPreset && <p className="text-xs text-muted">更換布料會把所有區域參數重設為「{fabricLabel(fabric)}」預設值。</p>}
            <label className="block text-sm">針跡精細度
              <select className="field mt-1" value={level} onChange={e => setLevel(e.target.value as DetailLevel)}>
                {DETAIL_LEVELS.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
              </select>
            </label>
            <p className="text-xs text-muted">{DETAIL_LEVELS.find(d => d.id === level)?.hint}</p>
            <button className="btn btn-primary w-full justify-center" disabled={!!busy || !sizeOk} onClick={saveAndCompile}>
              {busy ?? (dirty ? "儲存並編譯" : stale || compiled === null ? "編譯" : "重新編譯")}
            </button>
            {progress && <JobProgress p={progress} />}
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

          <div className="card space-y-2 p-4">
            <h2 className="font-medium">AI 針法建議</h2>
            {config?.aiEnabled ? (
              <>
                <p className="text-xs text-muted">
                  會把區域的重繪預覽圖（不是原始檔）和幾何數據送到 Anthropic 的 Claude 分析。AI 只提出建議，最後由規則檢查並產生新版本。
                </p>
                <button className="btn w-full justify-center" disabled={!!busy || dirty} onClick={aiReview}>
                  {design.aiReview ? "重新請 AI 建議" : "請 AI 建議針法"}
                </button>
                {dirty && <p className="text-xs text-warn">請先儲存目前的修改。</p>}
              </>
            ) : (
              <p className="text-xs text-muted">伺服器未設定 AI（ANTHROPIC_API_KEY），目前由規則依幾何判斷針法。</p>
            )}
            {design.aiReview && (
              <div className="space-y-1 text-sm">
                <p>{design.aiReview.summary}</p>
                {design.aiReview.risks.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-5 text-xs text-warn">
                    {design.aiReview.risks.map((risk, i) => <li key={i}>{risk.message}</li>)}
                  </ul>
                )}
                <p className="text-xs text-muted">模型：{design.aiReview.model}（依 revision {design.aiReview.basedOnRevision}）</p>
              </div>
            )}
          </div>

          {design.raster && (
            <div className="card space-y-3 p-4">
              <h2 className="font-medium">圖片轉向量</h2>
              {(design.raster.analysisVersion ?? 1) < 2 && <p className="text-xs text-warn">
                此設計使用舊版圖片分析。選擇「保留細節」並重新分析，才能套用新的輪廓處理。
              </p>}
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
            <h2 className="font-medium">區域（{visibleCount}/{design.regions.length} 繡製，依縫製順序）</h2>
            {design.planner?.colorChangesBefore !== undefined && design.planner.colorChangesAfter !== undefined
              && design.planner.colorChangesAfter < design.planner.colorChangesBefore && (
              <p className="text-xs text-muted">已自動調整順序：換色 {design.planner.colorChangesBefore} → {design.planner.colorChangesAfter} 次（不改變圖形重疊關係）。</p>
            )}
            <RegionMap design={design} colors={colors} selected={selected}
              hidden={rid => regionValue(rid, "hidden", !!design.regions.find(x => x.id === rid)?.hidden)}
              onSelect={rid => {
                setSelected(cur => cur === rid ? null : rid);
                document.getElementById(`region-row-${rid}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
              }} />
            <p className="text-xs text-muted">點圖上的形狀或下方的列表，會標出是哪個區域。</p>
            <ul className="max-h-96 space-y-1 overflow-auto text-sm">
              {design.regions.map((reg, index) => {
                const hidden = regionValue(reg.id, "hidden", !!reg.hidden);
                const colorId = regionValue(reg.id, "colorId", reg.colorId);
                const allowedFor = detail.allowedStitches[reg.id];
                const plan = reg.plan;
                return (
                  <li key={reg.id} id={`region-row-${reg.id}`}
                    className={`rounded-md p-1 ${hidden ? "opacity-50" : ""} ${selected === reg.id ? "bg-fabric ring-1 ring-bad" : ""}`}
                    onClick={e => { if (!(e.target as HTMLElement).closest("input,select")) setSelected(cur => cur === reg.id ? null : reg.id); }}>
                    <div className="flex items-center gap-2">
                      <input type="checkbox" checked={!hidden} aria-label={`繡製 ${reg.name}`}
                        disabled={!hidden && visibleCount <= 1}
                        onChange={e => editRegion(reg.id, { hidden: !e.target.checked })} />
                      <RegionThumb design={design} regionId={reg.id} />
                      <span className="inline-block h-3.5 w-3.5 shrink-0 rounded-sm border border-line" style={{ background: colors[colorId] }} />
                      <span className="min-w-0 flex-1 truncate" title={reg.id}>{index + 1}. {reg.name}</span>
                      {plan?.needsReview && <span className="rounded bg-warn px-1 text-xs text-accent-ink" title="需要人工確認">需確認</span>}
                      {design.palette.length > 1 && (
                        <select className="field w-auto px-1 py-0.5 text-xs" value={colorId} aria-label={`${reg.name} 線色`}
                          onChange={e => editRegion(reg.id, { colorId: e.target.value })}>
                          {design.palette.map((c, i) => <option key={c.id} value={c.id}>色 {i + 1}</option>)}
                        </select>
                      )}
                      <select className="field w-auto px-1 py-0.5 text-xs" value={regionValue(reg.id, "stitchType", reg.stitchType)}
                        aria-label={`${reg.name} 針法`} onChange={e => editRegion(reg.id, { stitchType: e.target.value as StitchType })}>
                        {(["fill", "running", "satin"] as const).map(st => {
                          const blocked = allowedFor?.[st];
                          return (blocked && st !== reg.stitchType) ? null : (
                            <option key={st} value={st} title={blocked ? errorMessage(blocked) : undefined}>{STITCH_LABEL[st]}</option>
                          );
                        })}
                      </select>
                    </div>
                    {plan && (
                      <p className="ml-[4.25rem] mt-0.5 text-xs text-muted">
                        {plan.manual ? "手動設定" : plan.source === "ai" ? `AI：${plan.aiReason || STITCH_LABEL[plan.suggested]}` : planReason(plan.reason)}
                        {plan.override && <span className="text-warn">（規則否決 AI 的{STITCH_LABEL[plan.suggested]}：{errorMessage(plan.override)}）</span>}
                        {reg.runningPath === "centerline" && reg.stitchType === "running" && "・沿中心線"}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
            <p className="text-xs text-muted">平針：細線沿中心線，其他沿外框一圈。緞面：只適用寬 1–7 mm、寬度均勻的線條。取消勾選＝不繡這個區域。</p>
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
