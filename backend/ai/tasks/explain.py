"""AI 任務二：結構化結果 → 白話說明。"""
import logging

import config
from models import AnalysisResult
from ai import client

log = logging.getLogger(__name__)


def run(results: list[AnalysisResult]) -> tuple[str, bool]:
    """回傳 (說明文字, 是否走了 fixture fallback)。"""
    if config.DEMO_MODE:
        return _fallback(results), True

    payload = "\n".join(
        f"- {r.item.name}｜{r.status}｜{r.score}｜{'；'.join(r.reasons)}"
        for r in results
    )
    try:
        return client.generate_text(client.load_prompt("explain", results=payload)), False
    except Exception:
        log.exception("explain failed, using fallback")
        return _fallback(results), True


def _fallback(results: list[AnalysisResult]) -> str:
    """AI 掛掉時的降級輸出。內容仍然正確，只是不夠口語。"""
    n = len(results)
    ok = sum(1 for r in results if r.status == "pass")
    return f"共分析 {n} 項，其中 {ok} 項通過。詳細判定依據請見下方清單。"
