"""
Cloud SQL（PostgreSQL）連線的唯一入口。其他地方不要直接開連線或 import connector。
比照 ai/client.py 的角色：一個外部系統，一個進入點。

只提供連線池與 ping()，不含任何 schema／CRUD——資料表怎麼設計，等題目定案再說。
本機開發、DEMO_MODE 時不需要這支能動：config.DB_INSTANCE_CONNECTION_NAME 留空
就不會有任何地方呼叫到這裡。
"""
import logging
import threading

import sqlalchemy
from google.cloud.sql.connector import Connector, IPTypes

import config

log = logging.getLogger(__name__)

_engine: sqlalchemy.engine.Engine | None = None
_connector: Connector | None = None
_lock = threading.Lock()


def get_engine() -> sqlalchemy.engine.Engine:
    """回傳連線池（lazy singleton，double-checked locking）。

    沒鎖的話，冷啟動當下多個並發請求會同時通過 `_engine is None` 的檢查，
    各自建立一份 Connector——Connector() 會開背景 thread 跟實際連線，
    沒被用到的那幾份會被拋棄卻沒人呼叫 close()，永久漏掉 thread 跟連線。

    連線失敗直接讓例外往上拋，呼叫端自行決定要不要降級——這裡不吞例外，
    跟 ai/client.py 的 fallback 責任分離：那是 AI 呼叫失敗有 fixture 可退，
    DB 沒有對應的退路。
    """
    global _engine, _connector
    if _engine is None:
        with _lock:
            if _engine is None:
                _connector = Connector()

                def _getconn():
                    return _connector.connect(
                        config.DB_INSTANCE_CONNECTION_NAME,
                        "pg8000",
                        user=config.DB_USER,
                        password=config.DB_PASSWORD,
                        db=config.DB_NAME,
                        ip_type=IPTypes.PUBLIC,
                    )

                _engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=_getconn)
    return _engine


def ping() -> bool:
    """確認連得到 Cloud SQL，不代表任何 schema 已經存在。

    失敗時清掉快取的連線池，下一次呼叫會重新建立，不會永久卡在壞掉的
    連線上——例如冷啟動當下 IAM 權限傳播還沒完成導致第一次連線失敗，
    沒有這段的話這個 instance 之後每次 health check 都會一直回報
    unreachable，即使權限早就好了。
    """
    global _engine, _connector
    try:
        with get_engine().connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        return True
    except Exception:
        with _lock:
            if _connector is not None:
                _connector.close()
            _engine = None
            _connector = None
        raise