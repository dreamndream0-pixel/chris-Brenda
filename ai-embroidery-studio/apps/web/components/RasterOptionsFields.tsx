"use client";
import type { AnalyzeOptions, ContourDetail } from "@/lib/api";

export type BgMode = "auto" | "manual" | "keep";
export interface RasterChoice { colors: number | null; bgMode: BgMode; bgHex: string;
  backgroundScope: "edge" | "all"; detailMode: ContourDetail }
export const DEFAULT_RASTER: RasterChoice = { colors: null, bgMode: "auto", bgHex: "#ffffff",
  backgroundScope: "edge", detailMode: "preserve" };

export const toAnalyzeOptions = (c: RasterChoice): AnalyzeOptions => ({
  colors: c.colors,
  removeBackground: c.bgMode !== "keep",
  backgroundHex: c.bgMode === "manual" ? c.bgHex : null,
  backgroundScope: c.backgroundScope,
  detailMode: c.detailMode,
});

export default function RasterOptionsFields({ value, onChange }: { value: RasterChoice; onChange: (v: RasterChoice) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm">色數
        <select className="field mt-1" value={value.colors ?? "auto"}
          onChange={e => onChange({ ...value, colors: e.target.value === "auto" ? null : +e.target.value })}>
          <option value="auto">自動判斷（1–6 色）</option>
          {[1, 2, 3, 4, 5, 6].map(n => <option key={n} value={n}>{n} 色</option>)}
        </select>
      </label>
      <label className="text-sm">輪廓與細節
        <select className="field mt-1" value={value.detailMode}
          onChange={e => onChange({ ...value, detailMode: e.target.value as ContourDetail })}>
          <option value="preserve">保留細節（小字、五官、Logo）</option>
          <option value="balanced">平衡（一般圖案）</option>
          <option value="clean">加強去雜點（有雜訊的圖片）</option>
        </select>
      </label>
      {value.bgMode !== "keep" && <label className="text-sm">去背範圍
        <select className="field mt-1" value={value.backgroundScope}
          onChange={e => onChange({ ...value, backgroundScope: e.target.value as "edge" | "all" })}>
          <option value="edge">只移除外側背景（保留內部同色細節）</option>
          <option value="all">移除所有同色區域（含字母內部空洞）</option>
        </select>
      </label>}
      <label className="text-sm">背景
        <select className="field mt-1" value={value.bgMode} onChange={e => onChange({ ...value, bgMode: e.target.value as BgMode })}>
          <option value="auto">自動去背（偵測邊緣顏色）</option>
          <option value="manual">指定背景色</option>
          <option value="keep">保留背景（一起繡）</option>
        </select>
      </label>
      {value.bgMode === "manual" && (
        <label className="flex items-center gap-2 text-sm sm:col-span-2">背景色
          <input type="color" value={value.bgHex} onChange={e => onChange({ ...value, bgHex: e.target.value })}
            className="h-8 w-12 cursor-pointer rounded border border-line" aria-label="背景色" />
          <code className="text-muted">{value.bgHex}</code>
        </label>
      )}
      <p className="text-xs text-muted sm:col-span-2">透明 PNG 直接使用透明區域。保留細節會減少小圖形的清除與輪廓簡化，不會提高針跡密度；極小細節仍可能需要放大尺寸才能繡清楚。</p>
    </div>
  );
}
