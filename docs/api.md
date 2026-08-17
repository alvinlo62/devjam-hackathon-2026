# API 契約

> 第 1 小時定案。改這份 = 前後端都要改，成本最高。
> 後端改 `models.py` 後，記得同步更新這裡。

所有回應統一外殼：

```json
{ "ok": true, "data": { }, "error": null }
```

---

## GET /api/health

環境檢查。前端接得到這支，代表 CORS / proxy / 埠號都沒問題。

```json
{ "ok": true, "data": { "status": "ok", "demo_mode": false, "db": null } }
```

`db` 欄位只有設定 `CLOUD_SQL_CONFIG` 時才會實際檢查連線：`"ok"` 表示連得到 Cloud SQL、
`"unreachable"` 表示連不到、`null` 表示沒設定 Cloud SQL（本機開發預設如此）。

## POST /api/analyze

主流程。

**Request**

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| text | string | 否 | 文字輸入 |
| image_base64 | string | 否 | 純 base64，不含 `data:` 前綴 |
| options | object | 否 | 額外參數 |

**Response `data`**

| 欄位 | 型別 | 說明 |
|---|---|---|
| results | array | 判定結果清單 |
| summary | string | AI 生成的白話說明 |
| used_fixture | boolean | 是否為示範資料 |

`results[]` 每一筆：

| 欄位 | 型別 | 說明 |
|---|---|---|
| item | object | 抽取出的原始項目 |
| status | `pass` \| `warn` \| `fail` | 判定結果 |
| score | number | 分數 |
| reasons | string[] | 判定依據，逐條可追溯 |
| gap | string \| null | 「差一點」提醒 |
