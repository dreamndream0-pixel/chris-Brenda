# AI Embroidery Studio — Gate A（核心可編譯能力）

對應規劃書 §12 Gate A：**固定的手工 SVG → Ink/Stitch CLI 產生 ZIP → 取出 DST/PES → pyembroidery 重讀驗證 → 針跡預覽**。不含 AI、前端、資料庫。

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

# 完整 Gate A（在 worker 映像內，含真實 Ink/Stitch）
docker build -f infra/worker/Dockerfile -t emb-worker:gate-a .
mkdir -p out && chmod 777 out
docker run --rm --network=none --cpus=2 --memory=2g -v "$PWD/out:/out" emb-worker:gate-a \
  python services/worker/gate_a.py --fixtures fixtures --out /out/gate-a
# 然後用瀏覽器開 out/gate-a/preview.html
```

Gate A 通過條件：四張 fixture 全部 `PASS`，即 DST/PES 皆可重讀、針數 > 0、尺寸在容差內、色段數正確、預覽播放的針數與 DST 解碼一致。

## 目前狀態與已知事項

- **單元測試：16 passed**（engine 安全性、逾時、錯誤碼、驗證、預覽一致性、gate_a 流程）。
- **真實 Ink/Stitch 編譯尚未在此環境跑過**；需在 worker 映像內執行 `gate_a.py` 確認，並依實際結果微調 `expected.json` 容差。
- Ink/Stitch 官方 Linux 執行檔未使用；改以原始碼 + 固定 tag/commit 部署。wxPython 由 Ubuntu 套件提供（CLI 匯入時需要，不開 GUI）；inkex 以 `--no-deps` 安裝以避開僅 GUI 需要的 PyGObject。
- **PES 會把線色吸附到 Brother 色票**（測試中 `#c0392b` → `#d15400`），DST 則完全不存線色。給工廠的線色清單必須以 threadlist／規格表為準。
- Ink/Stitch 為 GPL-3.0；若散布此映像，需另行審閱授權義務（規劃書 §14）。
