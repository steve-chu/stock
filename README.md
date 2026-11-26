# 我的看盤台：手機版（iPhone）

電腦版（`stock-platform`）不動。這個資料夾是另外做的手機版：

- **GitHub 每個交易日傍晚自動跑一次**（18:40、21:10 各一次），用電腦版一模一樣的程式（`core/`）抓收盤、算好全部分析，發佈成一個網頁。
- iPhone 用 Safari 打開網址 →「加入主畫面」，之後就像 App 一樣點開來看。
- **完全免費**，電腦不用開著。網址可以傳給家人朋友，他們也能加到主畫面。
- **持股只存在各自的手機裡**，不會上傳，每個人看到的是自己的損益。

手機版是「看」的：自選股、分類、長期名單不能在手機上改（要改自選股請改 `stocks.txt`，見下面）。也沒有「回看」。

---

## 第一次設定（約 10 分鐘，只做一次）

### 1. 註冊 GitHub
到 <https://github.com> 註冊（免費）。

### 2. 把這個資料夾放上去（二選一）

**A. 用 GitHub Desktop（推薦，最不會出錯）**
1. 安裝 <https://desktop.github.com> → 登入。
2. File → **Add local repository** → 選這個 `stock-mobile` 資料夾 → 它說「不是 Git 倉庫」→ 按 **create a repository** → Create repository。
3. 按上方 **Publish repository** → **把「Keep this code private」取消勾選** → Publish。
   （免費帳號的網頁只能用公開倉庫；裡面沒有你的持股，持股只在手機上）

**B. 用網頁上傳**
1. 右上「＋」→ New repository → 取名（例如 `stock`）→ 選 **Public** → Create。
2. 按「uploading an existing file」→ 把資料夾裡的東西全部拖進去 → Commit。
3. **`.github` 資料夾一定要上去**。如果沒傳上去：Add file → Create new file，檔名打 `.github/workflows/build.yml`，內容貼上這個資料夾裡同名檔案的內容。

### 3. 打開網頁功能
倉庫上方 **Settings** → 左邊 **Pages** → Source 選 **GitHub Actions**。

### 4.（建議）放 FinMind token
跟電腦版 `.env` 裡的 `FINMIND_TOKEN` 同一個。
Settings → Secrets and variables → Actions → **New repository secret**
- Name：`FINMIND_TOKEN`
- Secret：貼上 token

沒放也能跑，只是抓資料的次數上限比較低。

### 5. 第一次手動跑
倉庫上方 **Actions** → 左邊「每日更新」→ 右邊 **Run workflow**。大約 3～5 分鐘，變綠色勾勾就好了。
網址在 Settings → Pages 最上面，長這樣：`https://你的帳號.github.io/stock/`

### 6. 加到 iPhone 主畫面
用 **Safari** 打開網址 → 下方「分享」按鈕 →「**加入主畫面**」。

---

## 平常怎麼用

- 點一檔 → 看 K 線和三個分頁；左上「‹ 自選股」回清單。
- 「重新整理」= 重新讀取 GitHub 最新算好的資料（不是即時行情，是每天收盤後的分析）。
- 「我的持股」可以記買賣，只存在這支手機的 Safari 裡。**換手機或清除 Safari 資料會不見**，重要的紀錄請以電腦版為準。

## 加／刪自選股
在 GitHub 倉庫點 `stocks.txt` → 右上鉛筆 ✏️ 編輯 → 一行一個代號 → Commit changes。
存檔後會自動重跑一次（幾分鐘），新股票就出現了。

## 電腦版改了程式，手機版要跟著更新
把電腦版的 `.py` 和 `static/` 複製到這裡的 `core/`（`data` 不用），再上傳到 GitHub。存上去就會自動重跑。

## 不想讓不認識的人看到？
網址沒公開的話一般人找不到。如果要上鎖，可以用 Cloudflare Access（50 人以內免費）加一個「輸入 Email 收驗證碼」的門，需要時再跟我說。

---

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `core/` | 電腦版程式的複本（原封不動） |
| `web/` | 手機版外殼：手機排版、把資料改從檔案讀、持股存在手機 |
| `build.py` | GitHub 每天跑的那支：算好全部分析，輸出網頁到 `site/` |
| `stocks.txt` | 自選股清單 |
| `seed/market.db` | 第一次用的資料庫（從電腦版複製，已刪掉交易紀錄） |
| `.github/workflows/build.yml` | 排程設定 |

資料庫之後存在倉庫的 `db` 分支，每天覆蓋，只保留最新一份。
本機測試（不連網路）：`OFFLINE=1 python build.py`，然後在 `site/` 開一個網頁伺服器。
