"""
Agent 迴圈與決策軌跡收集（spec.md §9）。

兩條路徑產生完全一樣形狀的結果（同一套 orchestrator/services、同一個
TraceStep 格式）：

- run_scripted：決策順序寫死，離線可跑，現場斷網照樣演得出決策軌跡。
- run_llm：改用 Google ADK（Agent Development Kit）的 LlmAgent + Runner
  跑真正的 agent 迴圈，模型自己決定要呼叫哪個工具，包括「超載後改查
  明日」這個關鍵決策點——這裡完全沒有 if-else 處理這件事，工具怎麼被
  呼叫、呼叫幾次、什麼時候結束都是 ADK 內部在跑，我們只用
  after_tool_callback side-effect 記錄每次呼叫的 TraceStep。如果模型
  不會自己做出正確決策，要去改 ai/tools.py 的 docstring 或
  ai/prompts/agent.md 的工作原則，不是在這裡加分支。
"""
import logging

import config
from ai import client, orchestrator, tools
from data import store
from models import Case, CaseStatus, Eligibility, EligibilityResult, TraceStep

log = logging.getLogger(__name__)

MAX_TURNS = 8  # 對應 ADK RunConfig(max_llm_calls=...)，避免無限迴圈


def run_scripted(case: Case) -> Case:
    """
    離線劇本。決策順序寫死，但呼叫的是跟 run_llm 完全相同的
    orchestrator.execute()，所以畫面（trace 的形狀）跟正式路徑一致。
    """
    store.add_case(case)
    trace: list[TraceStep] = [_photo_analysis_step(case)]
    tool_results: dict[str, dict] = {}

    def call(name: str, args: dict) -> dict:
        result, step = orchestrator.execute(name, args)
        trace.append(step)
        tool_results[name] = result
        return result

    item_names = [item.name for item in case.items]
    quantities = [item.quantity for item in case.items]

    elig = call("check_eligibility", {"item_names": item_names, "quantities": quantities})

    if elig["clarification_needed"]:
        # 目前 services/eligibility.py 唯一會觸發 clarification_needed 的
        # 路徑是裝潢廢料裁量條款（spec.md §6.3），所以這裡直接問這個問題；
        # 之後若規則新增其他需要追問的情境，這裡要跟著擴充。
        call("ask_citizen", {
            "question": "這是您自行拆除的，還是請廠商施工？",
            "options": [
                {"label": "自行拆除", "value": "self"},
                {"label": "委託廠商", "value": "contractor"},
            ],
            "reason": "偵測到疑似裝潢廢料，需要確認來源才能判斷資格",
        })
    elif elig["status"] == Eligibility.INELIGIBLE.value:
        pass  # 不符合資格，結束，不用再排程
    else:
        call("get_attributes", {"item_names": item_names, "quantities": quantities})

        district = case.location.district
        today = call("query_shifts", {"district": district, "when": "today"})

        if today.get("found"):
            call("compute_insertion", {"case_id": case.id, "shift_id": today["shift_id"]})
            capacity = call(
                "check_capacity", {"shift_id": today["shift_id"], "case_id": case.id}
            )

            if capacity["overloaded"]:
                next_day = call("query_shifts", {"district": district, "when": "next_day"})
                if next_day.get("found"):
                    call(
                        "compute_insertion",
                        {"case_id": case.id, "shift_id": next_day["shift_id"]},
                    )

    updates = _derive_case_updates(tool_results)
    note = summarize(trace, updates)
    return case.model_copy(update={**updates, "trace": trace, "note": note})


def run_llm(case: Case) -> Case:
    """
    真正的 agent 迴圈，用 Google ADK 的 LlmAgent + Runner 執行。

    ADK 的 tools 直接吃 ai/tools.py 的 Python 函式（框架自己讀 type hint
    跟 docstring 生成 schema），每次工具被呼叫後，after_tool_callback
    會拿到 (tool, args, tool_context, tool_response)，我們用它組
    TraceStep、附加進 trace——這是唯一攔截點，迴圈本身、要不要再呼叫下一
    個工具、什麼時候結束，全部是 ADK 內部邏輯，我們不插手也插不了手。

    ⚠️ 已用假 API key 實測過：request 真的會送到 Google 伺服器並收到
    結構化錯誤（見對話記錄），確認 ADK 用的是跟 ai/client.py 相同的
    google-genai SDK、讀同一個 GEMINI_API_KEY 環境變數，session
    /Runner 都有同步版本（create_session_sync / runner.run()），
    不需要 asyncio 橋接，維持專案「全部用 def，不用 async def」的慣例。
    """
    from google.adk.agents import LlmAgent
    from google.adk.agents.run_config import RunConfig
    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types

    store.add_case(case)
    trace: list[TraceStep] = [_photo_analysis_step(case)]
    tool_results: dict[str, dict] = {}

    def after_tool_callback(tool, args, tool_context, tool_response):
        # tool_context 沒用到，但 ADK 用關鍵字比對參數名稱呼叫 callback，
        # 這個參數名稱跟位置都是硬性規定，不能刪也不能改名（見官方文件）。
        # ★ 全場最重要的攔截點：不做任何判斷，只是把 ADK 已經執行完的
        # 工具呼叫記錄成 TraceStep。is_pivot 的邏輯完全在
        # orchestrator.execute() 裡（query_shifts when=next_day），
        # 這裡沒有、也不需要知道「超載後該怎麼辦」——那是模型自己決定
        # 呼叫 query_shifts 的結果，不是這裡寫的規則。
        _, step = orchestrator.execute(tool.name, args)
        trace.append(step)
        tool_results[tool.name] = tool_response
        return None  # 不修改工具結果，只是側面記錄

    agent = LlmAgent(
        name="waste_dispatch_agent",
        model=config.GEMINI_MODEL,
        instruction=client.load_prompt("agent"),
        tools=tools.TOOLS,
        after_tool_callback=after_tool_callback,
    )

    app_name = "waste_dispatch"
    runner = InMemoryRunner(agent=agent, app_name=app_name)
    session = runner.session_service.create_session_sync(app_name=app_name, user_id="citizen")

    events = runner.run(
        user_id="citizen",
        session_id=session.id,
        new_message=genai_types.Content(
            role="user", parts=[genai_types.Part(text=_case_summary_text(case))]
        ),
        run_config=RunConfig(max_llm_calls=MAX_TURNS),
    )

    final_text = None
    for event in events:
        # ADK 失敗時不一定拋例外，而是把錯誤包進 Event（見對話記錄裡
        # 假 API key 的實測結果），要自己檢查、自己 raise，run() 的
        # try/except 降級機制才抓得到。
        if event.error_code:
            raise RuntimeError(f"ADK 執行失敗（{event.error_code}）：{event.error_message}")
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text

    updates = _derive_case_updates(tool_results)
    note = final_text or summarize(trace, updates)
    return case.model_copy(update={**updates, "trace": trace, "note": note})


def run(case: Case) -> tuple[Case, bool]:
    """
    DEMO_MODE=true -> run_scripted；否則嘗試 run_llm，失敗（沒 API key、
    網路異常、模型行為異常）時降級到 run_scripted，不讓整條流程中斷
    （AGENTS.md：每個 AI 任務都要有失敗時的 fixture 降級路徑）。

    回傳 (case, used_ai)，used_ai 標示這次是不是真的跑了 run_llm。
    """
    if config.DEMO_MODE:
        return run_scripted(case), False

    try:
        return run_llm(case), True
    except Exception:
        log.exception("run_llm 失敗，降級到 run_scripted")
        return run_scripted(case), False


def summarize(trace: list[TraceStep], results: dict) -> str:
    """
    AI 不可用時的降級敘述。內容跟工具算出來的結果一樣正確，
    只是逐條列出 trace，不像 Gemini narrate 出來的那麼口語。
    """
    lines = [f"{step.action}{step.detail}" for step in trace]

    status = results.get("status")
    if status is not None:
        lines.append(f"最終狀態：{status.value if hasattr(status, 'value') else status}")

    resource_hint = results.get("resource_hint")
    if resource_hint:
        lines.append(resource_hint)

    return "\n".join(lines)


def _derive_case_updates(tool_results: dict[str, dict]) -> dict:
    """
    依累積的工具結果決定 Case 該更新哪些欄位。純粹讀取工具結果、不做
    判斷——判斷早就在 services/ 裡做完了，這裡只是把結果搬到 Case 上。

    eligible/needs_review 都先維持 CaseStatus.PENDING：插入建議是
    compute_insertion 算出來的，真正排進班次要等人工接受（spec.md
    §4.4），agent 只負責算與建議，不負責拍板。
    """
    updates: dict = {}

    elig_raw = tool_results.get("check_eligibility")
    if elig_raw is not None:
        eligibility_result = EligibilityResult.model_validate(elig_raw)
        updates["eligibility"] = eligibility_result
        updates["status"] = (
            CaseStatus.REJECTED
            if eligibility_result.status == Eligibility.INELIGIBLE
            else CaseStatus.PENDING
        )

    attrs_raw = tool_results.get("get_attributes")
    if attrs_raw is not None:
        updates["resource_hint"] = attrs_raw.get("resource_hint")

    return updates


def _photo_analysis_step(case: Case) -> TraceStep:
    """
    這裡沒有真的呼叫視覺模型：classify_item（照片→品項）不在這次的
    6 個 agent 工具裡（spec.md §9.2 把它列在 ai/，但不經過這套
    function calling 迴圈），Case.items 進來時已經是結構化資料。
    這一步只是把「已知的品項」整理成跟 spec.md §5.3 範例一致的
    第一行 trace，不是真的重新分析照片。
    """
    if not case.items:
        return TraceStep(icon="🔍", action="分析照片…", detail="未取得品項資料")
    summary = "、".join(f"{item.name}×{item.quantity}" for item in case.items)
    return TraceStep(icon="🔍", action="分析照片…", detail=f"辨識：{summary}")


def _case_summary_text(case: Case) -> str:
    items_text = "、".join(f"{item.name}×{item.quantity}" for item in case.items)
    return (
        f"新案件 {case.id}，地點：{case.location.district}（{case.location.address}）。\n"
        f"申報品項：{items_text}。\n"
        "請依你的工作原則處理這件案子，決定要呼叫哪些工具。"
    )