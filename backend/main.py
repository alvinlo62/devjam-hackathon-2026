"""
FastAPI 入口。endpoint 少於 6 個時不要拆 routers/。

啟動：uv run uvicorn main:app --reload --port 8000
文件：http://localhost:8000/docs
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import config
from ai import agent, classify
from data import rules, store
from db.cloudsql import client as cloudsql_client
from models import (
    AcceptInsertionRequest,
    ApiResponse,
    BlockType,
    Case,
    CaseStatus,
    Choice,
    ClassifyPhotoRequest,
    ClassifyPhotoResponse,
    Eligibility,
    Location,
    Message,
    MessageBlock,
    ProposeInsertionRequest,
    ProposeInsertionResponse,
    ReviewCaseRequest,
    ScheduleResponse,
    SubmitCaseRequest,
    SubmitCaseResponse,
    UpdateCaseStatusRequest,
    WasteItem,
)
from services import attributes, scheduler

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# AnyIO 預設同步 route handler（我們全部用 def，不用 async def）只給 40 個並發
# thread 額度，這個數字是 Python 生態的預設值，不是照這個服務的實際需求設的。
# 現場人數不確定（評審 + 可能的其他參賽者），把它調高，讓 Cloud Run 自己的
# --concurrency 才是真正決定規模上限的機制，不要被這個意外的天花板卡住。
THREAD_POOL_SIZE = 200


@asynccontextmanager
async def lifespan(app: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = THREAD_POOL_SIZE
    yield


app = FastAPI(title="Hackathon Template", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 網址是公開、無認證的（評審要用自己的裝置連），只擋 /api/analyze——
# 目的不是防駭客，是避免有人（不管故意或腳本迴圈）把共用的 Gemini 額度
# 榨乾，害其他人只能看到 fallback 示範資料。依 IP 計數，記憶體內、
# 沒有外部依賴，重啟就重置，黑客松 demo 這個規模夠用。
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content=ApiResponse(ok=False, error="請求太頻繁，請稍後再試").model_dump(),
    )


@app.get("/api/health")
def health():
    """第一件要跑通的事。前端接得到這支，環境就沒問題。"""
    db_status = None
    if config.DB_INSTANCE_CONNECTION_NAME:
        try:
            cloudsql_client.ping()
            db_status = "ok"
        except Exception:
            log.exception("db health check failed")
            db_status = "unreachable"

    return ApiResponse(
        data={"status": "ok", "demo_mode": config.DEMO_MODE, "db": db_status}
    )


# ---------- 民眾端追問的固定文案（目前規則唯一會觸發追問的情境，
# 見 services/eligibility.py 的裝潢廢料裁量條款）----------
_RENOVATION_QUESTION = "這是您自行拆除的，還是請廠商施工？"
_RENOVATION_OPTIONS = [
    Choice(label="自行拆除", value="self"),
    Choice(label="委託廠商", value="contractor"),
]


def _guess_district(text: str) -> str | None:
    """
    ⚠️ TODO：geocoding 的暫時實作。真正版本應該呼叫地理編碼服務把完整
    地址轉成行政區＋座標，這裡先用關鍵字比對，只找得出行政區名稱，
    抓不到座標（呼叫端要另外補一個預設點，見 submit_case）。
    """
    if not text:
        return None
    for district in rules.DEPOTS:
        if district in text:
            return district
    return None


def _guess_items_from_text(text: str) -> list[WasteItem]:
    """
    ⚠️ TODO：影像辨識的暫時實作。沒有照片時退回用文字比對抓品項名稱，
    準確度遠不如 ai/classify.py 的真實視覺辨識，只是讓沒有照片的請求
    不會直接卡死。Demo 前應該讓前端強制要求上傳照片，不要依賴這條路徑。
    """
    if not text:
        return []
    candidates = {name for names in rules.ACCEPTED_ITEMS.values() for name in names}
    candidates |= set(rules.ITEM_ALIASES.keys())

    # 長的先比對：避免「床墊」這種別名剛好是「彈簧床墊」的子字串，
    # 同一個東西被重複算成兩筆品項。
    matched_names: list[str] = []
    for name in sorted(candidates, key=len, reverse=True):
        if name in text and not any(name in longer for longer in matched_names):
            matched_names.append(name)

    found: list[WasteItem] = []
    for name in matched_names:
        canonical = rules.ITEM_ALIASES.get(name, name)
        category = next(
            (cat for cat, names in rules.ACCEPTED_ITEMS.items() if canonical in names),
            "未分類",
        )
        found.append(WasteItem(name=name, category=category, quantity=1))
    return found


def _find_pickup(case_id: str) -> dict | None:
    """案件目前排在哪個班次的第幾站（尚未排入任何班次時回傳 None）。"""
    for shift in store.all_shifts():
        for stop in shift.stops:
            if stop.case.id == case_id:
                return {
                    "district": shift.district,
                    "date": shift.date,
                    "seq": stop.seq,
                    "eta_minutes": stop.eta_minutes,
                }
    return None


_DAY_LABEL = {"today": "今日", "tomorrow": "明日"}


def _schedule_summary_text(case: Case) -> str | None:
    """
    給民眾看的排程結果白話文——不是決策軌跡。決策軌跡（分析照片、查詢
    班次這類 agent 內部過程）只在班長端顯示（見 CaseCard.showTrace、
    MessageBlock 的 trace 區塊），民眾只需要知道「排到哪一天」跟
    「是否跟原本指定的不同」，這裡直接讀 store/Case 的結構化資料組句子，
    不是把 trace 逐條轉成文字。

    兩種情況要分開講清楚（spec.md §4.4：agent 只建議，真正插入要人工
    接受）：
    - 已經被班長接受、真的排進路線了 → 用 _find_pickup 查到的站序講。
    - 還沒被接受，只是 agent 算出來打算排哪一天 → 用 case.proposed_date
      講，明講「將由清潔隊確認後排入路線」，不要講得像已經定案。
    """
    preferred_day = case.preferred_day or "today"

    pickup = _find_pickup(case.id)
    if pickup is not None:
        today = store.today_shift(pickup["district"])
        actual_day = "today" if today is not None and today.date == pickup["date"] else "tomorrow"
        if actual_day != preferred_day:
            return (
                f"您指定的{_DAY_LABEL[preferred_day]}班次已滿，"
                f"系統已改安排{_DAY_LABEL[actual_day]}（{pickup['date']}）收運，第 {pickup['seq']} 站。"
            )
        return f"已排入{_DAY_LABEL[actual_day]}（{pickup['date']}）收運，第 {pickup['seq']} 站。"

    if case.proposed_date is None:
        return None

    today = store.today_shift(case.location.district)
    actual_day = "today" if today is not None and today.date == case.proposed_date else "tomorrow"
    if actual_day != preferred_day:
        return (
            f"您指定的{_DAY_LABEL[preferred_day]}班次已滿，"
            f"系統建議改安排{_DAY_LABEL[actual_day]}（{case.proposed_date}）收運，"
            "將由清潔隊確認後排入路線。"
        )
    return f"系統建議安排於{_DAY_LABEL[actual_day]}（{case.proposed_date}）收運，將由清潔隊確認後排入路線。"


def _build_case_message(case: Case) -> Message:
    """依案件的資格判定結果，組出對應形狀的訊息（spec.md §3.1 區塊型態）。"""
    elig = case.eligibility
    blocks: list[MessageBlock] = []

    if elig is not None and elig.clarification_needed:
        blocks.append(MessageBlock(
            type=BlockType.CHOICES,
            question=_RENOVATION_QUESTION,
            options=_RENOVATION_OPTIONS,
        ))
        return Message(role="agent", blocks=blocks)

    if elig is not None and elig.status == Eligibility.INELIGIBLE:
        blocks.append(MessageBlock(type=BlockType.TEXT, content="\n".join(elig.reasons)))
        blocks.append(MessageBlock(type=BlockType.RESULT, case=case))
        return Message(role="agent", blocks=blocks)

    # accepted（eligible）或單純 needs_review（不需要追問，交清潔隊複核）
    blocks.append(MessageBlock(type=BlockType.RESULT, case=case))
    schedule_text = _schedule_summary_text(case)
    if schedule_text:
        blocks.append(MessageBlock(type=BlockType.TEXT, content=schedule_text))
    elif elig is not None and elig.status == Eligibility.NEEDS_REVIEW:
        blocks.append(MessageBlock(
            type=BlockType.TEXT,
            content="此案件需清潔隊人工複核，將由清潔隊另行通知收運安排。",
        ))
    if case.resource_hint:
        blocks.append(MessageBlock(type=BlockType.TEXT, content=case.resource_hint))
    return Message(role="agent", blocks=blocks)


@app.get("/api/applicant-types", response_model=ApiResponse)
def get_applicant_types():
    """
    申請人身份選項清單，民眾端送件畫面用來渲染點選按鈕（spec.md §6.2
    服務對象限一般家庭及住戶）。選項由後端提供、單一來源
    data.rules.EXCLUDED_APPLICANTS，前端不要自己寫死這份清單，
    以後規則表改了兩邊才不會兜不起來。
    """
    try:
        options = [{"label": "一般家庭及住戶", "value": "household"}] + [
            {"label": label, "value": code} for code, label in rules.EXCLUDED_APPLICANTS.items()
        ]
        return ApiResponse(data={"options": options})
    except Exception as e:
        log.exception("get_applicant_types failed")
        return ApiResponse(ok=False, error=str(e))


@app.get("/api/schedule", response_model=ApiResponse)
def get_schedule():
    """班長儀表板：所有班次 + needs_review 待審佇列 + 今日已完成。"""
    try:
        data = ScheduleResponse(
            shifts=store.all_shifts(),
            pending_review=store.pending_review(),
            completed=store.completed_cases(),
        )
        return ApiResponse(data=data)
    except Exception as e:
        log.exception("get_schedule failed")
        return ApiResponse(ok=False, error=str(e))


@app.post("/api/photo/classify", response_model=ApiResponse)
@limiter.limit("15/minute")
def classify_photo_preview(request: Request, req: ClassifyPhotoRequest):
    """
    民眾端「確認資料」頁面用：辨識照片＋查屬性（長度／重量級距／材質／
    可否拆解），純預覽，不建立案件、不判定資格、不寫入 store。真正送件
    時把這裡的 items 原封帶回 POST /api/cases（見 SubmitCaseRequest.items
    的說明），同一張照片不會被辨識兩次。
    """
    try:
        items = classify.classify_photo(req.image_base64)
        if not items:
            return ApiResponse(ok=False, error="看不出品項，請重新拍照")
        annotated = attributes.annotate_all(items)
        return ApiResponse(data=ClassifyPhotoResponse(items=annotated))
    except Exception as e:
        log.exception("classify_photo_preview failed")
        return ApiResponse(ok=False, error=str(e))


@app.post("/api/cases", response_model=ApiResponse)
@limiter.limit("15/minute")
def submit_case(request: Request, req: SubmitCaseRequest):
    """
    民眾送件，走完整 agent 流程（ai/agent.run()）。

    req.case_id 有值時是續答同一案件的追問（例如裝潢廢料來源），
    直接把答案帶回 agent.run() 重新判定，不是開新案件。
    """
    try:
        if req.case_id:
            case = store.get_case(req.case_id)
            if case is None:
                return ApiResponse(ok=False, error=f"找不到案件：{req.case_id}")
            renovation_by = req.answers.get("decoration_source")
            case, _used_ai = agent.run(
                case, renovation_by=renovation_by, applicant_type=req.applicant_type
            )
        else:
            if req.items:
                # 前端「確認資料」頁面已經呼叫過 POST /api/photo/classify，
                # 這裡直接用那次的結果，不重新辨識同一張照片（見
                # SubmitCaseRequest.items 的說明）。
                items = req.items
            elif req.image_base64:
                items = classify.classify_photo(req.image_base64)
            else:
                items = _guess_items_from_text(req.note or "")
            if not items:
                return ApiResponse(ok=False, error="看不出品項，請重新拍照或描述")

            location = req.location
            if location is None:
                district = _guess_district(req.note or "") or "信義區"
                depot = rules.DEPOTS.get(district, rules.DEFAULT_DEPOT)
                location = Location(
                    address=req.note or "地址未提供（暫時實作，待接 geocoding）",
                    district=district,
                    lat=depot.lat,
                    lng=depot.lng,
                )

            new_case = Case(
                id=store.next_case_id(),
                location=location,
                items=items,
                note=req.note,
                preferred_day=req.preferred_day,
            )
            case, _used_ai = agent.run(new_case, applicant_type=req.applicant_type)

        message = _build_case_message(case)
        return ApiResponse(data=SubmitCaseResponse(message=message, case=case))
    except Exception as e:
        log.exception("submit_case failed")
        return ApiResponse(ok=False, error=str(e))


@app.post("/api/insertion/propose", response_model=ApiResponse)
def propose_insertion(req: ProposeInsertionRequest):
    """對既有案件重算插入建議（不真的插入，見 spec.md §4.4）。"""
    try:
        case = store.get_case(req.case_id)
        if case is None:
            return ApiResponse(ok=False, error=f"找不到案件：{req.case_id}")
        shift = store.get_shift(req.shift_id)
        if shift is None:
            return ApiResponse(ok=False, error=f"找不到班次：{req.shift_id}")

        plan = scheduler.compute_insertion(shift, case)
        return ApiResponse(data=ProposeInsertionResponse(plan=plan, trace=[]))
    except Exception as e:
        log.exception("propose_insertion failed")
        return ApiResponse(ok=False, error=str(e))


@app.post("/api/insertion/accept", response_model=ApiResponse)
def accept_insertion(req: AcceptInsertionRequest):
    """
    ★ 班長接受建議後才真正插入（spec.md §4.4，人工接受、不全自動）。
    這裡才會真的呼叫 scheduler.apply_insertion() 改動 Shift.stops，
    agent 之前算出來的都只是建議，沒有這一步不會真的排進路線。
    """
    try:
        case = store.get_case(req.case_id)
        if case is None:
            return ApiResponse(ok=False, error=f"找不到案件：{req.case_id}")
        shift = store.get_shift(req.shift_id)
        if shift is None:
            return ApiResponse(ok=False, error=f"找不到班次：{req.shift_id}")

        # 狀態要先算好、包進 updated_case，再拿 updated_case（不是舊的
        # case）去插入班次——apply_insertion 會把傳進去的案件物件整份存進
        # Shift.stops[].case，如果先插入、事後才更新狀態，Shift.stops
        # 裡存的就會是插入當下那份舊狀態（pending）的快照，跟 store 裡
        # 真正的案件記錄從此不同步（班長端讀的正是 Shift.stops，會一直
        # 看到過期狀態，例如看不到「開始清運」按鈕）。
        today = store.today_shift(shift.district)
        status = CaseStatus.SCHEDULED if today is not None and today.id == shift.id else CaseStatus.DEFERRED
        updated_case = case.model_copy(update={"status": status})

        new_shift = scheduler.apply_insertion(shift, updated_case, req.position)
        store.put_shift(new_shift)
        store.add_case(updated_case)

        return ApiResponse(data={"shift": new_shift, "case": updated_case})
    except Exception as e:
        log.exception("accept_insertion failed")
        return ApiResponse(ok=False, error=str(e))


_MANUAL_CASE_STATUSES = {CaseStatus.COLLECTING, CaseStatus.COMPLETED}


@app.get("/api/cases/{case_id}", response_model=ApiResponse)
def get_case(case_id: str):
    """
    民眾端輪詢查詢單一案件狀態，用來同步進度（已送出/已排程/清運中/
    已完成），連同已排班次的預計清運時間與地點一起回傳（尚未排入
    任何班次時 pickup 是 None）。
    """
    try:
        case = store.get_case(case_id)
        if case is None:
            return ApiResponse(ok=False, error=f"找不到案件：{case_id}")

        return ApiResponse(data={"case": case, "pickup": _find_pickup(case_id)})
    except Exception as e:
        log.exception("get_case failed")
        return ApiResponse(ok=False, error=str(e))


@app.post("/api/cases/status", response_model=ApiResponse)
def update_case_status(req: UpdateCaseStatusRequest):
    """
    班長手動標記「開始清運」/「已收運」（每一站各自獨立標記，不是自動
    依日期/時間推斷）。只接受 collecting/completed，其餘狀態轉換各自有
    專屬流程，不透過這支通用改，避免繞過 check_eligibility/apply_insertion
    的既有規則。
    """
    try:
        if req.status not in _MANUAL_CASE_STATUSES:
            return ApiResponse(
                ok=False,
                error=f"這支 endpoint 只接受 collecting/completed，收到：{req.status.value}",
            )
        case = store.get_case(req.case_id)
        if case is None:
            return ApiResponse(ok=False, error=f"找不到案件：{req.case_id}")

        updated_case = case.model_copy(update={"status": req.status})
        store.add_case(updated_case)
        # 案件這時候通常已經排進某個班次的 Shift.stops 裡了（不然班長端
        # 看不到這一站、也點不到這個按鈕），那份嵌入的快照要一併同步，
        # 見 store.sync_case_in_shifts 的說明。
        store.sync_case_in_shifts(updated_case)
        return ApiResponse(data=updated_case)
    except Exception as e:
        log.exception("update_case_status failed")
        return ApiResponse(ok=False, error=str(e))


@app.post("/api/cases/review", response_model=ApiResponse)
def review_case(req: ReviewCaseRequest):
    """
    班長現場複核 needs_review 案件的最終決定。只處理目前確實是
    needs_review 的案件，避免誤觸已經有明確判定（eligible/ineligible）
    的案件——那些不是這支端點的職責範圍。

    這支端點刻意不走排程／插入路線那一套：needs_review 代表規則判不了、
    要由人現場判斷，判斷當下就是「收走了」或「不收」，是已經發生的事，
    不是「決定完再排一個未來班次」——所以 approved=True 直接把狀態設成
    COMPLETED（已收運，不會出現在路線表或圓餅圖統計裡，因為它從來就
    不是規劃中的站點），不會像一般 eligible 案件那樣先進「新案件待確認」
    等第二次人工接受插入。approved=False 改判 ineligible、狀態設成
    REJECTED，從待審佇列移除。
    """
    try:
        case = store.get_case(req.case_id)
        if case is None:
            return ApiResponse(ok=False, error=f"找不到案件：{req.case_id}")
        if case.eligibility is None or case.eligibility.status != Eligibility.NEEDS_REVIEW:
            return ApiResponse(ok=False, error="此案件目前不是待複核（needs_review）狀態")

        note_suffix = f"（{req.note}）" if req.note else ""
        if req.approved:
            reasons = [*case.eligibility.reasons, f"班長現場複核：確認可收運，當場完成收運{note_suffix}"]
            updated_eligibility = case.eligibility.model_copy(
                update={"status": Eligibility.ELIGIBLE, "reasons": reasons, "clarification_needed": False}
            )
            updated_case = case.model_copy(
                update={"eligibility": updated_eligibility, "status": CaseStatus.COMPLETED}
            )
        else:
            reasons = [*case.eligibility.reasons, f"班長現場複核：確認不可收運{note_suffix}"]
            updated_eligibility = case.eligibility.model_copy(
                update={"status": Eligibility.INELIGIBLE, "reasons": reasons, "clarification_needed": False}
            )
            updated_case = case.model_copy(
                update={"eligibility": updated_eligibility, "status": CaseStatus.REJECTED}
            )

        store.add_case(updated_case)
        store.sync_case_in_shifts(updated_case)
        return ApiResponse(data=updated_case)
    except Exception as e:
        log.exception("review_case failed")
        return ApiResponse(ok=False, error=str(e))


@app.post("/api/reset", response_model=ApiResponse)
def reset():
    """重置回 fixture 劇本的初始狀態（排練用，spec.md §8.3 的 28 筆預載案件）。"""
    try:
        store.load()
        return ApiResponse(data={"reset": True})
    except Exception as e:
        log.exception("reset failed")
        return ApiResponse(ok=False, error=str(e))


# Cloud Run 用：Dockerfile 把 `frontend` build 出來的靜態檔放進 ./static。
# 本機用 `npm run dev` 開發時這個資料夾不存在，略過即可。
# 必須放在所有 /api 路由「之後」註冊，否則會攔截掉 API 請求。
#
# SPAStaticFiles：純 StaticFiles(html=True) 只有精確對到根目錄或實際存在的
# index.html 才會回傳它，對 /dashboard 這種前端 client-side route 直接請求
# （重新整理、貼網址）會找不到對應檔案而回 404。這裡覆寫 get_response，
# 404 時 fallback 回 index.html，交給前端 main.jsx 自己判斷路徑該渲染哪一頁。
class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/", SPAStaticFiles(directory=_STATIC_DIR, html=True), name="static")
