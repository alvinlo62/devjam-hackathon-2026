"""
照片 → 結構化品項清單（spec.md §9.2 的 classify_item）。

不是 agent 工具，不經過 ai/tools.py 的 function-calling 迴圈——這是
agent 迴圈開始「之前」的獨立 Gemini 視覺呼叫，把照片變成結構化資料，
之後才輪到 ai/agent.py 的 run_scripted/run_llm 拿這份清單去跑
check_eligibility 等工具。這裡只負責「看懂照片」，不判斷資格。

用 client.generate()（generate_content）而不是 client.create()
（Interactions API）：這是單次呼叫，沒有第二輪，用不到 Interactions
API 的多輪狀態接續能力，見 ai/client.py 的說明。
"""
import json
import logging

from ai import client
from models import WasteItem

log = logging.getLogger(__name__)


def classify_photo(image_base64: str) -> list[WasteItem]:
    """拍照辨識大型廢棄物品項，回傳結構化清單。看不出東西時回傳空清單。"""
    prompt = client.load_prompt("classify")
    text = client.generate(prompt, image_base64=image_base64)

    text = (text or "[]").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    raw_items = json.loads(text)
    return [
        WasteItem(
            name=item["name"],
            category=item.get("category", "未分類"),
            quantity=item.get("quantity", 1),
            confidence=item.get("confidence", 1.0),
        )
        for item in raw_items
    ]