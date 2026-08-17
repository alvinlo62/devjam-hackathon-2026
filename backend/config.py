"""集中管理環境變數。不要在其他檔案直接讀 os.environ。"""
import json
import logging
import os
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

# DEMO_MODE=true 時，AI 層改讀 fixtures，完全不呼叫外部 API。
# 現場網路異常、額度用完或 API 變慢時的保命開關。
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

# Cloud SQL（PostgreSQL）連線設定，整包存在一個 Secret Manager secret（JSON 格式）：
# {"instance_connection_name": "PROJECT:REGION:INSTANCE", "db_name": "...", "db_user": "...", "db_password": "..."}
# 本機開發不需要填，留空時 db/cloudsql/client.py 不會被呼叫。
# 格式錯誤時退回空字典（等同沒設定），不要讓整個 app 連 Gemini 相關功能
# 都因為一個 DB secret 格式打錯而起不來。
try:
    _CLOUD_SQL_CONFIG = json.loads(os.getenv("CLOUD_SQL_CONFIG", "{}"))
except json.JSONDecodeError:
    log.warning("CLOUD_SQL_CONFIG 不是合法 JSON，DB 功能停用")
    _CLOUD_SQL_CONFIG = {}
DB_INSTANCE_CONNECTION_NAME = _CLOUD_SQL_CONFIG.get("instance_connection_name", "")
DB_NAME = _CLOUD_SQL_CONFIG.get("db_name", "")
DB_USER = _CLOUD_SQL_CONFIG.get("db_user", "")
DB_PASSWORD = _CLOUD_SQL_CONFIG.get("db_password", "")
