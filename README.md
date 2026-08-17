# Hackathon Template

FastAPI + React 的黑客松起手式。目標：**題目一公布，30 分鐘內從零到畫面上出現 AI 的回應。**

領域中立，任何主題都能套。

---

## 快速開始

```bash
# 後端（使用 uv）
cd backend
uv sync                       # 建 .venv 並裝好所有套件
cp .env.example .env          # 填入 GEMINI_API_KEY
uv run uvicorn main:app --reload --port 8000

# 前端（另開終端機）
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

沒裝 uv：`curl -LsSf https://astral.sh/uv/install.sh | sh`（Windows 用 `winget install astral-sh.uv`）

常用指令：

| 動作 | 指令 |
|---|---|
| 裝套件 | `uv add <package>` |
| 裝開發用套件 | `uv add --dev <package>` |
| 移除套件 | `uv remove <package>` |
| 跑測試 | `uv run pytest` |
| 同步環境（拉到隊友的 commit 後） | `uv sync` |

`uv.lock` 會自動產生，**務必進版控**。四人環境不一致的問題通常在凌晨才爆出來。

`backend/.python-version` 已鎖定版本，`uv sync` 會照這個建環境，需要的話還會自動下載對應版本。

前端已設 proxy，一律打 `/api`，不用處理 CORS。

驗收：打開前端頁面按「開始分析」，有結果就代表全串通了。

---

## 三個核心設計

### 1. `services/` 與 `ai/` 實體分離

```
輸入 → ai/ 理解 → services/ 計算 → ai/ 解釋 → 輸出
              ↑                ↑
          機率性、可錯      確定性、可測
```

| 層 | 負責 | 不負責 |
|---|---|---|
| `ai/` | 聽懂輸入、生成說明 | ❌ 判定、計算 |
| `services/` | 判定、計算、驗證 | ❌ 語言理解 |

**這不只是整潔，這是你的技術論述。** 評審問「AI 出錯怎麼辦」或
「這不就是包一層 ChatGPT」，答案是：核心判定根本不經過 AI，
是確定性的 Python，有單元測試，每條結論都附依據。

### 2. `DEMO_MODE` 保命開關

`.env` 設 `DEMO_MODE=true`，AI 層改讀 `fixtures/`，完全不呼叫外部 API。

即使沒開這個旗標，AI 呼叫失敗時也會自動退回 fixture，流程不會整條死掉。

現場網路異常、額度用完、API 變慢時，你還是演得完。

### 3. `models.py` 是前後端契約

第 1 小時定案。定完就寫幾支回傳假資料的 endpoint 丟給前端，
讓前端全程並行，不用等後端。

**前端等後端是黑客松最大的時間黑洞。**

---

## 目錄

```
Dockerfile              Cloud Run 部署用（前端 build 靜態檔 + 後端一起包）
.dockerignore
.github/
└── workflows/
    └── deploy-to-production-on-push-tag.yml   push tag 自動部署到 Cloud Run

backend/
├── pyproject.toml       套件管理（uv）
├── .python-version      鎖定 Python 版本
├── main.py              入口 + 路由（endpoint < 6 個不要拆 routers/）
├── config.py            環境變數集中處
├── models.py            ★ Pydantic schema = 前後端契約
├── services/            ★ 業務邏輯：確定性、純函式、可測試
├── ai/
│   ├── client.py        Gemini 唯一入口（其他地方別直接 import SDK）
│   ├── tasks/           一個 AI 任務一支檔
│   └── prompts/         ★ prompt 存 .md，標題／清單分段，非工程師也能改
├── db/
│   └── cloudsql/
│       └── client.py    Cloud SQL 唯一連線入口，只有連線池／ping()，不含 schema
├── data/                靜態資料、規則庫
├── fixtures/            ★ Demo 固定素材（進版控）
└── tests/               只測 services/，不測 ai/

frontend/
└── src/
    ├── api/client.js    ★ 所有後端呼叫集中一支
    ├── components/
    └── App.jsx

docs/
├── api.md                     介面契約
├── demo-script.md             ★ 第一天就開檔
├── dry-run-spec.md            開發流程演練用（賽前熱身，非正式比賽規格）
├── agent-prompts.md           搭配 coding agent 分階段開發的 prompt
└── day-of-gcp-checklist.md    ★ 比賽當天換 GCP 帳號要重新設定的東西
```

---

## 比賽當天怎麼改

| 順序 | 動作 | 檔案 |
|---|---|---|
| 1 | 改領域模型 | `models.py` |
| 2 | 改判定邏輯 | `services/analyzer.py` |
| 3 | 改 prompt | `ai/prompts/*.md` |
| 4 | 換 Demo 素材 | `fixtures/demo_items.json` |
| 5 | 改畫面文案 | `App.jsx`、`ResultCard.jsx` |

架構不用動。只改上面五個地方。

---

## 為什麼 prompt 用 .md 不用 .txt

- 可以用標題、清單、程式碼區塊分段，長 prompt 讀起來不會是一坨文字
- GitHub 和多數編輯器對 `.md` 有語法高亮，`.txt` 沒有
- 團隊裡不寫程式的人（負責文案、Pitch）也能直接開檔案改用詞，不用碰 Python

`ai/client.py` 的 `load_prompt()` 用 `str.format()` 帶入變數，
所以 prompt 裡除了 `{變數名稱}` 之外，**不要出現其他單獨的花括號**，
不然 `.format()` 會報錯。

---

## 刻意不放的東西

ORM、migration、使用者認證、TypeScript、狀態管理套件、`utils/` 萬用資料夾。

24 小時內這些全是純成本。狀態存記憶體或 React state 就夠，
除非題目需要跨 session／跨使用者保存資料，才用得到 `backend/db/`。

> `Dockerfile` 與 `.github/workflows/` 是例外：只為了把整個服務部署到 Cloud Run
> 給評審用自己的裝置操作，跟本機開發流程無關。**本機開發還是照上面「快速開始」
> 分開跑 `uvicorn` 和 `npm run dev`，不需要裝 Docker。**
>
> `backend/db/cloudsql/client.py` 也是例外：Cloud SQL 的唯一連線入口，只有連線池
> 跟 `ping()`，不含 schema。本機不設 `CLOUD_SQL_CONFIG` 環境變數就完全不會被呼叫。

---

## 拆檔門檻

沒到門檻就別拆。過早拆檔在小專案是負收益。

| 拆什麼 | 門檻 |
|---|---|
| `routers/` | endpoint > 6 |
| `services/` 拆多檔 | 單檔 > 300 行 |
| 前端 `pages/` | 畫面 > 3 個 |

---

## 賽前檢查清單

- [v] 這份模板從零跑通一次（不是讀過，是真的跑起來）
- [v] **uv 先試跑過**（`uv sync`、`uv run pytest`、`uv add`）——任何工具都不該在比賽當天首次使用
- [v] `GEMINI_API_KEY` 已確認可用，額度足夠團隊人數
- [ ] **確認官方文件的 SDK 套件名、模型字串、structured output 用法**
- [v] 圖片輸入實測過一次
- [v] `DEMO_MODE=true` 實測過，離線能完整跑完
- [ ] 簡報模板留空格：問題／方案／Demo／技術／市場／團隊
- [v] 用 `docs/dry-run-spec.md` 跑過一次完整演練，校準時間估算

> ⚠️ `ai/client.py` 的 SDK 寫法變動很快。**不要照這份或任何教學文章直接抄**，
> 賽前務必到官方文件確認一次。這是最容易在當天卡住的地方。

---

## 當天前 90 分鐘

| 時間 | 做什麼 |
|---|---|
| 0–30 分 | 各自安靜寫點子，不討論（避免第一個發言的人綁架方向） |
| 30–60 分 | 攤開來篩：資料當場拿得到嗎？室內演得了嗎？跟直接問 ChatGPT 差在哪？ |
| 60–75 分 | **定案，不再回頭** |
| 75–90 分 | 定 `models.py`、分工、開跑 |

黑客松最常見的死法不是技術做不出來，是三小時後還在爭論要做什麼。
