# Agent 分階段開發 Prompt

搭配 `AGENTS.md` 與 `spec.md` 使用。**從零開始實作。**

## 使用方式

**一次只貼一個階段,驗收完再進下一步。**

不要一次貼完整份規格——那樣 agent 會一路做到底,你來不及審,錯了也不知道錯在哪。

每個階段結尾都要求 agent「停下來等確認」,這是刻意的。你要在每個交接點確認方向沒歪,尤其是 `services/` 與 `ai/` 的界線。

**預估總時數約 5 小時**(不含前端美化與 Demo 準備)。若某階段超時 50%,砍功能而不是延長時間。

---

## 階段零:載入上下文(10 分鐘)

```
請先讀 AGENTS.md 和 docs/spec.md,然後只回答我四件事:

1. 用兩句話說明 ai/ 和 services/ 的職責界線
2. 為什麼資格判定要回傳三態而不是二態?
3. 這個專案的 Demo 核心爆點是什麼?
4. 你認為規格裡最容易出錯或最模糊的地方是什麼

先不要寫任何程式碼,也不要建立任何檔案。
```

**為什麼要這一步**:確認它讀懂架構鐵則。第 4 題的答案通常會提前暴露規格漏洞,比事後除錯便宜太多。

**驗收**:如果它第 1 題答不出「ai 決定呼叫什麼、services 負責算」,或第 3 題沒提到「超載後改查明日」,重新讓它讀一次再問。

---

## 階段一:專案骨架與介面契約(30 分鐘)

```
建立專案骨架與 backend/models.py。

目錄結構:
backend/
├── pyproject.toml        uv 管理,依賴: fastapi uvicorn[standard] pydantic
│                          python-dotenv google-genai;dev: pytest
├── .python-version       3.12
├── .env.example
├── config.py             環境變數集中處,含 DEMO_MODE 開關
├── models.py             ★ 本階段重點
├── services/__init__.py
├── ai/__init__.py
├── ai/prompts/
├── data/__init__.py
├── fixtures/
└── tests/

frontend/                 Vite + React(JSX,非 TS)

models.py 需定義的型別(依 spec.md §3-§5):

列舉:
- Eligibility: eligible | ineligible | needs_review   ← 三態,不可簡化
- WeightBand: light | medium | heavy
- BlockType: text | choices | upload | result | trace
- CaseStatus: pending | scheduled | deferred | rejected

領域模型:
- Location(address, district, lat, lng)
- ItemAttributes(weight_band, max_dimension_cm, dismantlable,
                 special_handling, volume_units)
- WasteItem(name, category, quantity, confidence, attributes)
- EligibilityResult(status, reasons, rule_refs, clarification_needed)
- Case(id, location, items, eligibility, status, resource_hint, note, created_at)

排程:
- Stop(seq, case, eta_minutes)
- Shift(id, district, date, capacity_units, used_units, stops, total_minutes)
  需有 load_ratio 與 overloaded 兩個 property
- InsertionPlan(shift_id, position, added_minutes,
                resulting_load_ratio, feasible, reason)

Agent:
- TraceStep(icon, action, detail, tool, is_pivot)
  is_pivot 標記 agent 改變計畫的關鍵步驟

訊息流:
- Choice(label, value)
- MessageBlock(type, content, question, options, case, trace)
- Message(role, blocks)

API:
- ApiResponse(ok, data, error)  統一外殼
- SubmitCaseRequest / SubmitCaseResponse
- ScheduleResponse
- ProposeInsertionRequest / ProposeInsertionResponse
- AcceptInsertionRequest

要求:
- 每個模型加簡短 docstring 說明用途
- 三態、is_pivot 這類刻意設計要在註解標明原因
- 不要寫任何業務邏輯

完成後回報:
- models.py 完整內容
- uv run python -c "import models" 的實際輸出
- 你做的任何補充假設

然後停下來等我確認。
```

**驗收重點**:`Eligibility` 是三態、`TraceStep` 有 `is_pivot`。這兩個是後面所有階段的地基。

---

## 階段二:規則表與資格判定(50 分鐘)

```
建立 data/rules.py 與 services/eligibility.py。

【data/rules.py】

依 spec.md §6.2 建立規則表,包含:
- ACCEPTED_ITEMS: 分類 -> 品項清單(廢棄家具/家電用品/其他)
- QUANTITY_THRESHOLDS: 廢行李箱 3 只門檻
- EXCLUDED_APPLICANTS: 住家兼營商業、機構、學校、部隊、法人
- RENOVATION_KEYWORDS: 觸發裝潢廢料追問的關鍵字
- STONE_KEYWORDS: 石材類(原文限定「非石材類」)
- CONSTRUCTION_WASTE: 馬桶、浴缸、流理台
- 服務時間: 週日不收運、至少提前一日、21 時後排出
- LAST_VERIFIED 與 SOURCE_URL 常數

★ 硬性要求:
- 每條規則標註來源
- 尚未查證的內容標 TODO,不得自行編造數值
- 特別是罰則金額,沒有確認來源就不要寫

【services/eligibility.py】

check(items, applicant_type="household", renovation_by=None) -> EligibilityResult

判定順序:
1. 申請對象排除 -> ineligible
2. 營建廢棄物(馬桶/浴缸/流理台) -> ineligible
3. 石材類 -> ineligible
4. 數量門檻不足 -> ineligible
5. 裝潢廢料且 renovation_by=None -> needs_review + clarification_needed
   renovation_by="contractor" -> ineligible
   renovation_by="self" -> needs_review(清潔隊裁量)
6. 在收運清單內 -> eligible
7. 不在清單內 -> needs_review

★ 硬性要求:
- 不得 import ai,不得呼叫任何外部 API
- 純函式:同輸入永遠同輸出
- reasons 與 rule_refs 必須逐條可追溯到規則來源

【tests/test_eligibility.py】

至少涵蓋:
- 清單內品項 -> eligible
- 廢行李箱 2 只 -> ineligible,理由含「3 只」
- 廢行李箱 3 只 -> eligible
- 法人申請 -> ineligible
- 木板無施工方資訊 -> needs_review + clarification_needed 非空
- 木板 renovation_by=contractor -> ineligible
- 木板 renovation_by=self -> needs_review
- 石材類 -> ineligible
- 不明物體 -> needs_review

完成後回報:
- uv run pytest 的實際輸出
- grep -rn "import ai\|from ai" backend/services/ 的實際輸出(應為空)

然後停下來等我確認。
```

**這一階段的意義**:這是你回答「這不就是包一層 ChatGPT」的實體證據。跑得出測試,論述就成立。

---

## 階段三:屬性標記與距離(40 分鐘)

```
建立 services/attributes.py 與 services/distance.py。

【attributes.py】

依 spec.md §7 實作:
- annotate(item) -> ItemAttributes  查表,非推理
- annotate_all(items) -> list[WasteItem]  純函式,不修改輸入
- total_volume(items) -> float  載重計算的輸入
- resource_hint(items) -> str | None

屬性對照表放 data/rules.py 的 ITEM_ATTRIBUTES,
格式: 物品名 -> (重量級距, 最大尺寸cm, 可否拆解, 特殊處理, 容量單位)
至少涵蓋 spec 提到的收運品項。冰箱與冷氣標記「含冷媒設備,需特殊處理」。

★ 硬性要求:
- 區分「觀察」與「主張」:ItemAttributes 是事實,resource_hint 是建議
- 所有 resource_hint 文字必須含「系統建議」字樣,不得宣稱為規範要求
- 尺寸與重量為常識推估,在 rules.py 註解標明非官方規範

【distance.py】

get_matrix(locations, source=None) -> list[list[float]]
回傳兩兩之間的行車分鐘數矩陣。

source: "haversine" | "google" | "fixture";None 時依 DEMO_MODE 決定。

- _haversine_matrix(): 直線距離 × 1.35 修正,除以市區平均速率換算分鐘
- _from_fixture(): 讀 fixtures/distance_matrix.json
- _from_routes_api(): 先寫 NotImplementedError,自動退回 haversine

★ 為什麼先做 haversine:
排程演算法不在乎距離怎麼來的。先用假距離把邏輯跑通,
開發階段毫秒級可反覆測試、不燒配額。真實 API 留到最後接。

⚠️ _from_routes_api 的已知重點(實作時才需要):
1. X-Goog-FieldMask 是必填 HTTP header(不是 body),遺漏直接 400
2. 計費按元素數計算,30x30 = 900 元素,務必設每日上限
3. 實作後把結果存成 fixture,Demo 現場不要即時打

【tests/test_attributes.py】

至少涵蓋:
- 已知品項取得正確屬性
- 冰箱標記含冷媒
- 未知品項使用預設值
- 數量會等比放大 volume_units
- resource_hint 含「系統建議」
- 簡單品項無 hint
- annotate_all 不修改輸入

完成後回報 pytest 實際輸出。然後停下來等我確認。
```

---

## 階段四:排程核心(60 分鐘)

```
建立 services/scheduler.py。★ 本專案最重要的檔案。

範圍界定(不可擴張):
✅ 做:單一班次的路線排序(最近鄰居)+ 載重檢查 + 插入成本
❌ 不做:多車分派(VRP)、時間窗(VRPTW)
分區分組是「查表」不是演算法

需實作:

- DEPOT: 清潔隊駐地的固定座標
- order_route(cases, depot) -> (排序後案件, 總分鐘數)
  最近鄰居。相同距離時取索引較小者,確保確定性。
- build_shift(shift_id, district, date, cases, capacity_units) -> Shift
  排序後填入 Stop,計算每站 eta_minutes 與班次 used_units
- group_by_district(cases) -> dict[str, list[Case]]
  查表分組
- compute_insertion(shift, case) -> InsertionPlan   ★ Demo 核心
  對每個可能位置計算「插入後總時間 − 原本總時間」,取最小者。
  同時算插入後載重率,超過容量則 feasible=False
- apply_insertion(shift, case, position) -> Shift
  實際插入。只在班長點擊接受後呼叫。
- check_capacity(shift, case=None) -> dict
  回傳 current_units / projected_units / load_ratio / overloaded

★ 硬性要求:
- 不得 import ai
- 所有函式為純函式(apply_insertion 回傳新 Shift,不修改輸入)
- compute_insertion 的 feasible=False 是 agent 改變計畫的觸發點,
  這個欄位的語意不可改

【tests/test_scheduler.py】

至少涵蓋:
- 空案件清單
- 排序結果可重現(跑兩次結果相同)
- 最近鄰居真的選最近的
- build_shift 正確填入 seq 與 eta
- 載重未超過時 overloaded=False
- 載重超過時 overloaded=True
- 插入後超載時 feasible=False 且 resulting_load_ratio > 1.0
- 有餘裕時 feasible=True
- apply_insertion 後站數 +1、指定位置正確、used_units 增加
- group_by_district 正確分組

完成後回報 pytest 實際輸出。然後停下來等我確認。
```

**驗收重點**:「插入後超載 -> feasible=False」這個測試必須通過。它是 Demo 主線的技術基礎。

---

## 階段五:Demo 劇本資料(30 分鐘)

```
建立 fixtures/demo_cases.json 與 services/store.py。

【demo_cases.json】

依 spec.md §8.3 設計 28 筆案件,分佈於信義區、大安區、松山區。

★ 這是 Demo 劇本,不是隨機測資。必須刻意包含:
- 2-3 件含冷媒品項(冰箱、冷氣) -> 演特殊處理標記
- 1 件彈簧床墊 -> 演資源建議「2 人搬運」
- 1-2 件位置偏遠 -> 讓路線順序有明顯邏輯
- 1 件木板或類似裝潢廢料 -> 演 needs_review 與 agent 追問

檔案開頭加 _comment 與 _design 欄位,說明每筆劇本案件的用途。

同時定義 6 個班次(3 區 × 2 天),各含 capacity_units。

★ 關鍵調校:
信義區今日班次的 capacity_units 要設定成「起始載重約 92-95%」。
這樣現場再送一件彈簧床墊(容量單位約 3.0)就必定觸發超載,
才能演出「超載 -> 改排明日」這個核心爆點。

請先算出信義區案件的總容量單位,再回推 capacity_units 該設多少。
回報時附上實際算出的載重百分比。

【services/store.py】

記憶體儲存。刻意不用資料庫。

- load(): 從 fixture 載入案件、補上屬性、建立初始班次
- ensure_loaded()
- all_shifts() / get_shift(id) / put_shift(shift)
- today_shift(district) / next_day_shift(district)
- add_case(case) / get_case(id)
- pending_review() -> 回傳 needs_review 案件
- next_case_id()

完成後回報:
- 各班次的實際站數與載重百分比
- 確認信義區在 92-95% 之間

然後停下來等我確認。
```

**驗收重點**:信義區載重必須落在 92–95%。這個數字沒調對,你的 Demo 主線就演不出來。

---

## 階段六:Agent 工具與分派(50 分鐘)

```
建立 ai/tools.py、ai/orchestrator.py、ai/client.py、ai/prompts/。

【ai/tools.py】

依 Gemini Interactions API 格式定義 6 個 function declaration:

- check_eligibility(item_names, quantities, applicant_type?, renovation_by?)
- get_attributes(item_names, quantities?)
- compute_insertion(case_id, shift_id)
- check_capacity(shift_id, case_id?)
- query_shifts(district, when)        when: today | next_day
- ask_citizen(question, options, reason?)

★ description 要寫清楚「什麼時候該用」,特別是:
- check_capacity 的 description 要提到 overloaded=true 時應考慮查詢其他班次
- query_shifts 的 description 要提到「今日超載時用 next_day 查明日餘裕」
這是引導模型自主做出正確決策的關鍵,不是靠程式硬寫分支。

格式:
{"type": "function", "name": ..., "description": ...,
 "parameters": {"type": "object", "properties": {...}, "required": [...]}}

⚠️ Interactions API 已 GA,generateContent 已標為 legacy。
請先對照 https://ai.google.dev/gemini-api/docs/function-calling
確認格式。若與上述不符,直接指出,不要自行猜測參數名稱。

【ai/orchestrator.py】

execute(name, args) -> (結果 dict, TraceStep)

★ 這是 ai/ 與 services/ 的唯一橋樑。
   這一層不做任何判斷或計算,只轉發給 services/ 並把結果包成 TraceStep。

★ query_shifts 當 when="next_day" 時,產生的 TraceStep 必須 is_pivot=True,
   action 文字為「改為查詢明日班次」。這是 Demo 全場最重要的一行。

【ai/client.py】

Gemini 呼叫的唯一入口。其他檔案不得直接 import SDK。

- create(input_, tools, previous_id) -> interaction
- function_result(name, call_id, result) -> dict
- image_input(prompt, image_base64) -> list
- load_prompt(name, **kwargs)  從 ai/prompts/<name>.md 讀取

⚠️ load_prompt 用 str.format(),prompt 中除 {變數} 外不可有單獨花括號,
   JSON 範例請用雙花括號跳脫。

【ai/prompts/】

- classify.md  照片 -> 物品清單(JSON)
- agent.md     agent 的系統指示,說明工作原則
- narrate.md   排程結果 -> 白話說明

agent.md 的工作原則需包含:
1. 先確認資格再談排程
2. 資訊不足時追問,不要猜
3. 插入前必須檢查載重;overloaded 時不要硬塞,改查 next_day
4. 你負責決定呼叫什麼,不負責計算;不得修改工具回傳的數值

完成後回報:
- 各 tool 用假資料呼叫 orchestrator.execute 的實際輸出
- 確認 query_shifts(when="next_day") 產生的 TraceStep.is_pivot 為 True

然後停下來等我確認。
```

---

## 階段七:Agent 迴圈(50 分鐘)

```
建立 ai/agent.py。

兩條路徑:

【run_scripted(case)】先做這個

離線劇本。決策順序寫死,但走同一套 orchestrator 與 services,
所以畫面與正式路徑完全一致 —— 現場斷網也演得完。

順序:
分析照片 -> check_eligibility
  -> 若 clarification_needed: ask_citizen 後結束
  -> 若 ineligible: 結束
-> get_attributes
-> query_shifts(today)
-> compute_insertion
-> check_capacity
  -> 若 overloaded: query_shifts(next_day) -> compute_insertion

【run_llm(case)】再做這個

真正的 agent 迴圈:模型決定呼叫哪個 tool,執行後把結果餵回去。

- 用 client.create() 帶 tools 發起
- 取 interaction.steps,過濾 step.type == "function_call"
- 每個 call 取 .name / .arguments / .id,經 orchestrator 執行
- 用 client.function_result() 包裝結果,帶 previous_interaction_id 回傳
- MAX_TURNS 上限 8,避免無限迴圈
- 每個 tool call 都要產生 TraceStep

★ 硬性要求:
超載後改查明日,必須是模型自己決定的,不可用 if-else 硬寫在 run_llm 裡。
如果你發現模型不會自己這樣做,改進 tools.py 的 description 或 agent.md 的
工作原則,而不是在程式裡加分支。

【run(case)】

DEMO_MODE=true -> run_scripted
否則 -> run_llm,失敗時降級到 run_scripted

【summarize(trace, results)】

AI 不可用時的降級敘述。內容仍正確,只是不夠口語。

驗收:
- 送一件會超載的案件,貼出完整 trace,確認出現 is_pivot=true 的步驟
- DEMO_MODE=true 時完全不需網路,仍跑得出同樣的 trace

然後停下來等我確認。
```

**這是整個專案的關鍵驗收點**。如果 `run_llm` 跑不出 pivot,先檢查 tool description 寫得夠不夠清楚,不要退而在程式裡硬寫。

---

## 階段八:API 路由(30 分鐘)

```
建立 backend/main.py。

端點:
- GET  /api/health              回傳 demo_mode 狀態
- GET  /api/schedule            班次 + 待審佇列
- POST /api/cases               民眾送件,走完整 agent 流程
- POST /api/insertion/propose   對既有案件重算建議
- POST /api/insertion/accept    ★ 班長接受後才真正插入
- POST /api/reset               重置回劇本初始狀態(排練用)

要求:
- 統一用 ApiResponse 外殼包
- CORS 設定讀 config.CORS_ORIGINS
- 每個端點 try/except,失敗回傳 ok=False + error
- POST /api/cases 依 eligibility 狀態組出不同的 Message:
  needs_clarification -> 含 choices 區塊
  ineligible          -> 含拒絕原因與替代管道說明
  accepted            -> 含 result 卡 + 敘述 + resource_hint

影像辨識與 geocoding 先寫暫時實作(文字比對 / 行政區關鍵字對應),
標 TODO,不要卡在這裡。

完成後回報:
- 用 curl 打 /api/health 與 /api/schedule 的實際回應
- POST /api/cases 送出「彈簧床墊 @ 信義區」的完整回應,含 trace

然後停下來等我確認。
```

---

## 階段九:班長儀表板(60 分鐘)

```
建立前端儀表板頁面。資料來源 GET /api/schedule。

版面:
- 頂部:各班次載重進度條,超過 100% 紅色
- 主體:班次任務清單。每張卡片顯示
  站序 / 地址 / 物品 / 屬性標籤 / resource_hint(標為系統建議) / ETA
- 右側:Agent 決策軌跡面板,逐行動畫顯示 TraceStep
  ★ is_pivot=true 的步驟必須視覺強調(顏色、邊框、或動畫)
- 底部:待審佇列,顯示 needs_review 案件

★ 硬性要求:
- 不要引入任何新的前端套件
- 不要用互動式地圖。地圖用 Maps Static API 的 <img> 標籤即可
- API 失敗時顯示錯誤訊息,不可白畫面
- 決策軌跡不需 streaming,後端一次回傳陣列,前端逐行動畫顯示即可

完成後回報改動的檔案清單。然後停下來等我確認。
```

---

## 階段十:民眾端訊息流(40 分鐘 — 硬性上限)

```
建立民眾端頁面。

要求:
- 訊息流外觀,但輸入以點擊為主
- 依 MessageBlock.type 渲染: text / choices / upload / result
- choices 渲染成按鈕,點選後帶 answers 重新 POST /api/cases
- 自由輸入框可有,但非流程必要環節
- 與儀表板共用區塊渲染邏輯(抽成共用元件)

⚠️ 這個階段有 40 分鐘硬性上限。時間到就停,不要追求完美。
   民眾端在三分鐘 Demo 中只佔 30 秒。

完成後回報。
```

---

## 階段十一:接真實 API(可選,行有餘力才做)

```
兩件事,可獨立進行:

1. main.py 的 _classify() 改為呼叫 Gemini 視覺辨識
   - 經 ai/client.py,不直接 import SDK
   - prompt 用 ai/prompts/classify.md
   - 失敗時降級到文字比對

2. services/distance.py 的 _from_routes_api() 實作
   - 記得 X-Goog-FieldMask 是 header
   - 實作後跑一次,結果存成 fixtures/distance_matrix.json
   - 確認 DEMO_MODE=true 時讀 fixture 不打 API

驗收:pytest 仍全綠(測試用 haversine,不受影響)

若前面階段落後,直接跳過。Haversine 也演得完。
```

---

## 給 agent 的追問模板

進行中若覺得它偏離方向,這幾句很好用:

| 情況 | 說法 |
|---|---|
| 它自己加了東西 | 「AGENTS.md 的『刻意不做的事』有列到這項嗎?沒有的話請移除。」 |
| 判定邏輯跑進 AI | 「這個數字是誰算的?如果是 AI 算的,請搬到 services/。」 |
| 它想改 models.py | 「models.py 是契約,改動前請說明為什麼非改不可。」 |
| 它把三態簡化成二態 | 「needs_review 是刻意設計,對應法規裁量條款,不可移除。」 |
| 它硬寫超載後的分支 | 「這樣就不是 agent 了。要讓模型自己決定改查明日,請改進 tool description。」 |
| 它一次做太多 | 「請只完成當前階段,其餘等我確認。」 |
| 它宣稱完成 | 「請貼出驗證指令的實際輸出,不要只說通過。」 |
| 它編造規則數值 | 「這個數字來源是什麼?沒有來源請標 TODO,不要編。」 |
| 它想加資料庫 | 「狀態存記憶體就好。24 小時內資料庫是純成本。」 |

---

## 每階段的通用驗收

```bash
cd backend && DEMO_MODE=true uv run pytest      # 測試全綠
grep -rn "import ai\|from ai" backend/services/  # 應無輸出
```

第二條是架構鐵則的自動檢查。**任何一個階段跑出結果,就代表界線被跨越了,當場退回重做。**

---

## 進度落後時的砍功能順序

時間不夠時,照這個順序砍,不要憑感覺:

1. 階段十一(真實 API)——Haversine 與文字比對都演得完
2. 階段十(民眾端)——砍到只剩上傳框 + 結果卡
3. 待審佇列 UI ——口頭帶過即可
4. 靜態地圖 ——純清單也能演

**絕對不能砍的**:階段四(排程核心)、階段七的 pivot、階段九的決策軌跡面板。
這三個是你全部的差異化,少了任何一個,系統就退化成查詢工具。
