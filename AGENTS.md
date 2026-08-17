# 專案規則

供 coding agent 讀取的常駐上下文。**開工前先讀完這份。**

## 這是什麼

黑客松專案模板。FastAPI + React（JSX，非 TS）。套件管理用 uv。
時間極度有限，優先順序是：**能跑 > 完整 > 漂亮**。

## 架構鐵則

這是本專案唯一不可妥協的設計。違反了要重寫。

```
輸入 → ai/ 理解 → services/ 計算 → ai/ 解釋 → 輸出
              ↑              ↑
          機率性、可錯    確定性、可測
```

| 層 | 負責 | 禁止 |
|---|---|---|
| `ai/` | 聽懂輸入、生成說明文字 | 任何判定、計算、分數 |
| `services/` | 判定、計算、驗證、排序 | 任何 AI 呼叫、任何 I/O |

**具體禁令：**

- `services/` 內不得出現 `import ai`、不得呼叫任何外部 API
- `services/` 的函式必須是純函式：同輸入永遠同輸出
- 判定結果與分數一律由 `services/` 產出，AI 只負責把結果講成人話
- AI 的輸出不得反過來覆寫 `services/` 的判定

理由：這條界線是專案的技術論述。判定邏輯一旦漏進 `ai/`，就失去「核心不經過 AI」的立場。

## 開發模式

- `models.py`（介面契約）：先定規格，規格未定案不得動工（SDD）
- `services/`：先寫測試再寫邏輯（TDD），核心判定案例必須涵蓋
- `ai/` 與前端：直接實作，不要求先寫測試，能跑優先

## 其他規則

- 修改 `models.py` 前必須先問。它是前後端契約，改動成本最高。
- 新增 AI 任務時，prompt 一律放 `ai/prompts/*.md`，不得寫死在 Python 裡。
- Gemini 的呼叫一律經過 `ai/client.py`，其他檔案不得直接 import SDK。
- 每個 AI 任務都要有失敗時的 fixture 降級路徑，不可讓整條流程中斷。
- 測試只寫給 `services/`，不要測 AI（輸出不穩定，測了浪費時間）。
- 裝套件用 `uv add`，不要手改 `pyproject.toml`。

## 刻意不做的事

不要主動加入：ORM、migration、使用者認證、
TypeScript、狀態管理套件、`utils/` 萬用資料夾、日誌框架。

24 小時內這些全是純成本。狀態存記憶體或 React state 就夠——
除非題目確定需要跨 session／跨使用者保存資料，才用得到 `db/`。

> 例外一：`Dockerfile` 與 `.github/workflows/` 已存在，是為了部署到 Cloud Run
> 讓評審用自己的裝置操作，不是本機開發的一部分。本機開發不需要 Docker，
> 也不要因為看到這兩個檔案就假設本機流程改變了。
>
> 例外二：`backend/db/cloudsql/client.py` 已存在，是 Cloud SQL 的唯一連線入口，
> 比照 `ai/client.py` 的角色。它只提供連線池與 `ping()`，**不含任何 schema／CRUD**——
> 資料表怎麼設計是題目定案後才決定的事。`config.DB_INSTANCE_CONNECTION_NAME` 留空時
> （本機開發預設如此）完全不會被呼叫，不影響原有流程。真的要讀寫資料時，
> 邏輯應該寫在呼叫端（`main.py` 或新的一層），不要塞進 `services/`——
> `services/` 不得有任何 I/O 的鐵則沒有因為加了 DB 而改變。

## 拆檔門檻

沒到門檻不要拆。過早拆檔在小專案是負收益。

| 拆什麼 | 門檻 |
|---|---|
| `routers/` | endpoint > 6 |
| `services/` 拆多檔 | 單檔 > 300 行 |
| 前端 `pages/` | 畫面 > 3 個 |

## 驗證指令

```bash
cd backend && uv run pytest                        # 測試
cd backend && DEMO_MODE=true uv run pytest         # 離線模式測試
grep -rn "import ai" backend/services/              # 應無輸出
```

## 回報方式

每完成一個階段，回報：
1. 改了哪些檔案
2. 驗證指令的實際輸出
3. 你做過的假設（尤其是規格沒寫清楚的地方）

不要一次做完多個階段。每階段結束後停下來等指示。
