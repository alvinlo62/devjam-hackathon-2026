"""
Agent 可呼叫的工具（改寫成 ADK 版本）。

改版原因：ai/agent.py 的 run_llm() 從手刻 Gemini function-calling 迴圈
改用 Google ADK（Agent Development Kit）的 LlmAgent + Runner。ADK 的
tools 是直接吃 Python callable——框架自己讀函式的 type hint 跟 docstring
生成 schema，不用像之前那樣手寫 JSON Schema 字典。

docstring 是引導模型自主決策的關鍵，不是程式硬寫 if-else——特別是
「什麼時候該用」寫在 docstring 裡，模型才會在對的時機自己選對的工具
（見 check_capacity 與 query_shifts 的說明）。跟改版前的 description
文字內容一致，只是格式從 JSON 欄位換成 docstring。

實際執行邏輯仍然全部委派給 ai/orchestrator.py（ai/ 與 services/ 的
唯一橋樑），這裡只是薄薄一層 ADK 相容包裝：呼叫 orchestrator.execute()
取回 (result, TraceStep)，回傳 result 給模型。TraceStep 由
ai/agent.py 的 after_tool_callback 另外處理（見該檔案），不在這裡。
"""
from ai import orchestrator


def check_eligibility(
    item_names: list[str],
    quantities: list[int],
    applicant_type: str = "household",
    renovation_by: str = "",
) -> dict:
    """判定一批廢棄物品項是否符合大型廢棄物收運資格（三態：eligible /
    ineligible / needs_review）。收到新案件時應該最先呼叫這個工具——
    先確認資格，再談排程；資格未確認前不要呼叫 compute_insertion。
    回傳 needs_review 且 clarification_needed=true 時，代表規則需要
    額外資訊才能判斷（例如疑似裝潢廢料但不知道是自行拆除還是廠商施工），
    這時應該呼叫 ask_citizen 追問，不要自己假設答案。

    Args:
        item_names: 品項名稱清單，例如 ["彈簧床墊", "廢行李箱"]。
        quantities: 對應 item_names 每個品項的數量，兩個陣列長度必須一致。
        applicant_type: 申請人類型，預設 household（一般家庭及住戶）。
            住家兼營商業、機構、學校、部隊、法人等一律不符合收運資格。
        renovation_by: 只在已知答案時才提供："self" 代表民眾自行拆除
            （會進入待審佇列由清潔隊裁量），"contractor" 代表委託廠商施工
            （不符合收運資格）。不確定時留空，工具會回傳 needs_review
            並提示需要追問，不要猜。
    """
    args = {"item_names": item_names, "quantities": quantities, "applicant_type": applicant_type}
    if renovation_by:
        args["renovation_by"] = renovation_by
    result, _ = orchestrator.execute("check_eligibility", args)
    return result


def get_attributes(item_names: list[str], quantities: list[int]) -> dict:
    """查詢品項的客觀屬性（重量級距、最大尺寸、是否可拆解、是否需特殊處理，
    例如含冷媒設備）與系統參考的人力配置建議。這些是查表結果，不是規範
    要求，跟班長或民眾說明時要照工具回傳的文字講，不要自己加碼保證。

    Args:
        item_names: 品項名稱清單。
        quantities: 對應每個品項的數量，兩個陣列長度必須一致。
    """
    result, _ = orchestrator.execute(
        "get_attributes", {"item_names": item_names, "quantities": quantities}
    )
    return result


def compute_insertion(case_id: str, shift_id: str) -> dict:
    """計算把一筆案件插入某班次路線的最佳位置與成本（增加的行車分鐘數），
    同時算出插入後的預估載重率。呼叫前案件資格應該已經確認為 eligible。
    回傳的 feasible=false 代表插入後會超過本班次容量閾值——這時不要硬塞，
    改呼叫 query_shifts（when="next_day"）查詢明日班次是否有餘裕。

    Args:
        case_id: 要插入的案件 id。
        shift_id: 要插入的目標班次 id。
    """
    result, _ = orchestrator.execute(
        "compute_insertion", {"case_id": case_id, "shift_id": shift_id}
    )
    return result


def check_capacity(shift_id: str, case_id: str = "") -> dict:
    """查詢某班次目前的載重狀態；若提供 case_id，會一併算出插入該案件後的
    預估載重率。回傳的 overloaded=true 代表已經或即將超過本班次容量閾值，
    這時應該考慮改呼叫 query_shifts（when="next_day"）查詢同行政區明日
    班次是否有餘裕，而不是繼續在原班次硬塞或直接放棄這筆案件。

    Args:
        shift_id: 要查詢的班次 id。
        case_id: 選填。若提供，會計算插入這筆案件後的預估載重率。
    """
    args = {"shift_id": shift_id}
    if case_id:
        args["case_id"] = case_id
    result, _ = orchestrator.execute("check_capacity", args)
    return result


def query_shifts(district: str, when: str) -> dict:
    """查詢某行政區某一天的班次狀態（站數、載重率、是否超載）。
    when="today" 查今日班次；今日班次超載（check_capacity 回傳
    overloaded=true）時，改用 when="next_day" 查詢明日該區班次是否有餘裕
    可以容納——這是本系統遇到超載時的標準處理方式，不是失敗，是設計好的
    行為，不要因為今日超載就直接判案件不能收。

    Args:
        district: 行政區名稱，例如「信義區」。
        when: "today" 查今日班次，"next_day" 查明日班次，只能是這兩個值。
    """
    result, _ = orchestrator.execute("query_shifts", {"district": district, "when": when})
    return result


def ask_citizen(question: str, options: list[dict], reason: str = "") -> dict:
    """當資訊不足以判斷資格或屬性時，向民眾追問，不要用猜的——你的直覺對
    這個系統的規則常常是錯的（例如：兩只行李箱聽起來像大型廢棄物，但實際
    門檻是 3 只），不確定的事一律用工具查或用這個工具問，不要自己假設答案。
    民眾端輸入以點擊為主，盡量透過 options 提供選項，不要只丟開放式問題。

    Args:
        question: 要問民眾的問題，白話文。
        options: 提供給民眾點選的選項清單，每個元素是
            {"label": "顯示文字", "value": "對應的值"}。
        reason: 選填，說明為什麼需要這個資訊，讓民眾理解追問的原因。
    """
    args = {"question": question, "options": options}
    if reason:
        args["reason"] = reason
    result, _ = orchestrator.execute("ask_citizen", args)
    return result


TOOLS = [
    check_eligibility,
    get_attributes,
    compute_insertion,
    check_capacity,
    query_shifts,
    ask_citizen,
]