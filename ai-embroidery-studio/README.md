# AI Embroidery Studio

依《MVP 技術規劃書》分階段開發。目前完成：

- **Gate A — 核心可編譯能力**：固定 SVG → Ink/Stitch CLI → DST/PES → pyembroidery 重讀驗證 → 針跡預覽。
- **Gate B — 完整使用流程**：網頁上傳 SVG → 建立專案 → 設定尺寸與布料 → 編譯 → 預覽 → 匯出工廠交件包 → 下載；含權限與檔案限制。
- **Gate C — 圖片轉向量**：PNG/JPG → 去背 → Lab 分色 → 清除雜點 → VTracer → 區域 JSON → 填針／平針；結果不理想時可重新分析（色數、背景）或逐區改針法、改色、不繡。

## Gate C：圖片轉向量

| 步驟 | 做法（`services/worker/raster_import.py`） |
|---|---|
| 安全讀檔 | 檢查檔頭（PNG/JPEG）且需與副檔名、宣告類型一致；≤ 8 MB、≤ 4096 × 4096 px；套用 EXIF 方向後丟棄所有 metadata；預覽圖一律重新編碼 |
| 去背 | 有透明度的 PNG 直接用 alpha；否則取影像邊緣中位色為背景（或使用者指定色），Lab 距離 ΔE > 12 視為圖形；也可選「保留背景」 |
| 分色 | Lab 色彩空間 k-means；自動模式取「95 百分位誤差 ΔE < 10」的最小色數（1–6），避免小面積細節（如臉頰）被平均掉；也可指定色數 |
| 清理 | 中值濾波去鋸齒雜色；小於 0.8 × 0.8 mm（依目標尺寸換算）的碎塊併入周圍顏色 |
| 向量化 | 每個顏色一張互不重疊的遮罩，分別用 VTracer 描邊（不重疊＝不會重複繡）；面積大的顏色先繡、細節後繡 |
| 接上既有流程 | 產生的 SVG 走與上傳 SVG 相同的清理與匯入（Design JSON），所以後續編譯、驗證、匯出完全共用 |

**手動修正（失敗時的退路）**：專案頁可「以這些設定重新分析」（換色數／背景，產生新版本），或逐區改針法（填針／平針）、改線色、取消不繡；修改送出時一樣走 `baseRevision` 樂觀鎖。

**驗證**（真實 Ink/Stitch）：

| 測試圖 | 自動色數 | 區域 | 針數 | 尺寸 |
|---|---|---|---|---|
| `fixtures/raster/wordmark_chue.png`（單色字樣，含 É 的重音符號） | 1 | 5 | 2122 | 80.4 × 26.0 mm |
| `fixtures/raster/two_color_transparent.png`（透明背景兩色） | 2 | 2 | 2773 | 70.4 × 41.2 mm |
| `fixtures/raster/mascot.jpg`（JPEG 壓縮雜訊、少色吉祥物） | 3 | 7 | 7334 | 70.4 × 74.8 mm |

測試圖由 `tools/make_raster_fixtures.py` 產生。測試：53 個（含 3 個真實 Ink/Stitch 圖片編譯，約 2 分 40 秒）。

**已知限制**：
- **編譯時間**：吉祥物約 100 秒（SVG 徽章約 35 秒）。剖析結果：主要花在 Ink/Stitch tatami 填針繞開孔洞（眼睛、臉頰）的移動路徑計算，另約兩成是每次重新讀取 150 個線色色票（Ink/Stitch 本身每個色票讀兩次）。目前引擎逾時 180 秒，更複雜的圖可能逾時；之後可考慮修補 Ink/Stitch 色票載入或保留每個專案的 Ink/Stitch 快取。
- 細線（< 1 mm）只會發出警告，仍以填針處理；自動轉成中心線平針需要骨架化，留待 Gate D。
- 區域改成平針時是「沿外框一圈」，內部會露出布料（顏色區域互不重疊）。
- 漸層與照片式圖片不在 MVP 範圍；分色會把漸層切成色塊。

## Gate B：本機啟動

需要：Python 3.12 + Ink/Stitch（見下方 Gate A）、Redis、Node 22。

```bash
# 1) 後端套件（裝在 Ink/Stitch 的 venv 裡，worker 才能呼叫它）
/opt/venv/bin/pip install -r services/requirements.txt

# 2) 共用環境變數
export EMB_DATA_DIR=$PWD/data EMB_REDIS_URL=redis://localhost:6379/0 EMB_AUTH_MODE=dev \
       EMB_SIGNING_SECRET=change-me EMB_PUBLIC_API_URL=http://localhost:8000 EMB_CORS_ORIGINS=http://localhost:3000

# 3) 三個程序（各開一個終端機）
redis-server
INKSTITCH_CMD="xvfb-run -a /opt/venv/bin/python /opt/inkstitch/inkstitch.py" /opt/venv/bin/rq worker emb --url $EMB_REDIS_URL
/opt/venv/bin/uvicorn services.api.main:app --port 8000

# 4) 前端
cd apps/web && npm install && npm run dev     # http://localhost:3000/studio
```

或用 Docker：`docker compose -f infra/docker-compose.yml up --build`（Redis + API + worker），前端另外 `npm run dev`。

### Gate B 架構

| 路徑 | 說明 |
|---|---|
| `apps/web/` | Next.js 16 + TypeScript + Tailwind：`/studio` 專案列表、`/studio/new` 上傳與尺寸/布料、`/studio/[id]` 設定、編譯、針跡播放、匯出下載（手機可用） |
| `services/api/` | FastAPI：§9 的 REST API（projects、upload-url、analyze、design PATCH 樂觀鎖、compile、stitches、exports、jobs、短效下載連結） |
| `services/core/` | 設定、資料表（SQLAlchemy；本機 SQLite，正式 Postgres）、私有儲存、HMAC 簽名 URL、RQ 佇列 |
| `services/worker/svg_import.py` | SVG 安全清理（元素/屬性白名單、拒絕 DOCTYPE/ENTITY、移除 script/事件/外部連結/圖片/foreignObject/use/CSS/url()）→ 攤平 transform → Design JSON |
| `services/worker/svg_compile.py` | Design JSON → Ink/Stitch SVG（只輸出白名單且 clamp 過的參數，path 由 svgelements 重新序列化） |
| `services/worker/fabrics.py` | 布料預設（平織棉／針織棉／帆布／其他）與參數上下限 |
| `services/worker/tasks.py` | RQ 背景工作：analyze → compile（含驗證）→ export（ZIP：DST、PES、Ink/Stitch SVG、threadlist、規格表 txt/json） |
| `infra/supabase/migrations/` | Postgres schema + RLS + 私有 bucket |

### Gate B 安全與限制

- 每個查詢都以 `user_id` 過濾；別人的專案、工作、下載一律回 404（不洩漏是否存在）。
- 上傳：只收 SVG、≤ 8 MB（宣告與實際都檢查）、≤ 5000 元素、≤ 2000 圖形、≤ 50000 路徑段、≤ 12 色、必須有 viewBox。
- 上傳與下載都用 HMAC 簽名的短效 token（上傳 10 分鐘、下載 5 分鐘），下載回應帶 `Content-Disposition: attachment`、`nosniff`、`CSP: sandbox`。
- 每位使用者同時最多 3 個進行中的工作（超過回 429）。
- 設計修改需帶 `baseRevision`，過期回 409；舊 revision 的編譯不會覆蓋新 revision 的結果。
- **登入目前是開發模式**（`X-Dev-User` 標頭，任何人輸入名稱即可）。API 已支援 Supabase JWT（`EMB_AUTH_MODE=supabase`），但前端尚未接 Supabase Auth，**不可對外公開部署**。
- **檔案儲存目前只有本機檔案系統版本**；Supabase Storage 版本（同一套 key 結構與簽名 URL）尚未實作。
- 區域照 SVG 文件順序縫製，尚未自動重排以減少換色（例：徽章「深藍→紅→深藍」會換色 2 次）；屬 Gate D/E。
- 渲染 Ink/Stitch 的子程序只拿到最小環境變數，但與 worker 共用網路；Docker 版把 worker 放在無對外網路的 internal network。

### Gate B 驗證

- 當時 35 個測試全部通過：API 完整流程、跨使用者存取、簽名連結竄改/過期、上傳限制、惡意 SVG（XXE、script、缺 viewBox）、revision 衝突、舊編譯不覆蓋、工作數上限、引擎失敗、Supabase JWT。
- 端對端（真實 Redis + RQ worker + Ink/Stitch + 瀏覽器）：上傳 `fixtures/uploads/two_color_badge.svg` → 70 mm 編譯（約 35 秒）→ 改 90 mm、針織棉 → 重新編譯 → 匯出 ZIP → 下載；實際針跡 90.0 × 90.0 mm、3549 針、3 色段。手機寬度無橫向捲動。

## Gate A（核心可編譯能力）

## 內容

| 路徑 | 說明 |
|---|---|
| `fixtures/fixture_*.svg` | 四個固定測試圖：圓形填針、平針框、兩色區塊、均勻寬度緞面柱（帶 `inkstitch:*` 參數，單位 mm） |
| `fixtures/expected.json` | 每張圖的期望寬高（mm）、容差、線色區段數 |
| `services/worker/engine.py` | Ink/Stitch CLI 執行器：`shell=False`、逾時、獨立暫存目錄、最小環境變數（不帶入金鑰）、ZIP 僅取白名單副檔名並防 path traversal、穩定錯誤碼 |
| `services/worker/validate.py` | 重讀 DST/PES：針數、跳針、剪線、換色、色段、實際尺寸，與期望值比對；DST vs PES 交叉檢查 |
| `services/worker/preview.py` | 從**匯出的 DST** 解碼針跡序列 `[x_mm, y_mm, cmd, colorIndex]`（不從 SVG 另行模擬） |
| `services/worker/gate_a.py` | 一鍵跑完所有 fixture，輸出 `report.json` 與 `preview.html` |
| `tools/stitch_viewer.html` | Canvas 針跡播放器：播放/暫停、0.25–4x、時間線、針點、跳針、色段 |
| `infra/worker/Dockerfile` | 固定版本 worker 映像：Ubuntu 24.04 + Ink/Stitch **v3.3.0**（commit `b0edd963…`，建置時驗證）+ 固定版本 PyPI 依賴 |
| `infra/docker-compose.yml` | 以 `network_mode: none`、唯讀根目錄、CPU/記憶體上限執行 Gate A |
| `tests/` | 單元測試（以假引擎測 subprocess 流程）＋ 真實 Ink/Stitch 整合測試（需 `INKSTITCH_CMD`） |

## 執行

```bash
# 單元測試（不需 Ink/Stitch）
python3 -m venv .venv && .venv/bin/pip install -r services/worker/requirements.txt
.venv/bin/python -m pytest -q tests

# 指定已安裝的 Ink/Stitch 跑真實編譯（範例）
INKSTITCH_CMD="xvfb-run -a /opt/venv/bin/python /opt/inkstitch/inkstitch.py" python -m services.worker.gate_a

# 完整 Gate A（在 worker 映像內，含真實 Ink/Stitch）
docker build -f infra/worker/Dockerfile -t emb-worker:gate-a .
mkdir -p out && chmod 777 out
docker run --rm --network=none --cpus=2 --memory=2g -v "$PWD/out:/out" emb-worker:gate-a \
  python -m services.worker.gate_a --fixtures fixtures --out /out/gate-a
# 然後用瀏覽器開 out/gate-a/preview.html
```

Gate A 通過條件：四張 fixture 全部 `PASS`，即 DST/PES 皆可重讀、針數 > 0、尺寸在容差內、色段數正確、預覽播放的針數與 DST 解碼一致。

## 目前狀態：Gate A 通過（2026-10-14）

真實 Ink/Stitch v3.3.0 編譯結果（DST 重讀，PES 交叉檢查一致）：

| Fixture | 針數 | 尺寸（mm） | 色段 | 跳針 | 結果 |
|---|---|---|---|---|---|
| `fixture_circle_fill.svg` | 1183 | 30.4 × 30.2 | 1 | 2 | PASS |
| `fixture_logo_running.svg` | 53 | 30.0 × 10.0 | 1 | 2 | PASS |
| `fixture_satin_stroke.svg` | 271 | 40.0 × 4.0 | 1 | 2 | PASS |
| `fixture_two_color.svg` | 972 | 40.0 × 20.0 | 2 | 2 | PASS |

測試：19 passed（含真實 Ink/Stitch 整合測試，約 50 秒）。技術驗證通過 ≠ 生產品質，仍需工廠同布料試繡（Gate F）。

## 已知事項（開發時必看）

- **SVG 必須帶 `<inkstitch:inkstitch_svg_version>4</…>` metadata。** 缺少時 Ink/Stitch 會跳出「是否更新文件」對話框，在無畫面的伺服器上會**無限卡住**。`engine.py` 會在編譯前檢查並以 `unsupported_svg_version` 拒絕；之後的 `svg_compile.py`（Design JSON → SVG）一定要寫入這個標記。
- **wxPython 需要 X display**（即使只跑 CLI），所以 `INKSTITCH_CMD` 用 `xvfb-run -a` 包住，每個 job 一個臨時虛擬螢幕。
- **逾時會整個 process group 一起砍掉**，避免 `xvfb-run` 被殺後 Ink/Stitch / Xvfb 變成孤兒程序。
- **PES 會把線色吸附到 Brother 色票**（`#c0392b` → `#d15400`），DST 完全不存線色。給工廠的線色清單以 threadlist／規格表為準。
- Ink/Stitch 以原始碼 + 固定 tag/commit 部署；wxPython 用 Ubuntu 套件；inkex 以 `--no-deps` 安裝避開僅 GUI 需要的 PyGObject（官方 git 版本的 metadata 有語法錯誤，PyPI 1.4.1 正常）。
- Ink/Stitch 為 GPL-3.0；若散布此映像，需另行審閱授權義務（規劃書 §14）。
