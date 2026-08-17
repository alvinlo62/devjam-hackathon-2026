"""
只測 services/，不要測 ai/。
AI 輸出不穩定，測了浪費時間；規則引擎算錯則會在 Demo 現場致命。

執行：uv run pytest
"""
from models import ExtractedItem
from services import analyzer


def _item(value, confidence=1.0):
    return ExtractedItem(name="t", category="c", value=value, confidence=confidence)


def test_pass():
    r = analyzer.evaluate([_item(90)])[0]
    assert r.status == "pass"
    assert r.gap is None


def test_warn_has_gap():
    r = analyzer.evaluate([_item(60)])[0]
    assert r.status == "warn"
    assert r.gap is not None


def test_fail():
    assert analyzer.evaluate([_item(10)])[0].status == "fail"


def test_low_confidence_flagged():
    r = analyzer.evaluate([_item(90, confidence=0.3)])[0]
    assert any("信心" in x for x in r.reasons)
