"""
Gemini 呼叫的唯一入口。其他地方不要直接 import SDK。
好處：換模型、加重試、切 DEMO_MODE 都只改這一支。

⚠️ SDK 套件名、模型字串、structured output 用法變動很快。
   比賽前務必到官方文件確認，不要照這份或任何教學文章直接抄。
"""
import base64
import json
import logging
import threading
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

import config

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_client = None
_lock = threading.Lock()


REQUEST_TIMEOUT_MS = 30_000  # 現場網路異常時避免請求無限卡住，讓 fallback 機制能發揮作用


def _get_client():
    """lazy singleton，double-checked locking。沒鎖的話冷啟動當下多個並發
    請求會各自建立一份 client，白做工（雖然不像 Cloud SQL 的 Connector 會漏
    背景 thread，但一樣沒必要）。"""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from google import genai  # 延遲載入，DEMO_MODE 時不需要 SDK
                from google.genai import types
                _client = genai.Client(
                    api_key=config.GEMINI_API_KEY,
                    http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
                )
    return _client


def generate_text(prompt: str, image_base64: str | None = None) -> str:
    """純文字輸出。"""
    parts: list = [prompt]
    if image_base64:
        parts.append(_image_part(image_base64))

    resp = _get_client().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=parts,
    )
    return resp.text


def generate_structured(
    prompt: str,
    schema: Type[T],
    image_base64: str | None = None,
) -> T:
    """
    結構化輸出：直接拿 Pydantic model 當 schema。
    這是整個模板最有價值的一招 —— 省掉解析自由文字的所有麻煩。
    """
    parts: list = [prompt]
    if image_base64:
        parts.append(_image_part(image_base64))

    resp = _get_client().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=parts,
        config={
            "response_mime_type": "application/json",
            "response_schema": schema,
        },
    )
    return schema.model_validate(json.loads(resp.text))


def _image_part(image_base64: str):
    from google.genai import types
    return types.Part.from_bytes(
        data=base64.b64decode(image_base64),
        mime_type="image/jpeg",
    )


def load_prompt(name: str, **kwargs) -> str:
    """
    從 ai/prompts/<name>.md 讀 prompt 並帶入變數。

    prompt 用 .md 而非 .txt：可以用標題、清單、程式碼區塊分段，
    在 GitHub 或編輯器裡直接有語法高亮，改起來比純文字檔清楚。
    """
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8").format(**kwargs)
