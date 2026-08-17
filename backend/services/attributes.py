"""
屬性標記與資源建議。純函式，同輸入永遠同輸出。

不得依賴 ai 模組、不得呼叫任何外部 API（AGENTS.md 架構鐵則）。

★ 觀察 vs 主張（spec.md §7.1）：
- ItemAttributes 是「觀察」——查表得來的客觀事實，不帶建議。
- resource_hint() 產生的文字是「主張」——系統參考值，不是規範要求，
  文字裡一律含「系統建議」字樣，避免被誤讀成官方規定。
"""
from data import rules
from models import ItemAttributes, WasteItem, WeightBand


def annotate(item: WasteItem) -> ItemAttributes:
    """查表取得單一品項的屬性，查不到就用保守預設值（見 rules.DEFAULT_ITEM_ATTRIBUTES）。"""
    # 別名對照跟 services/eligibility.py 用同一張表，兩邊對「這是同一種東西」
    # 要有一致的認知，例如「辦公椅」查屬性時也該當成「桌椅」查。
    canonical = rules.ITEM_ALIASES.get(item.name, item.name)
    weight_band, max_dimension_cm, dismantlable, special_handling, volume_units = (
        rules.ITEM_ATTRIBUTES.get(canonical, rules.DEFAULT_ITEM_ATTRIBUTES)
    )
    return ItemAttributes(
        weight_band=weight_band,
        max_dimension_cm=max_dimension_cm,
        dismantlable=dismantlable,
        special_handling=special_handling,
        volume_units=volume_units,
    )


def annotate_all(items: list[WasteItem]) -> list[WasteItem]:
    """回傳附上 attributes 的新品項清單，不修改傳入的 items。"""
    return [item.model_copy(update={"attributes": annotate(item)}) for item in items]


def total_volume(items: list[WasteItem]) -> float:
    """
    所有品項的體積加總（volume_units × quantity），供載重計算使用
    （spec.md §4.2：累加體積 → 超過容量閾值 → 標紅色警示）。

    品項若已有 attributes（例如已跑過 annotate_all）就直接用，
    否則現場查表，不強制要求呼叫順序。
    """
    total = 0.0
    for item in items:
        attrs = item.attributes or annotate(item)
        total += attrs.volume_units * item.quantity
    return total


def resource_hint(items: list[WasteItem]) -> str | None:
    """
    依品項屬性產生人力/處理建議的白話文，全部是「系統參考值」，不是規範。

    只有重物（HEAVY）或需特殊處理的品項才會產生提示；
    全部是輕巧、無特殊需求的品項時回傳 None，不硬湊內容。
    """
    hints: list[str] = []
    for item in items:
        attrs = item.attributes or annotate(item)
        if attrs.weight_band == WeightBand.HEAVY:
            hints.append(f"「{item.name}」系統建議配置 2 人以上搬運（僅供參考，實際依現場判斷）")
        if attrs.special_handling:
            hints.append(f"「{item.name}」含冷媒等需特殊處理設備，系統建議安排特殊處理流程（僅供參考，實際依現場判斷）")
    return "；".join(hints) if hints else None