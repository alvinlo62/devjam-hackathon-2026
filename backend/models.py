"""
前後端契約。比賽第 1 小時就要定案，之後盡量不改。
改這裡 = 前後端都要改，成本最高。

命名慣例：<Action>Request / <Action>Response
"""
from typing import Any, Literal
from pydantic import BaseModel, Field


# ---------- 通用回應外殼 ----------
class ApiResponse(BaseModel):
    """所有 endpoint 統一用這個外殼包，前端只要寫一套錯誤處理。"""
    ok: bool = True
    data: Any | None = None
    error: str | None = None


# ---------- 領域模型（比賽當天改這裡）----------
class ExtractedItem(BaseModel):
    """AI 從非結構化輸入抽出來的一筆結構化資料。"""
    name: str
    category: str
    value: float | None = None
    confidence: float = Field(ge=0, le=1, default=1.0)
    note: str | None = None


class AnalysisResult(BaseModel):
    """規則引擎算完的結果。注意：這是程式算的，不是 AI 生的。"""
    item: ExtractedItem
    status: Literal["pass", "warn", "fail"]
    score: float
    reasons: list[str] = []          # 判定依據，逐條可追溯
    gap: str | None = None           # 「差一點」提醒


# ---------- Request / Response ----------
class AnalyzeRequest(BaseModel):
    text: str | None = None
    image_base64: str | None = None
    options: dict[str, Any] = {}


class AnalyzeResponse(BaseModel):
    results: list[AnalysisResult]
    summary: str                     # AI 生成的白話說明
    used_fixture: bool = False       # 是否走 DEMO_MODE
