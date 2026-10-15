"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import JobProgress, { nextProgress, type Progress } from "@/components/JobProgress";
import RasterOptionsFields, { DEFAULT_RASTER, toAnalyzeOptions, type RasterChoice } from "@/components/RasterOptionsFields";
import { ACCEPTED, api, ApiError, isRaster, SIZE_MAX_MM, SIZE_MIN_MM, sizeInRange, withRetry, type FabricPreset } from "@/lib/api";
import { errorMessage, FABRICS, JOB_STATUS } from "@/lib/labels";

const MAX_BYTES = 8 * 1024 * 1024;

export default function NewProjectPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  // Text, not numbers: a cleared number field would otherwise snap to "0" and typing gives "08".
  const [widthText, setWidthText] = useState("50");
  const [heightText, setHeightText] = useState("30");
  const width = Number(widthText), height = Number(heightText);
  // With the aspect locked only one side can be given; the other follows the artwork after analysis.
  const [sizeBy, setSizeBy] = useState<"width" | "height">("width");
  const [progress, setProgress] = useState<Progress | null>(null);
  const [lock, setLock] = useState(true);
  const [fabric, setFabric] = useState<FabricPreset>("woven_cotton");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [raster, setRaster] = useState<RasterChoice>(DEFAULT_RASTER);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const busy = status !== null && !error;
  const rasterFile = file !== null && isRaster(file);

  // Local preview for PNG/JPG only; SVG is never put into the page (it may contain scripts).
  useEffect(() => {
    if (!file || !isRaster(file)) { setPreviewUrl(null); return; }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const pick = (f: File | undefined) => {
    setError(null);
    if (!f) return;
    if (!Object.keys(ACCEPTED).some(ext => f.name.toLowerCase().endsWith(ext))) { setError(errorMessage("unsupported_file_type")); return; }
    if (f.size > MAX_BYTES) { setError(errorMessage("file_too_large")); return; }
    setFile(f);
    if (!name) setName(f.name.replace(/\.(svg|png|jpe?g)$/i, ""));
  };

  const step = (label: string, percent: number, hint: string | null = null) => {
    setStatus(label);
    setProgress(prev => nextProgress(prev, label, percent, { hint }));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const ok = sizeInRange;
    const byHeight = lock && sizeBy === "height";
    if (lock ? !ok(byHeight ? height : width) : !(ok(width) && ok(height))) { setError(`寬高需在 ${SIZE_MIN_MM}–${SIZE_MAX_MM} mm 之間。`); return; }
    setError(null);
    setProgress(null);
    try {
      // Free hosting sleeps when idle; the first request can wait about a minute for it to wake up.
      step("連線伺服器、建立專案", 2, "伺服器閒置後第一次使用需要喚醒，可能多等約 1 分鐘。");
      const project = await api.createProject({ name: name.trim() || file.name, widthMm: byHeight ? height : width,
        heightMm: lock ? undefined : height, lockAspect: lock, fabricPreset: fabric });
      step("上傳檔案", 6);
      const up = await api.uploadUrl(project.id, file);
      await withRetry(() => api.putUpload(up.uploadUrl, file, up.headers));
      const opts = { ...(rasterFile ? toAnalyzeOptions(raster) : {}), ...(byHeight ? { fitHeightMm: height } : {}) };
      step(JOB_STATUS.queued, 9);
      await api.analyze(project.id, up.uploadId, opts);
      // The analysis runs on the server; the project page follows it (and picks it up again
      // if the phone locks or the browser drops this page in the background).
      router.push(`/studio/${project.id}`);
    } catch (err) {
      setError(errorMessage(err instanceof ApiError ? err.code : "upload_failed"));
    }
  };

  return (
    <form onSubmit={submit} className="mx-auto max-w-2xl space-y-5">
      <h1 className="text-2xl font-semibold">新增專案</h1>

      <label
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files[0]); }}
        className={`card flex cursor-pointer flex-col items-center justify-center gap-2 border-2 border-dashed p-10 text-center ${dragging ? "border-accent" : ""}`}>
        <input type="file" accept=".svg,.png,.jpg,.jpeg,image/svg+xml,image/png,image/jpeg" className="sr-only" onChange={e => pick(e.target.files?.[0])} />
        {previewUrl && <img src={previewUrl} alt="上傳圖片預覽" className="max-h-48 rounded border border-line object-contain" />}
        <span className="text-lg">{file ? file.name : "拖放 SVG、PNG 或 JPG 到這裡，或點擊選擇"}</span>
        <span className="text-sm text-muted">{file ? `${(file.size / 1024).toFixed(1)} KB` : "上限 8 MB；SVG 需含 viewBox；圖片最大 4096 × 4096 像素。"}</span>
      </label>

      {rasterFile && (
        <div className="card space-y-2 p-5">
          <h2 className="font-medium">圖片轉向量</h2>
          <RasterOptionsFields value={raster} onChange={setRaster} />
        </div>
      )}

      <div className="card space-y-4 p-5">
        <label className="block text-sm">專案名稱
          <input className="field mt-1" value={name} onChange={e => setName(e.target.value)} maxLength={120} required />
        </label>
        <fieldset className="grid grid-cols-2 gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <legend className="mb-1 text-sm">最終刺繡尺寸</legend>
          <label className="text-sm">寬（mm）
            <input type="text" inputMode="decimal" className="field mt-1"
              value={lock && sizeBy === "height" ? "" : widthText} placeholder={lock && sizeBy === "height" ? "依比例" : ""}
              onChange={e => { setWidthText(e.target.value.replace(/[^\d.]/g, "")); setSizeBy("width"); }} />
          </label>
          <label className="text-sm">高（mm）
            <input type="text" inputMode="decimal" className="field mt-1"
              value={lock && sizeBy === "width" ? "" : heightText} placeholder={lock && sizeBy === "width" ? "依比例" : ""}
              onChange={e => { setHeightText(e.target.value.replace(/[^\d.]/g, "")); setSizeBy("height"); }} />
          </label>
          <label className="col-span-2 flex items-center gap-2 text-sm sm:col-span-1 sm:pb-2">
            <input type="checkbox" checked={lock} onChange={e => setLock(e.target.checked)} />鎖定比例
          </label>
        </fieldset>
        {lock && <p className="text-xs text-muted">鎖定比例時填寬或高其中一個，另一個依圖形比例自動計算。</p>}
        <label className="block text-sm">主要布料
          <select className="field mt-1" value={fabric} onChange={e => setFabric(e.target.value as FabricPreset)}>
            {FABRICS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </label>
      </div>

      {error && <p className="card border-bad p-3 text-bad" role="alert">{error}</p>}
      <div className="space-y-3">
        <button className="btn btn-primary" type="submit" disabled={!file || busy}>{busy ? "處理中…" : "開始分析"}</button>
        {busy && progress && <div className="card p-4"><JobProgress p={progress} /></div>}
      </div>
    </form>
  );
}
