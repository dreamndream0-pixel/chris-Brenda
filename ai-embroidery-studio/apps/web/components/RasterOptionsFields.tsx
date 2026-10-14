"use client";
import type { AnalyzeOptions } from "@/lib/api";

export type BgMode = "auto" | "manual" | "keep";
export interface RasterChoice { colors: number | null; bgMode: BgMode; bgHex: string }
export const DEFAULT_RASTER: RasterChoice = { colors: null, bgMode: "auto", bgHex: "#ffffff" };

export const toAnalyzeOptions = (c: RasterChoice): AnalyzeOptions => ({
  colors: c.colors,
  removeBackground: c.bgMode !== "keep",
  backgroundHex: c.bgMode === "manual" ? c.bgHex : null,
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
      <p className="text-xs text-muted sm:col-span-2">透明背景的 PNG 會直接使用透明區域，不需要去背設定。</p>
    </div>
  );
}
