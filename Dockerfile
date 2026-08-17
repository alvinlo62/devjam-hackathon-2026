# Cloud Run 部署用。單一 image：前端 build 成靜態檔，由 FastAPI 一起 serve，
# 同源不用處理 CORS，評審只需要記一個網址。
#
# 本機開發不需要這支，繼續照 README 分開跑 uvicorn / vite dev 即可。

# ---- 1. build 前端 ----
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend

# Vite 的 VITE_* 變數是 build 當下就烤進打包好的 JS 檔案，不是執行期讀的，
# 所以不能像後端那樣用 Cloud Run 的 --set-env-vars 解決，一定要在這裡當
# build argument 傳進來（見部署指令的 --build-arg）。.dockerignore 排除了
# .env，這裡也不會意外把本機的 .env 檔案內容帶進 image。
ARG VITE_GOOGLE_MAPS_API_KEY
ENV VITE_GOOGLE_MAPS_API_KEY=${VITE_GOOGLE_MAPS_API_KEY}

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. 準備後端 + 裝入前端靜態檔 ----
FROM python:3.12-slim AS backend
WORKDIR /app

RUN pip install --no-cache-dir uv

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./
COPY --from=frontend-build /app/frontend/dist ./static

# 直接用 build time 裝好的 venv，不要在 CMD 用 `uv run`——
# `uv run` 啟動時會照 lockfile 做隱性 sync（含 dev group），
# 等於每次 container 冷啟動都多一次網路呼叫去裝 pytest 等開發套件，
# 實測會拖慢 cold start，PyPI 連不到時甚至會讓 container 起不來。
ENV PATH="/app/.venv/bin:$PATH"

# Cloud Run 會注入 PORT（預設 8080），一定要監聽 0.0.0.0
ENV PORT=8080
EXPOSE 8080

# --forwarded-allow-ips='*'：Cloud Run 的請求是透過它自己受信任的內部 proxy
# 轉發進來，預設值只信任 127.0.0.1，導致 X-Forwarded-For 不會被採信，
# request.client.host 對所有使用者都會落到同一個內部位址——直接影響
# main.py 裡 rate limit 依 IP 分桶的正確性。這裡信任所有來源是合理的，
# 因為容器對外沒有開放其他進入點，唯一的連線來源就是 Cloud Run 本身。
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --forwarded-allow-ips='*'"]
