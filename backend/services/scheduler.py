"""
排程核心：單一班次的路線排序（最近鄰居）+ 載重檢查 + 插入成本。
純函式，不依賴 ai 模組、不做任何 I/O（AGENTS.md 架構鐵則）。

範圍界定（不可擴張，spec.md §4.1）：
✅ 做：單一班次的路線排序 + 載重檢查 + 插入成本
❌ 不做：多車分派（VRP）、時間窗（VRPTW）
分區分組（group_by_district）是查表（讀 Case.location.district），不是演算法。

compute_insertion() 的 feasible=False 是 agent 改變計畫、轉去查詢明日班次
的觸發點（spec.md §5.2 關鍵決策點），這個欄位的語意不可改。
"""
from data import rules
from models import Case, InsertionPlan, Location, Shift, Stop
from services import attributes, distance


def _depot_for(district: str) -> Location:
    """依行政區查對應清潔隊駐地（data.rules.DEPOTS），查不到就退回未查證的預設值。"""
    return rules.DEPOTS.get(district, rules.DEFAULT_DEPOT)


def order_route(cases: list[Case], depot: Location) -> tuple[list[Case], float]:
    """
    最近鄰居排序，從 depot 出發。相同距離時取索引較小者（線性掃描、
    只在嚴格更小時才換人選，天生就是「先到先贏」），確保結果可重現。

    回傳 (排序後案件, 總分鐘數)。
    """
    if not cases:
        return [], 0.0

    remaining = list(range(len(cases)))  # 保持原始索引升冪，tie-break 用
    current_loc = depot
    ordered: list[Case] = []
    total_minutes = 0.0

    while remaining:
        best_pos_in_remaining = None
        best_minutes = None
        for pos, idx in enumerate(remaining):
            minutes = distance.leg_minutes(current_loc, cases[idx].location)
            if best_minutes is None or minutes < best_minutes:
                best_minutes = minutes
                best_pos_in_remaining = pos

        chosen_idx = remaining.pop(best_pos_in_remaining)
        ordered.append(cases[chosen_idx])
        total_minutes += best_minutes
        current_loc = cases[chosen_idx].location

    return ordered, total_minutes


def build_shift(
    shift_id: str,
    district: str,
    date: str,
    cases: list[Case],
    capacity_units: float,
) -> Shift:
    """依最近鄰居排序建立班次，填入每站 Stop 與 eta_minutes，算出 used_units。"""
    depot = _depot_for(district)
    ordered, _ = order_route(cases, depot)
    stops, total_minutes = _build_stops(ordered, depot)
    used_units = attributes.total_volume([item for case in ordered for item in case.items])

    return Shift(
        id=shift_id,
        district=district,
        date=date,
        capacity_units=capacity_units,
        used_units=used_units,
        stops=stops,
        total_minutes=total_minutes,
    )


def _build_stops(cases_in_order: list[Case], depot: Location) -> tuple[list[Stop], float]:
    """依既定順序（不重新排序）從 depot 出發，逐站算 eta_minutes。"""
    stops: list[Stop] = []
    current_loc = depot
    cumulative = 0.0
    for seq, case in enumerate(cases_in_order, start=1):
        cumulative += distance.leg_minutes(current_loc, case.location)
        stops.append(Stop(seq=seq, case=case, eta_minutes=cumulative))
        current_loc = case.location
    return stops, cumulative


def group_by_district(cases: list[Case]) -> dict[str, list[Case]]:
    """依 Case.location.district 查表分組，不是演算法（spec.md §4.1）。"""
    groups: dict[str, list[Case]] = {}
    for case in cases:
        groups.setdefault(case.location.district, []).append(case)
    return groups


def compute_insertion(shift: Shift, case: Case) -> InsertionPlan:
    """
    ★ Demo 核心。對每個可能位置計算「插入後總時間 − 原本總時間」，取最小者；
    同時算插入後載重率，超過容量則 feasible=False——這是 agent 決定要不要
    改查明日班次的依據，語意不可變動。

    position 的語意（見 models.py InsertionPlan）：插入在第 position 站之後，
    0 代表插在駐地之後、成為新的第一站。
    """
    depot = _depot_for(shift.district)
    sequence_locations = [depot] + [stop.case.location for stop in shift.stops]
    n = len(shift.stops)

    best_position = 0
    best_added: float | None = None
    for position in range(n + 1):
        prev_loc = sequence_locations[position]
        if position < n:
            next_loc = sequence_locations[position + 1]
            original_leg = distance.leg_minutes(prev_loc, next_loc)
            added = (
                distance.leg_minutes(prev_loc, case.location)
                + distance.leg_minutes(case.location, next_loc)
                - original_leg
            )
        else:
            added = distance.leg_minutes(prev_loc, case.location)

        if best_added is None or added < best_added:
            best_added = added
            best_position = position

    capacity = check_capacity(shift, case)
    feasible = not capacity["overloaded"]
    reason = (
        f"插入後達 {capacity['load_ratio']:.0%}，超過本班次容量閾值"
        if not feasible
        else None
    )

    return InsertionPlan(
        shift_id=shift.id,
        position=best_position,
        added_minutes=best_added,
        resulting_load_ratio=capacity["load_ratio"],
        feasible=feasible,
        reason=reason,
    )


def apply_insertion(shift: Shift, case: Case, position: int) -> Shift:
    """
    實際插入，只在班長點擊接受後呼叫。回傳新 Shift，不修改輸入。
    不重新跑最近鄰居排序——插入位置由呼叫端（通常是 compute_insertion
    的建議）決定，保留班長看到的路線順序不被系統事後打亂。
    """
    existing_cases = [stop.case for stop in shift.stops]
    new_cases = existing_cases[:position] + [case] + existing_cases[position:]
    stops, total_minutes = _build_stops(new_cases, _depot_for(shift.district))
    used_units = attributes.total_volume([item for c in new_cases for item in c.items])

    return shift.model_copy(
        update={"stops": stops, "total_minutes": total_minutes, "used_units": used_units}
    )


def check_capacity(shift: Shift, case: Case | None = None) -> dict:
    """
    current_units：目前已用容量。
    projected_units：若插入 case（未提供則等於 current_units）後的容量。
    load_ratio / overloaded：以 projected_units 計算，門檻與 Shift.overloaded 一致（>1.0）。
    """
    current_units = shift.used_units
    added_units = attributes.total_volume(case.items) if case is not None else 0.0
    projected_units = current_units + added_units
    load_ratio = projected_units / shift.capacity_units if shift.capacity_units > 0 else 0.0

    return {
        "current_units": current_units,
        "projected_units": projected_units,
        "load_ratio": load_ratio,
        "overloaded": load_ratio > 1.0,
    }