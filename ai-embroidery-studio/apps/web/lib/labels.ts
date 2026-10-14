export const FABRICS = [
  { id: "woven_cotton", label: "平織棉" },
  { id: "knit_cotton", label: "針織棉" },
  { id: "canvas", label: "帆布" },
  { id: "other", label: "其他" },
] as const;

export const fabricLabel = (id: string) => FABRICS.find(f => f.id === id)?.label ?? id;

export const PROJECT_STATUS: Record<string, string> = { draft: "草稿", awaiting_test_sew: "待試繡", accepted: "已驗收" };

export const JOB_STATUS: Record<string, string> = {
  queued: "排隊中", preprocessing: "檢查檔案", planning: "分析圖形", compiling: "Ink/Stitch 編譯中",
  validating: "驗證針跡", exporting: "打包中", ready: "完成", failed: "失敗",
};

const MESSAGES: Record<string, string> = {
  not_authenticated: "請先輸入使用者名稱登入。",
  unsupported_file_type: "目前只支援 SVG 檔（PNG/JPG 將在下一階段支援）。",
  file_too_large: "檔案超過 8 MB 上限。",
  missing_viewbox: "SVG 缺少 viewBox，無法判斷比例。請在設計軟體中重新匯出。",
  invalid_viewbox: "SVG 的 viewBox 數值異常。",
  invalid_svg: "無法解析這個 SVG 檔。",
  doctype_not_allowed: "SVG 含有 DOCTYPE/ENTITY 宣告，基於安全理由拒絕。",
  no_embroiderable_shapes: "SVG 裡找不到可刺繡的填色或線條（文字請先轉外框）。",
  too_complex: "圖形太複雜（物件或節點過多），請先簡化。",
  too_many_colors: "顏色超過 12 色，請先減少色數。",
  degenerate_geometry: "圖形寬或高為零。",
  revision_conflict: "設計已在別處更新，請重新整理頁面。",
  too_many_active_jobs: "同時進行的工作太多，請稍候再試。",
  engine_failed: "Ink/Stitch 編譯失敗。",
  engine_timeout: "編譯逾時，圖形可能太複雜。",
  validation_failed: "輸出檔驗證未通過（尺寸或針數異常）。",
  not_compiled: "請先完成編譯。",
  queue_unavailable: "背景工作服務未啟動（Redis / worker）。",
  height_out_of_range: "依比例換算後的高度超出 5–300 mm。",
  invalid_input: "輸入值不正確（尺寸需在 5–300 mm）。",
  job_timeout: "等待逾時，請重新整理查看狀態。",
};

export const errorMessage = (code: string | null | undefined) =>
  (code && MESSAGES[code]) ?? `發生錯誤（${code ?? "unknown"}）`;

const WARNINGS: Record<string, string> = {
  factory_test_required: "需以相同布料與襯紙試繡",
  unsafe_content_removed: "已移除不安全內容（script／事件／外部連結等）",
  text_not_supported_convert_to_outlines: "文字已略過，請在設計軟體中轉成外框",
  gradient_or_pattern_replaced: "漸層／圖樣填色已改為單色",
  css_ignored: "<style> 樣式表已忽略，只讀取行內樣式",
  narrow_fill_under_1mm: "有填針區域窄於 1 mm",
  tiny_region: "有極小區域（< 0.5 mm）",
  many_colors: "超過 6 色，建議減少",
  many_jumps: "跳針偏多",
  color_blocks_differ_from_design: "換色段數與設計不同",
};
export const warningLabel = (w: string) =>
  WARNINGS[w] ?? (w.startsWith("unsupported_element_removed:") ? `已移除不支援的元素 <${w.split(":")[1]}>` : w);
