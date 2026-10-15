export const FABRICS = [
  { id: "woven_cotton", label: "平織棉" },
  { id: "knit_cotton", label: "針織棉" },
  { id: "canvas", label: "帆布" },
  { id: "other", label: "其他" },
] as const;

export const DETAIL_LEVELS = [
  { id: "standard", label: "標準", hint: "一般用途，針數最少、最快。" },
  { id: "fine", label: "精細", hint: "行距較密、針距較短，小字和曲線更清楚。" },
  { id: "ultra", label: "極精細", hint: "最密最細，針數多約 1/3；薄布或彈性布容易起皺，建議先試繡。" },
] as const;

export const fabricLabel = (id: string) => FABRICS.find(f => f.id === id)?.label ?? id;

export const PROJECT_STATUS: Record<string, string> = { draft: "草稿", awaiting_test_sew: "待試繡", accepted: "已驗收" };

export const JOB_STATUS: Record<string, string> = {
  queued: "排隊中", preprocessing: "檢查檔案", planning: "分析圖形", compiling: "Ink/Stitch 編譯中",
  validating: "驗證針跡", exporting: "打包中", ready: "完成", failed: "失敗",
};

const MESSAGES: Record<string, string> = {
  not_authenticated: "請先輸入使用者名稱登入。",
  unsupported_file_type: "只支援 SVG、PNG、JPG 檔。",
  invalid_image: "無法讀取這張圖片，檔案可能已損毀。",
  image_too_large: "圖片超過 4096 × 4096 像素。",
  image_too_small: "圖片太小（至少 16 像素）。",
  no_foreground: "去背後沒有剩下圖形；請改用「保留背景」或指定背景色。",
  invalid_background_color: "背景色格式不正確。",
  invalid_color_count: "色數需在 1–6 之間。",
  unknown_region: "找不到這個區域，請重新整理。",
  unknown_color: "找不到這個顏色，請重新整理。",
  all_regions_hidden: "至少要保留一個可見區域。",
  upload_not_ready: "原始檔不存在或尚未上傳完成。",
  ai_not_configured: "伺服器尚未設定 AI（ANTHROPIC_API_KEY）。",
  ai_refused: "AI 拒絕分析這個設計，請改用規則結果或手動調整。",
  ai_truncated: "AI 回覆不完整，請再試一次。",
  ai_bad_output: "AI 回覆格式錯誤，請再試一次。",
  ai_rate_limited: "AI 服務忙碌中，請稍後再試。",
  ai_auth_failed: "AI 金鑰無效或沒有權限。",
  ai_unavailable: "暫時連不上 AI 服務。",
  ai_request_failed: "AI 請求失敗。",
  too_many_regions: "區域太多（超過 400 個），AI 無法分析。",
  satin_needs_uniform_stroke: "緞面只適用於寬度均勻的線條狀區域。",
  satin_too_narrow: "以目前尺寸，這條線窄於 1 mm，無法做緞面。",
  satin_too_wide: "以目前尺寸，這條線寬於 7 mm，緞面會太鬆。",
  fill_needs_area: "這是線條（SVG 描邊），不能做填針。",
  missing_centerline: "這個區域沒有可用的中心線。",
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
  small_details_removed: "部分細小雜點已清除（小於 0.8 mm）",
  thin_features_under_1mm: "有寬度小於 1 mm 的細線，刺繡可能不清楚",
  satin_too_narrow: "緞面線條窄於 1 mm",
  satin_too_wide: "緞面線條寬於 7 mm，針腳會太長",
  satin_needs_uniform_stroke: "緞面區域寬度不均",
  thin_fill_use_running: "細線用填針效果差，建議改平針",
};
export const warningLabel = (w: string) =>
  WARNINGS[w] ?? (w.startsWith("unsupported_element_removed:") ? `已移除不支援的元素 <${w.split(":")[1]}>` : w);

export const STITCH_LABEL: Record<string, string> = { fill: "填針", running: "平針", satin: "緞面" };

const PLAN_REASONS: Record<string, string> = {
  thin_line_centerline: "細線 → 中心線平針",
  uniform_stroke: "寬度均勻的線條 → 緞面",
  area_fill: "面積 → 填針",
  wide_stroke: "粗描邊 → 緞面",
  stroke_line: "描邊 → 平針",
};
export const planReason = (code: string) => PLAN_REASONS[code] ?? code;
