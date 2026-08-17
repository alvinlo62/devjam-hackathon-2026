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
from models import ApiResponse
from db.cloudsql import client as cloudsql_client

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


# 案件相關 endpoint（送件、排程、插入試算、接受建議）依 models.py 的
# SubmitCaseRequest/ScheduleResponse/ProposeInsertionRequest/AcceptInsertionRequest
# 陸續補在這裡；範例路由已移除，@limiter.limit(...) 用法參考 git 歷史裡的舊 /api/analyze。


# Cloud Run 用：Dockerfile 把 `frontend` build 出來的靜態檔放進 ./static。
# 本機用 `npm run dev` 開發時這個資料夾不存在，略過即可。
# 必須放在所有 /api 路由「之後」註冊，否則會攔截掉 API 請求。
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
