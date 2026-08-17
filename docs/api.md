# API 契約

> 這份文件跟著 `backend/models.py` 走，改 `models.py` 後記得同步更新這裡。
> 上一版還在寫舊模板的 `/api/analyze`（通用範例路由），早就被階段一的
> 骨架清理刪掉了，這次是重寫，不是修補。

所有回應統一外殼（`models.ApiResponse`）：

```json
{ "ok": true, "data": { }, "error": null }
```

失敗時 `ok: false`，`error` 是白話錯誤訊息，`data` 是 `null`。

---

## GET /api/health

環境檢查。前端接得到這支，代表 CORS / proxy / 埠號都沒問題。

```json
{ "ok": true, "data": { "status": "ok", "demo_mode": false, "db": null } }
```

`db` 只有設定 `CLOUD_SQL_CONFIG` 時才會實際檢查連線：`"ok"` 連得到、
`"unreachable"` 連不到、`null` 沒設定（本機開發預設如此）。

---

## GET /api/schedule

班長儀表板：所有班次 + `needs_review` 待審佇列。

**Response `data`**（`models.ScheduleResponse`）

| 欄位 | 型別 | 說明 |
|---|---|---|
| shifts | `Shift[]` | 見下方 Shift 型別 |
| pending_review | `Case[]` | `needs_review` 狀態的案件，交班長裁量 |

**`Shift`**

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | string | 例如 `xinyi-today` |
| district | string | 行政區 |
| date | string | `YYYY-MM-DD` |
| capacity_units | number | 班次容量 |
| used_units | number | 目前已用容量 |
| load_ratio | number | `used_units / capacity_units`，後端算好直接給，不用前端重算 |
| overloaded | boolean | `load_ratio > 1.0` |
| total_minutes | number | 整條路線總行車時間 |
| stops | `Stop[]` | 依序排列，第一筆是第 1 站 |

**`Stop`**

| 欄位 | 型別 | 說明 |
|---|---|---|
| seq | integer | 站序，從 1 開始 |
| case | `Case` | 見下方 Case 型別 |
| eta_minutes | number | 從駐地出發累計到這站的行車分鐘數 |

---

## GET /api/applicant-types

申請人身份選項清單，`POST /api/cases` 的 `applicant_type` 欄位要用。
選項由後端提供（單一來源 `data.rules.EXCLUDED_APPLICANTS`），前端不要
自己寫死這份清單，規則表改了兩邊才不會兜不起來。

**Response `data`**

```json
{
  "options": [
    { "label": "一般家庭及住戶", "value": "household" },
    { "label": "住家兼營商業", "value": "commercial_household" },
    { "label": "機構", "value": "institution" },
    { "label": "學校", "value": "school" },
    { "label": "部隊", "value": "military" },
    { "label": "法人", "value": "corporate" }
  ]
}
```

---

## POST /api/cases

民眾送件，走完整 agent 流程（`ai/agent.run()`）。

**Request**（`models.SubmitCaseRequest`）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| case_id | string \| null | 否 | 有值＝續答同一案件的追問（見下）；`null`＝開新案件 |
| image_base64 | string \| null | 否 | 純 base64，不含 `data:` 前綴，走真實視覺辨識（`ai/classify.py`） |
| location | `Location` \| null | 否 | 有值就用；沒有時退回「geocoding 暫時實作」（行政區關鍵字比對 + 該區駐地座標），⚠️ 準確度不足，Demo 前應強制前端提供 |
| note | string \| null | 否 | 補充說明；沒有 `image_base64` 時，也會拿這欄位跑「文字比對」抓品項名稱（⚠️ 暫時實作，準確度遠不如照片辨識） |
| answers | object | 否 | 續答用，目前唯一用得到的 key 是 `decoration_source`，值是 `"self"` 或 `"contractor"` |
| applicant_type | string | 否 | 申請人身份，選項見 `GET /api/applicant-types`。預設 `"household"`——這是「前端沒送這欄位時」的備援值，不是強制值，前端應該讓民眾實際點選後再送出 |

**`Location`**：`{ address, district, lat, lng }`

**Response `data`**（`models.SubmitCaseResponse`）

| 欄位 | 型別 | 說明 |
|---|---|---|
| message | `Message` | 見下方，依判定結果組出不同區塊 |
| case | `Case` \| null | 這次處理完的案件 |

**`Message`**：`{ role: "agent", blocks: MessageBlock[] }`

**`MessageBlock`**（`type` 決定哪些欄位有值，見 `models.BlockType`）

| type | 用到的欄位 | 情境 |
|---|---|---|
| `choices` | question, options | 資格判定回傳 `clarification_needed=true`（目前唯一觸發情境：疑似裝潢廢料），前端要讓民眾點選，然後帶著 `case_id` + `answers.decoration_source` 再打一次 `/api/cases` |
| `text` | content | ineligible 時的拒絕原因；或案件的 `note`/`resource_hint` |
| `result` | case | 附上完整案件卡片 |

**`Case`**

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | string | |
| location | `Location` | |
| items | `WasteItem[]` | |
| eligibility | `EligibilityResult` \| null | |
| status | `CaseStatus` | `pending`\|`scheduled`\|`deferred`\|`rejected`\|`collecting`\|`completed`（見下） |
| resource_hint | string \| null | 系統參考的人力/處理建議，不是規範 |
| note | string \| null | agent 的白話說明（有真模型時是它自己生的最終回覆，離線時是逐條拼接） |
| created_at | string (ISO datetime) | |
| trace | `TraceStep[]` | 決策軌跡，`is_pivot=true` 標出「超載→改查明日」這類關鍵決策 |

**`WasteItem`**：`{ name, category, quantity, confidence, attributes }`，`attributes` 是 `{ weight_band, max_dimension_cm, dismantlable, special_handling, volume_units }` 或 `null`

**`EligibilityResult`**：`{ status, reasons, rule_refs, clarification_needed, items }`；`status` 是 `eligible`\|`ineligible`\|`needs_review`；**`rule_refs` 是內部除錯用，不要顯示給使用者**，畫面上只用 `reasons`

**`TraceStep`**：`{ icon, action, detail, tool, is_pivot }`

**`CaseStatus` 完整生命週期**：

```
pending → scheduled（班長接受插入）→ collecting（開始清運）→ completed（已收運）
        → deferred（超載改排明日，接受插入時判定）
        → rejected（ineligible）
```

`collecting`/`completed` 只能透過 `POST /api/cases/status` 由班長手動標記，
`scheduled`/`deferred` 只能透過 `POST /api/insertion/accept`，兩者不能互相取代。

---

## POST /api/insertion/propose

對既有案件重算插入建議，**不會真的插入**（純試算，供班長參考）。

**Request**（`models.ProposeInsertionRequest`）：`{ case_id, shift_id }`

**Response `data`**（`models.ProposeInsertionResponse`）

| 欄位 | 型別 | 說明 |
|---|---|---|
| plan | `InsertionPlan` | 見下 |
| trace | `TraceStep[]` | 目前固定回傳 `[]`，這支沒有另外收集 trace |

**`InsertionPlan`**：`{ shift_id, position, added_minutes, resulting_load_ratio, feasible, reason }`
`position` 是「插入在第幾站之後」，0 代表插在駐地之後、成為新的第一站。

---

## POST /api/insertion/accept

★ 班長接受建議後才真正插入，這支才會真的改動 `Shift.stops`。

**Request**（`models.AcceptInsertionRequest`）：`{ case_id, shift_id, position }`

**Response `data`**（raw dict，沒有對應的 pydantic model）

| 欄位 | 型別 | 說明 |
|---|---|---|
| shift | `Shift` | 插入後的新班次 |
| case | `Case` | `status` 已更新成 `scheduled`（插的是今日班次）或 `deferred`（插的是明日班次） |

---

## GET /api/cases/{case_id}

民眾端輪詢查詢單一案件狀態，用來同步進度（已送出/已排程/清運中/已完成）。

**Response `data`**（raw dict）

| 欄位 | 型別 | 說明 |
|---|---|---|
| case | `Case` | 找不到時整支回應是 `ok: false` |
| pickup | object \| null | 已排入某班次時給 `{ district, date, seq, eta_minutes }`；還在待審佇列或尚未排程則是 `null` |

---

## POST /api/cases/status

班長手動標記「開始清運」/「已收運」，每一站各自獨立標記。

**Request**（`models.UpdateCaseStatusRequest`）：`{ case_id, status }`
`status` **只接受** `"collecting"` 或 `"completed"`，其他值會回 `ok: false`（其餘狀態轉換各自有專屬 endpoint，不走這支）。

**Response `data`**：更新後的 `Case`。

---

## POST /api/reset

重置回 `fixtures/demo_cases.json` 劇本的初始狀態（排練用）。

**Response `data`**：`{ "reset": true }`