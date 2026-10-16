# Brenda & Chris 婚禮邀請函

純靜態 HTML、CSS、JavaScript，可直接由 GitHub Pages 發布，無需建置。

## 設計

以奶油白浮雕花卉、香檳金、手寫字體和封蠟信封呈現邀請函。保留原頁婚禮資料、合照、音樂及兩頁菜單；日期為 2026-05-30。原本時間標記混用 AM / PM，現統一為 24 小時制。

- `index.html`：婚禮內容與無 JavaScript 時的基本連結。
- `styles.css`：手機與桌面版面、信封開場、減少動畫偏好。
- `script.js`：開場、音樂播放、菜單彈窗。
- `assets/original-page-*.jpg`：從舊版頁面原樣擷取，未修改照片或菜單。
- `assets/wedding-music.mp3`：原頁音樂，點擊封蠟後才播放。
- `assets/brenda-chris-wedding.ics`：全天婚禮行事曆事件。

本機預覽：`python -m http.server 8765 --bind 127.0.0.1`。

## 花卉素材

使用內建 imagegen 產生，專案檔案：`assets/floral-paper.png`。

Final prompt:

> Create an original luxury wedding invitation stationery background, portrait 2:3 composition. Photorealistic ivory cotton paper with exquisite sculpted embossed WHITE flowers: elegant large garden roses, small five-petal blossoms, delicate leaves and tiny buds arranged generously in the upper left corner, upper right edge and bottom corners. Tone-on-tone warm creamy white bas-relief, soft natural light, subtle shadows, tactile handmade paper, restrained elegant Parisian wedding stationery. Keep the entire central 65 percent clean empty ivory paper for overlaying typography. Flowers occupy only the outer edges, no colored flowers, no gold border, NO TEXT, no monograms, no letters, no envelope, no logos. Straight-on flat lay, high-end editorial photography.
