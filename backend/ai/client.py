"""
Gemini 呼叫的唯一入口。其他地方不要直接 import SDK。
好處：換模型、加重試、切 DEMO_MODE 都只改這一支。

⚠️ Interactions API 已 GA，generateContent 已列為 legacy，本檔案改用
   client.interactions.create()。格式已對照官方文件查證（2026-08-17）：
   - function calling 格式：https://ai.google.dev/gemini-api/docs/function-calling
   - 圖片輸入格式：https://ai.google.dev/gemini-api/docs/interactions/image-understanding
   - output_text 等基本用法：https://ai.google.dev/gemini-api/docs/interactions/text-generation

   模型字串三份官方文件寫的不一樣（gemini-3.5-flash / gemini-3.7-flash，
   spec.md 猜的是 gemini-3.6-flash），無法從文件本身判斷哪個是實際可用的，
   config.GEMINI_MODEL 的值務必在比賽前用你自己的 API key 實測確認。
"""
import json
import logging
import threading
from pathlib import Path
from typing import Any

import config

log = logging.getLogger(__name__)

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


def create(
    input_: str | list[dict],
    tools: list[dict] | None = None,
    previous_id: str | None = None,
):
    """
    呼叫 Interactions API，回傳 interaction 物件。

    input_：純字串，或 [{"type": "text", ...}, {"type": "image", ...},
    {"type": "function_result", ...}] 這類 content part 清單（多輪帶工具
    結果時用）。
    tools：ai/tools.py 的 function declaration 清單，見該檔案格式。
    previous_id：延續前一輪對話時帶入，對應 previous_interaction_id。

    回傳的 interaction.output_text 是最終文字；interaction.steps 裡
    type == "function_call" 的項目要取 .name / .arguments / .id
    （.id 就是回覆時要帶的 call_id）。
    """
    kwargs: dict[str, Any] = {"model": config.GEMINI_MODEL, "input": input_}
    if tools:
        kwargs["tools"] = tools
    if previous_id:
        kwargs["previous_interaction_id"] = previous_id
    return _get_client().interactions.create(**kwargs)


def function_result(name: str, call_id: str, result: Any) -> dict:
    """
    把工具執行結果（見 ai/orchestrator.py）包成 Interactions API 要的
    function_result content part，放進下一輪 create() 的 input_ 裡。
    """
    return {
        "type": "function_result",
        "name": name,
        "call_id": call_id,
        "result": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
    }


def image_input(prompt: str, image_base64: str) -> list[dict]:
    """組成帶圖片的 input（inline base64，不需要先用 Files API 上傳）。"""
    return [
        {"type": "text", "text": prompt},
        {"type": "image", "data": image_base64, "mime_type": "image/jpeg"},
    ]


def load_prompt(name: str, **kwargs) -> str:
    """
    從 ai/prompts/<name>.md 讀 prompt 並帶入變數。

    prompt 用 .md 而非 .txt：可以用標題、清單、程式碼區塊分段，
    在 GitHub 或編輯器裡直接有語法高亮，改起來比純文字檔清楚。
    """
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8").format(**kwargs)
