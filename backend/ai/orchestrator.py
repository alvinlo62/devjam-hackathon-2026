"""
ai/ 與 services/ 的唯一橋樑。

★ 這一層不做任何判斷或計算，只把 agent 的工具呼叫轉發給 services/
（經由 data/store.py 查案件與班次），再把結果包成 TraceStep。
所有數字都是 services/ 算出來的，這裡只負責轉發與講白話。
"""
from data import store
from models import Eligibility, TraceStep, WasteItem
from services import attributes, eligibility, scheduler


def execute(name: str, args: dict) -> tuple[dict, TraceStep]:
    """依工具名稱分派給對應 handler，回傳 (結果 dict, TraceStep)。"""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"未知工具: {name}")
    return handler(args)


def _items_from_args(item_names: list[str], quantities: list[int] | None) -> list[WasteItem]:
    quantities = quantities or [1] * len(item_names)
    return [
        WasteItem(name=name, category="未分類", quantity=qty)
        for name, qty in zip(item_names, quantities)
    ]


_ELIGIBILITY_LABEL = {
    Eligibility.ELIGIBLE: "符合家戶巨大垃圾範圍",
    Eligibility.INELIGIBLE: "不符合收運資格",
    Eligibility.NEEDS_REVIEW: "需清潔隊裁量",
}


def _check_eligibility(args: dict) -> tuple[dict, TraceStep]:
    items = _items_from_args(args["item_names"], args["quantities"])
    result = eligibility.check(
        items,
        applicant_type=args.get("applicant_type", "household"),
        renovation_by=args.get("renovation_by"),
    )
    step = TraceStep(
        icon="📋",
        action="查詢收運資格…",
        detail=f"→ {_ELIGIBILITY_LABEL[result.status]}",
        tool="check_eligibility",
    )
    return result.model_dump(mode="json"), step


def _get_attributes(args: dict) -> tuple[dict, TraceStep]:
    items = _items_from_args(args["item_names"], args.get("quantities"))
    annotated = attributes.annotate_all(items)
    hint = attributes.resource_hint(annotated)

    result = {
        "items": [item.model_dump(mode="json") for item in annotated],
        "resource_hint": hint,
    }
    detail = hint if hint else f"已查明 {len(annotated)} 項屬性，無特殊建議"
    step = TraceStep(icon="📦", action="查詢屬性…", detail=detail, tool="get_attributes")
    return result, step


def _compute_insertion(args: dict) -> tuple[dict, TraceStep]:
    case = store.get_case(args["case_id"])
    if case is None:
        raise ValueError(f"找不到案件: {args['case_id']}")
    shift = store.get_shift(args["shift_id"])
    if shift is None:
        raise ValueError(f"找不到班次: {args['shift_id']}")

    plan = scheduler.compute_insertion(shift, case)
    detail = (
        f"最佳位置：第 {plan.position} 站後，+{plan.added_minutes:.0f} 分鐘"
        if plan.feasible
        else (plan.reason or "插入後超過本班次容量")
    )
    step = TraceStep(icon="📍", action="計算插入位置…", detail=detail, tool="compute_insertion")
    return plan.model_dump(mode="json"), step


def _check_capacity(args: dict) -> tuple[dict, TraceStep]:
    shift = store.get_shift(args["shift_id"])
    if shift is None:
        raise ValueError(f"找不到班次: {args['shift_id']}")
    case = store.get_case(args["case_id"]) if args.get("case_id") else None

    result = scheduler.check_capacity(shift, case)
    if result["overloaded"]:
        detail = f"插入後達 {result['load_ratio']:.0%}，超過本班次容量"
    else:
        detail = f"目前載重 {result['load_ratio']:.0%}，尚有餘裕"
    step = TraceStep(icon="⚠️", action="檢查載重…", detail=detail, tool="check_capacity")
    return result, step


def _query_shifts(args: dict) -> tuple[dict, TraceStep]:
    district = args["district"]
    when = args["when"]
    is_next_day = when == "next_day"

    shift = store.next_day_shift(district) if is_next_day else store.today_shift(district)

    if shift is None:
        result = {"found": False, "district": district, "when": when}
        detail = f"{district}{'明日' if is_next_day else '今日'}尚無班次資料"
    else:
        remaining_ratio = max(0.0, 1.0 - shift.load_ratio)
        result = {
            "found": True,
            "shift_id": shift.id,
            "district": shift.district,
            "date": shift.date,
            "stop_count": len(shift.stops),
            "load_ratio": shift.load_ratio,
            "overloaded": shift.overloaded,
            "remaining_ratio": remaining_ratio,
        }
        if is_next_day:
            detail = (
                f"明日該區餘裕 {remaining_ratio:.0%}，可容納"
                if not shift.overloaded
                else f"明日該區也已達 {shift.load_ratio:.0%}，同樣吃緊"
            )
        else:
            detail = f"目前載重 {shift.load_ratio:.0%}"

    # ★ 這是 Demo 全場最重要的一行：今日超載 → agent 自己決定改查明日班次，
    # is_pivot=True 標出這是「改變計畫」的關鍵步驟，語意不可改。
    step = TraceStep(
        icon="🔄" if is_next_day else "📅",
        action="改為查詢明日班次…" if is_next_day else "查詢今日班次…",
        detail=detail,
        tool="query_shifts",
        is_pivot=is_next_day,
    )
    return result, step


def _ask_citizen(args: dict) -> tuple[dict, TraceStep]:
    result = {
        "question": args["question"],
        "options": args.get("options", []),
        "reason": args.get("reason"),
    }
    step = TraceStep(icon="❓", action="向民眾追問…", detail=args["question"], tool="ask_citizen")
    return result, step


_HANDLERS = {
    "check_eligibility": _check_eligibility,
    "get_attributes": _get_attributes,
    "compute_insertion": _compute_insertion,
    "check_capacity": _check_capacity,
    "query_shifts": _query_shifts,
    "ask_citizen": _ask_citizen,
}
