from models import Eligibility, WasteItem
from services import eligibility


def _item(name: str, quantity: int = 1) -> WasteItem:
    return WasteItem(name=name, category="測試", quantity=quantity)


def test_accepted_item_is_eligible():
    result = eligibility.check([_item("沙發")])
    assert result.status == Eligibility.ELIGIBLE


def test_luggage_below_threshold_is_ineligible():
    result = eligibility.check([_item("廢行李箱", quantity=2)])
    assert result.status == Eligibility.INELIGIBLE
    assert any("3 只" in r for r in result.reasons)


def test_luggage_at_threshold_is_eligible():
    result = eligibility.check([_item("廢行李箱", quantity=3)])
    assert result.status == Eligibility.ELIGIBLE


def test_corporate_applicant_is_ineligible():
    result = eligibility.check([_item("沙發")], applicant_type="corporate")
    assert result.status == Eligibility.INELIGIBLE


def test_renovation_waste_without_source_needs_review_and_clarification():
    result = eligibility.check([_item("木板")])
    assert result.status == Eligibility.NEEDS_REVIEW
    assert result.clarification_needed is True


def test_renovation_waste_by_contractor_is_ineligible():
    result = eligibility.check([_item("木板")], renovation_by="contractor")
    assert result.status == Eligibility.INELIGIBLE


def test_renovation_waste_by_self_needs_review():
    result = eligibility.check([_item("木板")], renovation_by="self")
    assert result.status == Eligibility.NEEDS_REVIEW


def test_stone_item_is_ineligible():
    result = eligibility.check([_item("大理石桌")])
    assert result.status == Eligibility.INELIGIBLE


def test_unknown_item_needs_review():
    result = eligibility.check([_item("不明物體")])
    assert result.status == Eligibility.NEEDS_REVIEW


def test_item_results_pinpoint_which_item_failed():
    result = eligibility.check([_item("沙發"), _item("大理石桌")])
    assert result.status == Eligibility.INELIGIBLE  # 案件層級彙整取最嚴重者
    assert len(result.items) == 2
    assert result.items[0].item_index == 0
    assert result.items[0].status == Eligibility.ELIGIBLE
    assert result.items[1].item_index == 1
    assert result.items[1].item_name == "大理石桌"
    assert result.items[1].status == Eligibility.INELIGIBLE