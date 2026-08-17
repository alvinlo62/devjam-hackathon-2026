"""
業務邏輯層：確定性、純函式、可測試。

原則：
  - 這一層不呼叫任何 AI，不做 I/O
  - 同樣輸入永遠得到同樣輸出
  - 每個判定都要能說出「依據是什麼」

這一層的存在就是你的技術論述：
評審問「AI 出錯怎麼辦」，答案是核心判定根本不經過 AI。
"""
from models import AnalysisResult, ExtractedItem

# 規則可以寫死在這，也可以從 data/*.json 讀進來
THRESHOLDS = {
    "default": {"pass": 80.0, "warn": 50.0},
}


def evaluate(
    items: list[ExtractedItem],
    options: dict | None = None,
) -> list[AnalysisResult]:
    options = options or {}
    rule = THRESHOLDS.get(options.get("ruleset", "default"), THRESHOLDS["default"])

    results: list[AnalysisResult] = []
    for item in items:
        score = _score(item)
        reasons: list[str] = []
        gap: str | None = None

        if score >= rule["pass"]:
            status = "pass"
            reasons.append(f"分數 {score:.1f} 達標準 {rule['pass']}")
        elif score >= rule["warn"]:
            status = "warn"
            reasons.append(f"分數 {score:.1f} 低於標準 {rule['pass']}")
            gap = f"再提高 {rule['pass'] - score:.1f} 分即可達標"
        else:
            status = "fail"
            reasons.append(f"分數 {score:.1f} 低於警戒值 {rule['warn']}")
            gap = f"距離警戒值還差 {rule['warn'] - score:.1f} 分"

        if item.confidence < 0.6:
            reasons.append("辨識信心偏低，建議人工確認")

        results.append(
            AnalysisResult(
                item=item, status=status, score=score,
                reasons=reasons, gap=gap,
            )
        )
    return results


def _score(item: ExtractedItem) -> float:
    """把計算拆成小的純函式，好測試也好講解。"""
    base = item.value if item.value is not None else 0.0
    return round(base * item.confidence, 2)
