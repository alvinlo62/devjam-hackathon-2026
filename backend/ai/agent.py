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
from models import Case, CaseStatus, Eligibility, EligibilityResult, TraceStep, WasteItem

log = logging.getLogger(__name__)

MAX_TURNS = 8  # 對應 ADK RunConfig(max_llm_calls=...)，避免無限迴圈


def run_scripted(
    case: Case,
    renovation_by: str | None = None,
    applicant_type: str = "household",
) -> Case:
    """
    離線劇本。決策順序寫死，但呼叫的是跟 run_llm 完全相同的
    orchestrator.execute()，所以畫面（trace 的形狀）跟正式路徑一致。

    renovation_by：民眾回答完裝潢廢料追問後續答同一案件時帶入
    （見 main.py 的 POST /api/cases case_id 續答路徑），讓
    check_eligibility 這次能算出最終判定，不再卡在 clarification_needed。

    applicant_type：申請人身份（spec.md §6.2），跟 renovation_by 不同，
    這是送件當下就該有的輸入，不是 agent 反應式追問出來的——見
    models.SubmitCaseRequest.applicant_type、GET /api/applicant-types。
    """
    store.add_case(case)
    trace: list[TraceStep] = [_photo_analysis_step(case)]
    tool_results: dict[str, dict] = {}

    def call(name: str, args: dict) -> dict:
        result, step = orchestrator.execute(name, args)
        if name == "query_shifts":
            # is_pivot＝「這是這筆案件第二次查班次」，不分方向。
            # 民眾可以指定想要今日或明日，agent 第一次照民眾指定的查，
            # 這不算 pivot；只有查了第一次發現滿了、改查另一天，才是
            # agent 自己臨場調整計畫，這才是畫面上要標橘色強調的那一步。
            prior_queries = sum(1 for s in trace if s.tool == "query_shifts")
            step = step.model_copy(update={"is_pivot": prior_queries >= 1})
        trace.append(step)
        tool_results[name] = result
        return result

    item_names = [item.name for item in case.items]
    quantities = [item.quantity for item in case.items]

    elig_args = {
        "item_names": item_names,
        "quantities": quantities,
        "applicant_type": applicant_type,
    }
    if renovation_by:
        elig_args["renovation_by"] = renovation_by
    elig = call("check_eligibility", elig_args)

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
        # 民眾可以指定想要今日或明日收運（preferred_day），agent 先試
        # 民眾指定的那天；滿了再改查另一天——這是「先問民眾、查不到位才
        # 由 agent 自行調整」的順序，不是固定永遠先查今日。
        first_when = "next_day" if case.preferred_day == "tomorrow" else "today"
        second_when = "today" if first_when == "next_day" else "next_day"

        first = call("query_shifts", {"district": district, "when": first_when})

        if first.get("found"):
            call("compute_insertion", {"case_id": case.id, "shift_id": first["shift_id"]})
            capacity = call(
                "check_capacity", {"shift_id": first["shift_id"], "case_id": case.id}
            )

            if capacity["overloaded"]:
                second = call("query_shifts", {"district": district, "when": second_when})
                if second.get("found"):
                    call(
                        "compute_insertion",
                        {"case_id": case.id, "shift_id": second["shift_id"]},
                    )

    updates = _derive_case_updates(case, tool_results)
    # 注意：這裡不寫回 note——case.note 是民眾送件時附的補充說明
    # （SubmitCaseRequest.note），跟這裡算出來的處理結果是兩件事，
    # 寫回 note 會蓋掉民眾自己輸入的文字。給民眾看的排程結果文案由
    # main.py 的 _schedule_summary_text() 從 trace/store 另外組，
    # 不是逐條列出 trace（決策軌跡只在班長端顯示）。
    result = case.model_copy(update={**updates, "trace": trace})
    store.add_case(result)  # 存回處理完的版本，不是開頭那個還沒判定的版本
    return result


def run_llm(
    case: Case,
    renovation_by: str | None = None,
    applicant_type: str = "household",
) -> Case:
    """
    真正的 agent 迴圈，用 Google ADK 的 LlmAgent + Runner 執行。

    renovation_by：續答同一案件時帶入，併入給模型的案件摘要文字裡，
    模型看到之後應該會自己在呼叫 check_eligibility 時帶上這個答案
    （不是這裡幫模型決定要不要用，只是把民眾的回答如實告訴它）。

    applicant_type：申請人身份（spec.md §6.2），同樣併入案件摘要文字，
    由模型自己決定呼叫 check_eligibility 時帶上——這裡不幫模型判斷
    要不要用這個值，只是把資訊如實告訴它。

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
        # 工具呼叫記錄成 TraceStep——這裡沒有、也不需要知道「超載後該
        # 怎麼辦」，那是模型自己決定呼叫 query_shifts 的結果，不是這裡
        # 寫的規則。is_pivot 例外：判斷「這是不是這筆案件第二次查班次」
        # 純粹是計數，不是業務判斷，見 run_scripted 同一段註解。
        _, step = orchestrator.execute(tool.name, args)
        if tool.name == "query_shifts":
            prior_queries = sum(1 for s in trace if s.tool == "query_shifts")
            step = step.model_copy(update={"is_pivot": prior_queries >= 1})
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
            role="user",
            parts=[genai_types.Part(text=_case_summary_text(
                case, renovation_by=renovation_by, applicant_type=applicant_type,
            ))],
        ),
        run_config=RunConfig(max_llm_calls=MAX_TURNS),
    )

    for event in events:
        # ADK 失敗時不一定拋例外，而是把錯誤包進 Event（見對話記錄裡
        # 假 API key 的實測結果），要自己檢查、自己 raise，run() 的
        # try/except 降級機制才抓得到。
        if event.error_code:
            raise RuntimeError(f"ADK 執行失敗（{event.error_code}）：{event.error_message}")

    updates = _derive_case_updates(case, tool_results)
    # final_text（Gemini 生成的自然語言 narration）不寫回 case.note——
    # 那是民眾自己的補充說明欄位，見 run_scripted 同一段註解。民眾看到
    # 的排程結果由 main.py 的 _schedule_summary_text() 從 trace/store
    # 的結構化資料另外組，不需要靠這段自然語言文字。
    result = case.model_copy(update={**updates, "trace": trace})
    store.add_case(result)  # 存回處理完的版本，不是開頭那個還沒判定的版本
    return result


def run(
    case: Case,
    renovation_by: str | None = None,
    applicant_type: str = "household",
) -> tuple[Case, bool]:
    """
    DEMO_MODE=true -> run_scripted；否則嘗試 run_llm，失敗（沒 API key、
    網路異常、模型行為異常）時降級到 run_scripted，不讓整條流程中斷
    （AGENTS.md：每個 AI 任務都要有失敗時的 fixture 降級路徑）。

    renovation_by：續答裝潢廢料追問時帶入，見 run_scripted/run_llm 的說明。
    applicant_type：申請人身份，見 run_scripted/run_llm 的說明。
    回傳 (case, used_ai)，used_ai 標示這次是不是真的跑了 run_llm。
    """
    if config.DEMO_MODE:
        return run_scripted(case, renovation_by=renovation_by, applicant_type=applicant_type), False

    try:
        return run_llm(case, renovation_by=renovation_by, applicant_type=applicant_type), True
    except Exception:
        log.exception("run_llm 失敗，降級到 run_scripted")
        return run_scripted(case, renovation_by=renovation_by, applicant_type=applicant_type), False


def _derive_case_updates(case: Case, tool_results: dict[str, dict]) -> dict:
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
        # get_attributes 的工具結果是拿 item_names/quantities 重建的
        # WasteItem（orchestrator._items_from_args 裡 category 一律寫死
        # "未分類"），不能直接拿來蓋掉 case.items——那樣會把 classify_photo
        # 辨識出來的真實 category/confidence 洗掉。這裡只取每個位置算出來
        # 的 attributes，接回原本的 case.items，其餘欄位維持原樣。
        annotated = attrs_raw.get("items") or []
        if len(annotated) == len(case.items):
            updates["items"] = [
                item.model_copy(update={"attributes": WasteItem.model_validate(a).attributes})
                for item, a in zip(case.items, annotated)
            ]

    # tool_results 是 {工具名稱: 最後一次呼叫結果}，query_shifts 若被呼叫
    # 兩次（今日滿了改查明日），這裡自然拿到「最後、也是真正打算用」的
    # 那次結果，不用自己判斷要哪一次。
    qs_raw = tool_results.get("query_shifts")
    if qs_raw is not None and qs_raw.get("found"):
        updates["proposed_date"] = qs_raw["date"]

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


def _case_summary_text(
    case: Case,
    renovation_by: str | None = None,
    applicant_type: str = "household",
) -> str:
    items_text = "、".join(f"{item.name}×{item.quantity}" for item in case.items)
    extra = (
        f"\n民眾已回答裝潢廢料來源追問：renovation_by={renovation_by}"
        "（呼叫 check_eligibility 時請帶上這個答案）。"
        if renovation_by
        else ""
    )
    day_pref = (
        f"\n民眾指定的清運日偏好：preferred_day={case.preferred_day}"
        "（查詢班次時請先查這一天，滿了再改查另一天）。"
        if case.preferred_day
        else ""
    )
    return (
        f"新案件 {case.id}，地點：{case.location.district}（{case.location.address}）。\n"
        f"申報品項：{items_text}。申請人身份：applicant_type={applicant_type}"
        "（呼叫 check_eligibility 時請帶上這個值）。"
        f"{extra}{day_pref}\n"
        "請依你的工作原則處理這件案子，決定要呼叫哪些工具。"
    )