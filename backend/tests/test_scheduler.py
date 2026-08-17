from data import rules
from models import Case, ItemAttributes, Location, Shift, WasteItem, WeightBand
from services import scheduler

DEPOT = rules.DEPOTS["信義區"]  # 測試預設用信義區，跟 _case/_shift 的預設 district 對齊


def _location(lat: float, lng: float, district: str = "信義區") -> Location:
    return Location(address=f"{lat},{lng}", district=district, lat=lat, lng=lng)


def _item(volume_units: float = 1.0) -> WasteItem:
    return WasteItem(
        name="測試物品",
        category="測試",
        quantity=1,
        attributes=ItemAttributes(
            weight_band=WeightBand.MEDIUM,
            max_dimension_cm=100.0,
            dismantlable=False,
            special_handling=False,
            volume_units=volume_units,
        ),
    )


def _case(case_id: str, lat: float, lng: float, volume_units: float = 1.0, district: str = "信義區") -> Case:
    return Case(id=case_id, location=_location(lat, lng, district), items=[_item(volume_units)])


def _shift(case_ids_and_volumes: list[tuple[str, float]], capacity_units: float) -> Shift:
    """建一個班次，案件沿著離 DEPOT 越來越遠的方向排開，避免測試依賴排序細節。"""
    cases = [
        _case(cid, DEPOT.lat + 0.001 * (i + 1), DEPOT.lng, vol)
        for i, (cid, vol) in enumerate(case_ids_and_volumes)
    ]
    return scheduler.build_shift("s1", "信義區", "2026-08-17", cases, capacity_units)


def test_order_route_empty_cases():
    ordered, total_minutes = scheduler.order_route([], DEPOT)
    assert ordered == []
    assert total_minutes == 0.0


def test_order_route_is_reproducible():
    cases = [
        _case("a", DEPOT.lat + 0.02, DEPOT.lng),
        _case("b", DEPOT.lat + 0.01, DEPOT.lng),
        _case("c", DEPOT.lat + 0.03, DEPOT.lng),
    ]
    result1 = scheduler.order_route(cases, DEPOT)
    result2 = scheduler.order_route(cases, DEPOT)
    ids1 = [c.id for c in result1[0]]
    ids2 = [c.id for c in result2[0]]
    assert ids1 == ids2
    assert result1[1] == result2[1]


def test_nearest_neighbor_picks_closest_first():
    far = _case("far", DEPOT.lat + 0.05, DEPOT.lng)
    near = _case("near", DEPOT.lat + 0.005, DEPOT.lng)
    ordered, _ = scheduler.order_route([far, near], DEPOT)
    assert ordered[0].id == "near"
    assert ordered[1].id == "far"


def test_tie_break_picks_lower_index_when_equidistant():
    # 與 DEPOT 同緯度、經度對稱偏移，兩者到 DEPOT 的距離理論上完全相等。
    case_low_index = _case("low", DEPOT.lat, DEPOT.lng - 0.01)
    case_high_index = _case("high", DEPOT.lat, DEPOT.lng + 0.01)
    ordered, _ = scheduler.order_route([case_low_index, case_high_index], DEPOT)
    assert ordered[0].id == "low"


def test_build_shift_fills_seq_and_eta():
    shift = _shift([("a", 1.0), ("b", 1.0)], capacity_units=10)
    assert [stop.seq for stop in shift.stops] == [1, 2]
    assert shift.stops[0].eta_minutes > 0
    assert shift.stops[1].eta_minutes > shift.stops[0].eta_minutes


def test_capacity_not_overloaded_when_under_threshold():
    shift = _shift([("a", 2.0)], capacity_units=10)
    result = scheduler.check_capacity(shift)
    assert result["overloaded"] is False


def test_capacity_overloaded_when_over_threshold():
    shift = _shift([("a", 12.0)], capacity_units=10)
    result = scheduler.check_capacity(shift)
    assert result["overloaded"] is True


def test_insertion_infeasible_when_it_would_overload():
    shift = _shift([("a", 8.0)], capacity_units=10)
    new_case = _case("new", DEPOT.lat + 0.5, DEPOT.lng, volume_units=5.0)
    plan = scheduler.compute_insertion(shift, new_case)
    assert plan.feasible is False
    assert plan.resulting_load_ratio > 1.0


def test_insertion_feasible_when_there_is_room():
    shift = _shift([("a", 2.0)], capacity_units=10)
    new_case = _case("new", DEPOT.lat + 0.5, DEPOT.lng, volume_units=3.0)
    plan = scheduler.compute_insertion(shift, new_case)
    assert plan.feasible is True


def test_apply_insertion_adds_stop_at_position_and_increases_used_units():
    shift = _shift([("a", 1.0), ("b", 1.0)], capacity_units=10)
    original_used_units = shift.used_units
    original_stop_count = len(shift.stops)

    new_case = _case("new", DEPOT.lat + 0.5, DEPOT.lng, volume_units=2.0)
    new_shift = scheduler.apply_insertion(shift, new_case, position=1)

    assert len(new_shift.stops) == original_stop_count + 1
    assert new_shift.stops[1].case.id == "new"
    assert new_shift.used_units == original_used_units + 2.0
    # 原本的 shift 不能被動到
    assert len(shift.stops) == original_stop_count
    assert shift.used_units == original_used_units


def test_group_by_district_groups_correctly():
    cases = [
        _case("a", 25.0, 121.5, district="信義區"),
        _case("b", 25.0, 121.5, district="大安區"),
        _case("c", 25.0, 121.5, district="信義區"),
    ]
    groups = scheduler.group_by_district(cases)
    assert {c.id for c in groups["信義區"]} == {"a", "c"}
    assert {c.id for c in groups["大安區"]} == {"b"}