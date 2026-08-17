"""AI 任務一：非結構化輸入 → 結構化資料。"""
import json
import logging
from pathlib import Path

from pydantic import BaseModel

import config
from models import ExtractedItem
from ai import client

log = logging.getLogger(__name__)


class _ExtractOutput(BaseModel):
    """給 Gemini 的 response_schema。"""
    items: list[ExtractedItem]


def run(
    text: str | None = None, image_base64: str | None = None
) -> tuple[list[ExtractedItem], bool]:
    """回傳 (結果, 是否走了 fixture fallback)。"""
    if config.DEMO_MODE:
        return _from_fixture(), True

    prompt = client.load_prompt("extract", user_input=text or "（見圖片）")
    try:
        out = client.generate_structured(prompt, _ExtractOutput, image_base64=image_base64)
        return out.items, False
    except Exception:
        log.exception("extract failed, falling back to fixture")
        return _from_fixture(), True   # 現場保命：API 掛掉也不要整個流程死掉


def _from_fixture() -> list[ExtractedItem]:
    path = Path(__file__).resolve().parents[2] / "fixtures" / "demo_items.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [ExtractedItem(**x) for x in raw]
