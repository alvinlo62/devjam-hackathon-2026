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
    Eligibility,
    Location,
    Message,
    MessageBlock,
    ProposeInsertionRequest,
    ProposeInsertionResponse,
    ScheduleResponse,
    SubmitCaseRequest,
    SubmitCaseResponse,
    WasteItem,
)
from services import scheduler

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
    if case.note:
        blocks.append(MessageBlock(type=BlockType.TEXT, content=case.note))
    if case.resource_hint:
        blocks.append(MessageBlock(type=BlockType.TEXT, content=case.resource_hint))
    return Message(role="agent", blocks=blocks)


@app.get("/api/schedule", response_model=ApiResponse)
def get_schedule():
    """班長儀表板：所有班次 + needs_review 待審佇列。"""
    try:
        data = ScheduleResponse(shifts=store.all_shifts(), pending_review=store.pending_review())
        return ApiResponse(data=data)
    except Exception as e:
        log.exception("get_schedule failed")
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
            case, _used_ai = agent.run(case, renovation_by=renovation_by)
        else:
            if req.image_base64:
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

            new_case = Case(id=store.next_case_id(), location=location, items=items, note=req.note)
            case, _used_ai = agent.run(new_case)

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

        new_shift = scheduler.apply_insertion(shift, case, req.position)
        store.put_shift(new_shift)

        # 插入的是今日班次還是明日班次（超載改查明日的情境），決定案件最終狀態。
        today = store.today_shift(shift.district)
        status = CaseStatus.SCHEDULED if today is not None and today.id == shift.id else CaseStatus.DEFERRED
        updated_case = case.model_copy(update={"status": status})
        store.add_case(updated_case)

        return ApiResponse(data={"shift": new_shift, "case": updated_case})
    except Exception as e:
        log.exception("accept_insertion failed")
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
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
