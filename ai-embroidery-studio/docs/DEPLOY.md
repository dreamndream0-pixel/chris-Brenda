# 部署指南（Supabase + Redis + API/worker + Vercel）

架構：瀏覽器（Vercel 上的 Next.js）→ FastAPI（容器）→ Redis 佇列 → worker（同一個映像，含 Ink/Stitch）；資料庫、登入、檔案都在 Supabase。

> 本專案在開發環境只用「開發登入 + 本機 SQLite + 本機檔案」驗證過完整流程；Supabase 部分已用真實 Postgres（套用同一份 migration、RLS）與模擬的 Storage API 測試過，但**還沒有連到真正的 Supabase 專案跑過**。第一次部署請照最後的「上線驗證」逐項確認。

## 1. Supabase

1. 建立專案（區域選離使用者近的，例如 Tokyo / Singapore）。
2. **SQL Editor** 貼上並執行 `infra/supabase/migrations/0001_embroidery.sql`：建立 `emb_*` 資料表、RLS、私有 bucket `embroidery`（單檔 50 MB 上限）。
3. **Authentication → Providers → Email** 開啟；**URL Configuration** 的 Site URL 填網站網址，Redirect URLs 加 `https://<你的網域>/studio`。
4. 記下這些值（**Project Settings**）：

| 名稱 | 在哪裡 | 給誰 |
|---|---|---|
| Project URL | API 設定 | API、worker、網站 |
| anon / publishable key | API Keys | **只給網站**（公開金鑰） |
| service_role / secret key | API Keys | **只給 API 與 worker**（絕不可放前端） |
| JWKS URL = `<Project URL>/auth/v1/.well-known/jwks.json` | 新專案預設使用非對稱 JWT 簽章金鑰 | API |
| （舊專案）JWT Secret | JWT Keys → Legacy | API（擇一，與 JWKS 二選一） |
| 資料庫連線字串（Connection pooler，Transaction 模式，port 6543） | Database → Connect | API、worker |

連線字串要改成 SQLAlchemy 格式：`postgresql+psycopg://postgres.<ref>:<密碼>@<host>:6543/postgres`（程式已關閉 prepared statements，可搭配 pooler 的 transaction 模式）。

## 2. Redis

任何 Redis 6+ 都可以（Render Key Value、Upstash、自架）。記下 `redis://` 或 `rediss://` URL。

## 3. API 與 worker（同一個 Docker 映像）

映像：`infra/worker/Dockerfile`（Ubuntu 24.04 + Ink/Stitch v3.3.0 固定版本 + 後端程式）。以 Render 為例：一個 **Web Service**（API）＋一個 **Background Worker**，都指向這個 Dockerfile。

| 服務 | 啟動指令 |
|---|---|
| API | `uvicorn services.api.main:app --host 0.0.0.0 --port $PORT` |
| worker | `rq worker emb --url $EMB_REDIS_URL` |

環境變數（兩者共用，除非另註）：

| 變數 | 值 |
|---|---|
| `EMB_AUTH_MODE` | `supabase` |
| `SUPABASE_JWKS_URL` | `<Project URL>/auth/v1/.well-known/jwks.json`（或舊專案用 `SUPABASE_JWT_SECRET`） |
| `EMB_STORAGE` | `supabase` |
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | service_role / secret key |
| `EMB_DATABASE_URL` | 上面的 `postgresql+psycopg://...` |
| `EMB_REDIS_URL` | Redis URL |
| `EMB_QUEUE_MODE` | `rq` |
| `EMB_SIGNING_SECRET` | 隨機長字串（`openssl rand -hex 32`），API 與 worker 相同 |
| `EMB_PUBLIC_API_URL` | API 的公開網址，例如 `https://emb-api.onrender.com` |
| `EMB_CORS_ORIGINS` | 網站網址，例如 `https://studio.example.com`（多個用逗號） |
| `EMB_DATA_DIR` | `/data`（worker 的 Ink/Stitch 快取放這裡；可掛持久磁碟，不掛也能動） |
| `ANTHROPIC_API_KEY` | **只放 worker**：啟用 AI 針法建議 |
| `EMB_AI_ENABLED` | **只放 API**：`1` 讓網站顯示 AI 按鈕（API 本身不需要金鑰） |
| `EMB_AI_MODEL` | 選填，預設 `claude-opus-5-5` |

資源建議：worker 至少 2 vCPU / 2 GB RAM。一張少色吉祥物冷編譯約 1–2 分鐘（引擎逾時 300 秒、工作逾時 600 秒），同時處理多個工作就多開幾個 worker。

## 4. 網站（Vercel）

Root Directory 設 `ai-embroidery-studio/apps/web`，Framework 選 Next.js。環境變數：

| 變數 | 值 |
|---|---|
| `NEXT_PUBLIC_API_URL` | API 公開網址 |
| `NEXT_PUBLIC_AUTH_MODE` | `supabase` |
| `NEXT_PUBLIC_SUPABASE_URL` | Project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon / publishable key |

## 5. 上線驗證（第一次部署請逐項確認）

1. `GET <API>/healthz` 回 `{"ok":true,"authMode":"supabase","queueMode":"rq"}`。
2. 網站「註冊」→ 收確認信 → 登入，右上角出現 email。
3. 上傳 `fixtures/uploads/two_color_badge.svg`：Supabase Storage 的 `embroidery/private/<user id>/...` 出現原檔。
4. 編譯成功並看到針跡；下載 ZIP（連結是 Supabase 簽名網址，約 5 分鐘失效）。
5. 用另一個帳號登入，看不到前一個帳號的專案。
6. （有設 AI）按「請 AI 建議針法」，產生新版本並顯示 AI 摘要；Anthropic Console 看得到用量。

## 6. 安全與合規提醒

- service_role key、`EMB_SIGNING_SECRET`、`ANTHROPIC_API_KEY` 只放伺服器端環境變數。
- AI 會收到「區域重繪圖 + 幾何數據」（不是原始上傳檔）；網站上有告知文字。若客戶圖稿有保密要求，可不設 `ANTHROPIC_API_KEY`，系統改用規則判斷。
- Ink/Stitch 為 GPL-3.0。純 SaaS 自用與「散布映像給他人」的義務不同；若要把映像交給工廠或客戶，請先審閱授權（規劃書 §14）。
- 目前沒有刪除專案／帳號的功能與檔案保留政策，正式收客戶圖稿前需補上（規劃書 §14 資安與隱私）。
