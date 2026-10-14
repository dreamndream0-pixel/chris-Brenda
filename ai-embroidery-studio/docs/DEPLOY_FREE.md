# 免費部署：Supabase + Render + Vercel

> 2026-10 更新：Hugging Face 的 Docker Space 已改為需要 PRO 訂閱（約 US$9／月），免費方案改用 **Render 免費 Web Service**（0.1 vCPU / 512 MB，編譯約慢 10 倍、閒置 15 分鐘休眠）。下方 Hugging Face 步驟保留給訂閱 PRO 的情況（Actions 改為手動執行）。後端用同一個映像 `infra/cloud/Dockerfile`，Render 的設定寫在 repo 根目錄的 `render.yaml`。

| 服務 | 放什麼 |
|---|---|
| Supabase | 帳號登入、資料庫、上傳的圖與刺繡檔 |
| Hugging Face Space | 後端 API ＋ Ink/Stitch 編譯（同一個服務，不需要 Redis） |
| Vercel | 網站畫面 |

**順序很重要**：先 Supabase → 再 Vercel（拿到網址）→ 再 GitHub 設定 → 最後觸發部署。全部約 30 分鐘，其中 Hugging Face 第一次建置要等 10–20 分鐘。

---

## 第 1 步：Supabase（約 10 分鐘）

1. 到 supabase.com → **New project**。名稱隨意（例如 `embroidery`），**Region 選 Northeast Asia (Tokyo)**，設定一組資料庫密碼並**記下來**。
2. 等專案建好後，左側 **SQL Editor** → **New query**。打開 GitHub 上的 [`ai-embroidery-studio/infra/supabase/migrations/0001_embroidery.sql`](../infra/supabase/migrations/0001_embroidery.sql)（記得切到 `embroidery-gate-a` 分支），**整份複製貼上** → 按 **Run**。看到 `Success. No rows returned` 就對了。
3. 記下這些值（之後要貼到 GitHub 和 Vercel，**不要貼到對話裡**）：

| 名稱 | 在哪裡找 | 長相 |
|---|---|---|
| Project URL | 上方 **Connect** 按鈕，或 Settings → Data API | `https://xxxx.supabase.co` |
| Publishable key | Settings → **API Keys** | `sb_publishable_...`（舊專案叫 anon key，`eyJ...`） |
| Secret key | Settings → **API Keys** → Secret keys | `sb_secret_...`（舊專案叫 service_role，`eyJ...`）⚠️ 機密 |
| 資料庫連線字串 | 上方 **Connect** → **Transaction pooler** → URI | `postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-...pooler.supabase.com:6543/postgres` |

   連線字串要改兩處：`[YOUR-PASSWORD]` 換成你的資料庫密碼；開頭的 `postgresql://` 改成 **`postgresql+psycopg://`**。

## 第 2 步：Vercel 網站（約 5 分鐘）

1. 到 vercel.com → **Add New… → Project** → 匯入 GitHub 的 `chris-brenda` repo（第一次要授權 Vercel 讀取）。
2. 設定：
   - **Project Name**：例如 `emb-studio`（網址會是 `https://emb-studio.vercel.app`，**記下這個網址**）
   - **Root Directory**：按 Edit 選 `ai-embroidery-studio/apps/web`
   - **Environment Variables**（4 個）：

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://<HF帳號>-emb-api.hf.space`（全小寫；例如帳號 `Brenda` → `https://brenda-emb-api.hf.space`） |
| `NEXT_PUBLIC_AUTH_MODE` | `supabase` |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase 的 Project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase 的 **Publishable** key（不是 Secret key！） |

3. 按 **Deploy**。第一次很可能**失敗**，因為 Vercel 預設部署 `main` 分支，而程式碼在 `embroidery-gate-a`。這是正常的：
   到專案 **Settings → Git → Production Branch** 改成 `embroidery-gate-a` → 存檔 → **Deployments** 頁按右上 **⋯ → Redeploy**（或到 GitHub 隨便觸發一次推送）。
4. 回到 Supabase：**Authentication → URL Configuration**
   - **Site URL**：`https://emb-studio.vercel.app`（換成你的）
   - **Redirect URLs** 加一筆：`https://emb-studio.vercel.app/studio`

## 第 3 步：Hugging Face token（約 2 分鐘）

huggingface.co → 右上頭像 → **Settings → Access Tokens → Create new token** → Token type 選 **Write** → 建立後複製（`hf_...`）。**不用自己建 Space**，部署程式會自動建立一個公開的 `emb-api` Space。

## 第 4 步：GitHub 設定（約 5 分鐘）

GitHub 的 `chris-brenda` repo → **Settings → Secrets and variables → Actions**。

**Secrets 分頁**（New repository secret，機密）：

| Name | Value |
|---|---|
| `HF_TOKEN` | 第 3 步的 `hf_...` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase 的 **Secret** key |
| `EMB_DATABASE_URL` | 改好的 `postgresql+psycopg://...` 連線字串 |
| `ANTHROPIC_API_KEY` | （選填）要用 AI 針法建議才設；不設就由規則判斷 |

**Variables 分頁**（New repository variable，非機密）：

| Name | Value |
|---|---|
| `HF_SPACE` | `<HF帳號>/emb-api`（例如 `Brenda/emb-api`） |
| `SUPABASE_URL` | Supabase 的 Project URL |
| `WEB_ORIGIN` | Vercel 網址，例如 `https://emb-studio.vercel.app` |

## 第 5 步：部署後端

GitHub repo → **Actions** → 左側 **Deploy embroidery API to Hugging Face** → **Run workflow** → Branch 選 `embroidery-gate-a` → Run。

- Action 約 1 分鐘完成（把程式上傳到 Hugging Face）。
- 接著 Hugging Face 開始建置 Docker（第一次 10–20 分鐘），進度在 `https://huggingface.co/spaces/<HF帳號>/emb-api` 的 **Logs**。
- 狀態變成 **Running** 後，打開 `https://<HF帳號>-emb-api.hf.space/healthz`，看到 `{"ok":true,"authMode":"supabase","queueMode":"thread"}` 就成功了。

之後只要程式推到 `embroidery-gate-a`，後端與網站都會自動更新。

## 第 6 步：試用

1. 打開 Vercel 網址 → 右上 **登入** → **註冊** → 去信箱點確認連結。
2. 登入後 **新增專案** → 上傳一張 Logo（或 repo 裡的 `fixtures/uploads/two_color_badge.svg`）→ 開始分析 → 編譯 → 下載。
3. 第一次開啟若後端在休眠，會等 1–2 分鐘才回應。

## 出問題時

| 現象 | 原因／處理 |
|---|---|
| Action 顯示 `missing required setting: XXX` | 第 4 步少設了 XXX |
| Action 顯示 `EMB_DATABASE_URL must start with postgresql+psycopg://` | 連線字串開頭沒改 |
| `/healthz` 打不開、Space 顯示 Runtime error | 看 Space 的 Logs，把最後 30 行貼給我（**先遮掉任何金鑰**） |
| 網站顯示「發生錯誤（http_0）」或一直轉圈 | 後端在休眠或 `NEXT_PUBLIC_API_URL` 打錯；先打開 `/healthz` 叫醒它 |
| 登入後顯示 `invalid_token` | 檢查 Vercel 的 `NEXT_PUBLIC_SUPABASE_URL` 與 GitHub 的 `SUPABASE_URL` 是同一個專案 |
| 上傳後卡住或 CORS 錯誤 | GitHub 的 `WEB_ORIGIN` 要和 Vercel 網址完全一樣（https、沒有結尾斜線），改完重跑第 5 步 |

## 免費方案的限制

- Hugging Face Space 48 小時沒人用會休眠，喚醒 1–2 分鐘；Space 是公開的（程式碼可見，金鑰與使用者檔案不會公開）。
- 同一時間只編譯 1 件，其他排隊；重啟時進行中的工作會標示「伺服器重啟」，需重按編譯。
- Supabase 免費專案一週沒活動會暫停，到 Supabase 後台按 Restore 即可。
- Vercel Hobby 方案限非商業使用；正式收費營運時請升級或改用其他主機。
