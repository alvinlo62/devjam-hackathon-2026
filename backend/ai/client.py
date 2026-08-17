"""
Gemini 呼叫的唯一入口。其他地方不要直接 import SDK。
好處：換模型、加重試、切 DEMO_MODE 都只改這一支。

⚠️ ai/agent.py 的 run_llm()（真正的 agent 迴圈）已改用 Google ADK
   （google.adk）的 LlmAgent + Runner，不再呼叫這裡的 create()。
   這支檔案現在的用途縮小成：agent 迴圈以外、直接呼叫 Gemini 的場合
   （例如 classify_item 照片辨識，屬於 spec.md §9.2 講的「不經過
   function calling」的獨立 ai/ 呼叫）。load_prompt() 仍是 agent.py
   讀 ai/prompts/*.md 的入口，繼續共用。

⚠️ create()（Interactions API）跟 generate()（generate_content）並存，
   不要看到 generate_content 是 legacy 就以為都該用 create()：
   Interactions API 的賣點是 previous_interaction_id 多輪狀態接續，
   ai/classify.py 這種單次呼叫（送一次、拿一次結果，沒有第二輪）用不到
   這個能力，該用 generate()。agent 迴圈的多輪狀態則是 ADK 框架自己在
   管（見 ai/agent.py），也不是靠 Interactions API 的伺服器端狀態。
   目前專案裡沒有真的需要 Interactions API 狀態接續能力的地方，
   create() 先留著備用。改用 generate() 還有個實際好處：Interactions
   API 在 Vertex AI 這條路徑上模型支援範圍窄很多（實測只有
   gemini-3-flash-preview 通），generate_content 廣得多。

⚠️ Interactions API 已 GA，generateContent 已列為 legacy，本檔案改用
   client.interactions.create()。格式已對照官方文件查證（2026-08-17）：
   - function calling 格式：https://ai.google.dev/gemini-api/docs/function-calling
   - 圖片輸入格式：https://ai.google.dev/gemini-api/docs/interactions/image-understanding
   - output_text 等基本用法：https://ai.google.dev/gemini-api/docs/interactions/text-generation

   模型字串三份官方文件寫的不一樣（gemini-3.5-flash / gemini-3.7-flash，
   spec.md 猜的是 gemini-3.6-flash），無法從文件本身判斷哪個是實際可用的，
   config.GEMINI_MODEL 的值務必在比賽前用你自己的 API key 實測確認。
"""
import base64
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
    """
    lazy singleton，double-checked locking。沒鎖的話冷啟動當下多個並發
    請求會各自建立一份 client，白做工（雖然不像 Cloud SQL 的 Connector 會漏
    背景 thread，但一樣沒必要）。

    支援兩種驗證方式：
    - 一般 API key（GEMINI_API_KEY 有值時）
    - ADC / Vertex AI（組織禁用 API key 時，例如賽事方發的 GCP 帳號）：
      GEMINI_API_KEY 留空，改在 .env 設 GOOGLE_GENAI_USE_VERTEXAI=true、
      GOOGLE_CLOUD_PROJECT、GOOGLE_CLOUD_LOCATION，本機先跑過
      `setup_adc.sh` 產生憑證。這裡刻意不主動傳 api_key/vertexai/
      project/location 給 genai.Client()（api_key 只在有值時才傳）——
      SDK 自己會讀這些環境變數判斷要用哪種模式，我們手動判斷反而容易
      跟 SDK 內部的判斷順序兜不起來（已直接讀 SDK 原始碼確認判斷邏輯）。
    """
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from google import genai  # 延遲載入，DEMO_MODE 時不需要 SDK
                from google.genai import types
                kwargs: dict = {
                    "http_options": types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
                }
                if config.GEMINI_API_KEY:
                    kwargs["api_key"] = config.GEMINI_API_KEY
                _client = genai.Client(**kwargs)
    return _client


def create(
    input_: str | list[dict],
    tools: list[dict] | None = None,
    previous_id: str | None = None,
    system_instruction: str | None = None,
):
    """
    呼叫 Interactions API，回傳 interaction 物件。

    input_：純字串，或 [{"type": "text", ...}, {"type": "image", ...},
    {"type": "function_result", ...}] 這類 content part 清單（多輪帶工具
    結果時用）。
    tools：ai/tools.py 的 function declaration 清單，見該檔案格式。
    previous_id：延續前一輪對話時帶入，對應 previous_interaction_id。
    system_instruction：系統指示（例如 ai/prompts/agent.md）。⚠️ 次級來源
    （非 ai.google.dev 官方頁面直接寫的，是交叉比對到的第三方文章）確認為
    獨立參數；文件也提到 tools/generation_config 是 per-interaction、
    不會跟著 previous_interaction_id 延續，所以多輪對話每次都要重新帶，
    這裡對 system_instruction 採一樣保守做法。

    回傳的 interaction.output_text 是最終文字；interaction.steps 裡
    type == "function_call" 的項目要取 .name / .arguments / .id
    （.id 就是回覆時要帶的 call_id）。
    """
    kwargs: dict[str, Any] = {"model": config.GEMINI_MODEL, "input": input_}
    if tools:
        kwargs["tools"] = tools
    if previous_id:
        kwargs["previous_interaction_id"] = previous_id
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    return _get_client().interactions.create(**kwargs)


def generate(prompt: str, image_base64: str | None = None) -> str:
    """
    單次呼叫（generate_content，非 Interactions API），給不需要多輪
    對話狀態的任務用，例如 classify_item、narrate——這類任務本來就只
    送一次、拿一次結果，用不到 previous_interaction_id 接續能力。
    """
    contents: list = [prompt]
    if image_base64:
        contents.append(_image_part(image_base64))
    resp = _get_client().models.generate_content(model=config.GEMINI_MODEL, contents=contents)
    return resp.text


def _image_part(image_base64: str):
    from google.genai import types
    return types.Part.from_bytes(data=base64.b64decode(image_base64), mime_type="image/jpeg")


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
