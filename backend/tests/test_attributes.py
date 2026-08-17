from models import WeightBand, WasteItem
from services import attributes


def _item(name: str, quantity: int = 1) -> WasteItem:
    return WasteItem(name=name, category="測試", quantity=quantity)


def test_annotate_known_item_returns_correct_attributes():
    attrs = attributes.annotate(_item("沙發"))
    assert attrs.weight_band == WeightBand.HEAVY
    assert attrs.max_dimension_cm == 200.0
    assert attrs.volume_units == 4.0


def test_fridge_marked_for_special_handling():
    attrs = attributes.annotate(_item("電冰箱"))
    assert attrs.special_handling is True


def test_unknown_item_uses_default_attributes():
    attrs = attributes.annotate(_item("神秘物體"))
    assert attrs.weight_band == WeightBand.MEDIUM
    assert attrs.volume_units == 1.0
    assert attrs.special_handling is False


def test_quantity_scales_total_volume():
    single = attributes.total_volume([_item("電風扇", quantity=1)])
    double = attributes.total_volume([_item("電風扇", quantity=2)])
    assert double == single * 2


def test_resource_hint_contains_system_suggestion_marker():
    hint = attributes.resource_hint([_item("沙發")])
    assert hint is not None
    assert "系統建議" in hint


def test_simple_item_has_no_hint():
    hint = attributes.resource_hint([_item("電風扇")])
    assert hint is None


def test_annotate_all_does_not_mutate_input():
    original = [_item("沙發")]
    annotated = attributes.annotate_all(original)
    assert original[0].attributes is None
    assert annotated[0].attributes is not None
    assert annotated[0] is not original[0]
