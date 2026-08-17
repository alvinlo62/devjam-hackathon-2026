"""
Agent 可呼叫的工具宣告（Gemini Interactions API 格式，function calling）。

格式已對照官方文件查證（2026-08-17）：
https://ai.google.dev/gemini-api/docs/function-calling
最外層需要 "type": "function"，parameters 用 JSON Schema
（type/properties/required），tools=[...] 直接傳一串這種 dict，
不需要額外包一層 function_declarations。

description 是引導模型自主決策的關鍵，不是程式硬寫 if-else——
特別是「什麼時候該用」這件事寫在 description 裡，模型才會在對的
時機自己選對的工具（見 check_capacity 與 query_shifts 的說明）。
實際執行邏輯不在這裡，這裡只有宣告；呼叫轉發見 ai/orchestrator.py。
"""

CHECK_ELIGIBILITY = {
    "type": "function",
    "name": "check_eligibility",
    "description": (
        "判定一批廢棄物品項是否符合大型廢棄物收運資格（三態：eligible / "
        "ineligible / needs_review）。收到新案件時應該最先呼叫這個工具——"
        "先確認資格，再談排程；資格未確認前不要呼叫 compute_insertion。"
        "回傳 needs_review 且 clarification_needed=true 時，代表規則需要"
        "額外資訊才能判斷（例如疑似裝潢廢料但不知道是自行拆除還是廠商施工），"
        "這時應該呼叫 ask_citizen 追問，不要自己假設答案。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "item_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "品項名稱清單，例如 [\"彈簧床墊\", \"廢行李箱\"]。",
            },
            "quantities": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "對應 item_names 每個品項的數量，兩個陣列長度必須一致。",
            },
            "applicant_type": {
                "type": "string",
                "description": (
                    "申請人類型，預設 household（一般家庭及住戶）。"
                    "住家兼營商業、機構、學校、部隊、法人等一律不符合收運資格。"
                ),
            },
            "renovation_by": {
                "type": "string",
                "enum": ["self", "contractor"],
                "description": (
                    "只在已知答案時才提供：品項若疑似裝潢廢料，self 代表民眾自行拆除"
                    "（會進入待審佇列由清潔隊裁量），contractor 代表委託廠商施工"
                    "（不符合收運資格，須另外委託合格清除業者）。不確定時不要猜，"
                    "省略此參數即可，工具會回傳 needs_review 並提示需要追問。"
                ),
            },
        },
        "required": ["item_names", "quantities"],
    },
}

GET_ATTRIBUTES = {
    "type": "function",
    "name": "get_attributes",
    "description": (
        "查詢品項的客觀屬性（重量級距、最大尺寸、是否可拆解、是否需特殊處理，"
        "例如含冷媒設備）與系統參考的人力配置建議。這些是查表結果，不是規範要求，"
        "跟班長或民眾說明時要照工具回傳的文字講，不要自己加碼保證。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "item_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "品項名稱清單。",
            },
            "quantities": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "對應每個品項的數量，省略時每項預設為 1。",
            },
        },
        "required": ["item_names"],
    },
}

COMPUTE_INSERTION = {
    "type": "function",
    "name": "compute_insertion",
    "description": (
        "計算把一筆案件插入某班次路線的最佳位置與成本（增加的行車分鐘數），"
        "同時算出插入後的預估載重率。呼叫前案件資格應該已經確認為 eligible。"
        "回傳的 feasible=false 代表插入後會超過本班次容量閾值——這時不要硬塞，"
        "改呼叫 query_shifts（when=\"next_day\"）查詢明日班次是否有餘裕。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "case_id": {"type": "string", "description": "要插入的案件 id。"},
            "shift_id": {"type": "string", "description": "要插入的目標班次 id。"},
        },
        "required": ["case_id", "shift_id"],
    },
}

CHECK_CAPACITY = {
    "type": "function",
    "name": "check_capacity",
    "description": (
        "查詢某班次目前的載重狀態；若提供 case_id，會一併算出插入該案件後的"
        "預估載重率。回傳的 overloaded=true 代表已經或即將超過本班次容量閾值，"
        "這時應該考慮改呼叫 query_shifts（when=\"next_day\"）查詢同行政區明日"
        "班次是否有餘裕，而不是繼續在原班次硬塞或直接放棄這筆案件。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "shift_id": {"type": "string", "description": "要查詢的班次 id。"},
            "case_id": {
                "type": "string",
                "description": "選填。若提供，會計算插入這筆案件後的預估載重率。",
            },
        },
        "required": ["shift_id"],
    },
}

QUERY_SHIFTS = {
    "type": "function",
    "name": "query_shifts",
    "description": (
        "查詢某行政區某一天的班次狀態（站數、載重率、是否超載）。"
        "when=\"today\" 查今日班次；今日班次超載（check_capacity 回傳 "
        "overloaded=true）時，改用 when=\"next_day\" 查詢明日該區班次是否有餘裕"
        "可以容納——這是本系統遇到超載時的標準處理方式，不是失敗，是設計好的"
        "行為，不要因為今日超載就直接判案件不能收。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "district": {"type": "string", "description": "行政區名稱，例如「信義區」。"},
            "when": {
                "type": "string",
                "enum": ["today", "next_day"],
                "description": "today 查今日班次，next_day 查明日班次。",
            },
        },
        "required": ["district", "when"],
    },
}

ASK_CITIZEN = {
    "type": "function",
    "name": "ask_citizen",
    "description": (
        "當資訊不足以判斷資格或屬性時，向民眾追問，不要用猜的——你的直覺對這個"
        "系統的規則常常是錯的（例如：兩只行李箱聽起來像大型廢棄物，但實際門檻"
        "是 3 只），不確定的事一律用工具查或用這個工具問，不要自己假設答案。"
        "民眾端輸入以點擊為主，盡量透過 options 提供選項，不要只丟開放式問題。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "要問民眾的問題，白話文。"},
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "選項顯示文字。"},
                        "value": {"type": "string", "description": "選項對應的值。"},
                    },
                    "required": ["label", "value"],
                },
                "description": "提供給民眾點選的選項清單。",
            },
            "reason": {
                "type": "string",
                "description": "選填，說明為什麼需要這個資訊，讓民眾理解追問的原因。",
            },
        },
        "required": ["question", "options"],
    },
}

TOOLS: list[dict] = [
    CHECK_ELIGIBILITY,
    GET_ATTRIBUTES,
    COMPUTE_INSERTION,
    CHECK_CAPACITY,
    QUERY_SHIFTS,
    ASK_CITIZEN,
]

TOOLS_BY_NAME: dict[str, dict] = {tool["name"]: tool for tool in TOOLS}