"""
資格判定。純函式，同輸入永遠同輸出。

不得依賴 ai 模組、不得呼叫任何外部 API（AGENTS.md 架構鐵則）。
判定結果與理由一律從這裡產出，ai/ 只能把 EligibilityResult 講成人話，
不得反過來覆寫這裡的判定。
"""
from data import rules
from models import Eligibility, EligibilityResult, ItemEligibility, WasteItem

# 內部除錯/測試追溯用：對應本專案規格文件章節（非政府規則來源）。
# 與 rules.py 裡「轉錄自政府公告」的常數性質不同，不應混在一起，
# 也不是要顯示給使用者看的東西——見 models.py 裡 rule_refs 的說明。
# 兩個不同章節，不可合併：§6.2 是「非石材類」排除條款本身，
# §6.3 是該條款的追問/裁量流程系統化設計。
_SPEC_STONE_CLAUSE = "spec.md §6.2 裁量條款"
_SPEC_RENOVATION_CLAUSE = "spec.md §6.3 裁量條款"

# 合格清單攤平成集合，供逐項比對用（見 _check_item）。
_ACCEPTED_NAMES: set[str] = {
    name for names in rules.ACCEPTED_ITEMS.values() for name in names
}

# 判定嚴重度：一件案件裡只要有一項 ineligible，整件就是 ineligible；
# 沒有 ineligible 但有 needs_review，整件就是 needs_review；
# 全部 eligible 才是 eligible。
_SEVERITY = {
    Eligibility.ELIGIBLE: 0,
    Eligibility.NEEDS_REVIEW: 1,
    Eligibility.INELIGIBLE: 2,
}


def check(
    items: list[WasteItem],
    applicant_type: str = "household",
    renovation_by: str | None = None,
) -> EligibilityResult:
    """
    判定順序（spec.md §6）：
      1. 申請對象排除（案件層級，優先於所有品項判定）
      2. 每個品項依序檢查：石材類 → 數量門檻 → 裝潢廢料關鍵字 → 在清單內 → 不在清單內
      3. 彙整所有品項的判定，取最嚴重者作為整件案件的狀態；
         逐品項明細放進 EligibilityResult.items，供班長端標示「第幾項有問題」
    """
    if applicant_type in rules.EXCLUDED_APPLICANTS:
        label = rules.EXCLUDED_APPLICANTS[applicant_type]
        return EligibilityResult(
            status=Eligibility.INELIGIBLE,
            reasons=[
                f"申請對象為「{label}」，服務對象限一般家庭及住戶",
                rules.EXCLUDED_APPLICANT_REFERRAL,
            ],
            rule_refs=["rules.EXCLUDED_APPLICANTS", "rules.EXCLUDED_APPLICANT_REFERRAL"],
        )

    if not items:
        return EligibilityResult(
            status=Eligibility.NEEDS_REVIEW,
            reasons=["未提供任何品項，需人工確認"],
            rule_refs=["services.eligibility:empty_items"],
        )

    worst = Eligibility.ELIGIBLE
    reasons: list[str] = []
    rule_refs: list[str] = []
    clarification_needed = False
    item_results: list[ItemEligibility] = []

    for index, item in enumerate(items):
        status, item_reasons, item_refs, needs_clarify = _check_item(item, renovation_by)
        reasons.extend(item_reasons)
        rule_refs.extend(item_refs)
        clarification_needed = clarification_needed or needs_clarify
        item_results.append(
            ItemEligibility(
                item_index=index,
                item_name=item.name,
                status=status,
                reasons=item_reasons,
                rule_refs=item_refs,
            )
        )
        if _SEVERITY[status] > _SEVERITY[worst]:
            worst = status

    return EligibilityResult(
        status=worst,
        reasons=reasons,
        rule_refs=list(dict.fromkeys(rule_refs)),  # 去重但保留順序
        clarification_needed=clarification_needed,
        items=item_results,
    )


def _check_item(
    item: WasteItem,
    renovation_by: str | None,
) -> tuple[Eligibility, list[str], list[str], bool]:
    """回傳 (status, reasons, rule_refs, clarification_needed)，單一品項判定。"""
    name = item.name
    # 別名對照：Gemini 辨識用詞轉成公告清單的精確字串（例如「辦公椅」-> 「桌椅」），
    # 只用來比對，reasons 裡仍顯示原始名稱，保持對民眾/班長的說明貼近實際輸入。
    canonical = rules.ITEM_ALIASES.get(name, name)

    if any(kw in name for kw in rules.STONE_KEYWORDS):
        return (
            Eligibility.INELIGIBLE,
            [f"「{name}」屬石材類，裁量條款僅適用非石材類廢棄物"],
            ["rules.STONE_KEYWORDS", _SPEC_STONE_CLAUSE],
            False,
        )

    threshold = rules.QUANTITY_THRESHOLDS.get(canonical)
    if threshold is not None and item.quantity < threshold:
        return (
            Eligibility.INELIGIBLE,
            [f"「{name}」數量 {item.quantity} 只，未達 {threshold} 只（含）以上門檻"],
            ["rules.QUANTITY_THRESHOLDS"],
            False,
        )

    if any(kw in name for kw in rules.RENOVATION_KEYWORDS):
        if renovation_by == "contractor":
            return (
                Eligibility.INELIGIBLE,
                [
                    f"「{name}」為廠商施工之裝潢廢料，非個人自行修繕",
                    rules.EXCLUDED_APPLICANT_REFERRAL,
                ],
                [_SPEC_RENOVATION_CLAUSE, "rules.EXCLUDED_APPLICANT_REFERRAL"],
                False,
            )
        if renovation_by == "self":
            return (
                Eligibility.NEEDS_REVIEW,
                [f"「{name}」為自行拆除之裝潢廢料，需清潔隊現場裁量"],
                [_SPEC_RENOVATION_CLAUSE],
                False,
            )
        # renovation_by 為 None 或其他未定義值：無法判斷施工方，交給 agent 追問
        return (
            Eligibility.NEEDS_REVIEW,
            [f"「{name}」疑似裝潢廢料，需確認是否為自行拆除"],
            [_SPEC_RENOVATION_CLAUSE],
            True,
        )

    if canonical in _ACCEPTED_NAMES:
        reason = (
            f"「{name}」屬公告收運品項清單"
            if canonical == name
            else f"「{name}」對應公告品項「{canonical}」，屬收運清單"
        )
        refs = ["rules.ACCEPTED_ITEMS"]
        if canonical != name:
            refs.append("rules.ITEM_ALIASES")
        return (Eligibility.ELIGIBLE, [reason], refs, False)

    return (
        Eligibility.NEEDS_REVIEW,
        [f"「{name}」不在公告收運品項清單內，需清潔隊現場確認"],
        ["rules.ACCEPTED_ITEMS"],
        False,
    )