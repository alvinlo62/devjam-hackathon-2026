"""
距離矩陣的資料來源切換層。這裡會做 I/O（讀 fixture 檔、之後打 Google
Routes API），跟 rules.py 那種純資料表不同性質——之所以放在 data/
而不是 services/，是因為 AGENTS.md 的鐵則「services/ 不得有任何 I/O」
沒有例外；比照 db/cloudsql/client.py 的模式：I/O 邏輯放在 services/
外面一層，呼叫端（例如 services/scheduler.py 或 main.py）決定要不要
呼叫這裡的 get_matrix()，實際的距離計算/判定邏輯留在 services/。

真正確定性、可測試的計算在 services/distance.py 的 haversine_matrix()，
這裡只負責「選一個來源，選不到就退回那個純函式」。
"""
import json
import logging
from pathlib import Path

import config
from models import Location
from services.distance import haversine_matrix

log = logging.getLogger(__name__)

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "distance_matrix.json"


def get_matrix(
    locations: list[Location],
    source: str | None = None,
) -> list[list[float]]:
    """
    回傳 len(locations) × len(locations) 的行車分鐘數矩陣。

    source: "haversine" | "google" | "fixture"；None 時依 config.DEMO_MODE
    決定——DEMO_MODE=true（現場保命開關）用預先存好的 fixture，
    否則用 haversine（開發預設，不燒配額）。
    """
    if source is None:
        source = "fixture" if config.DEMO_MODE else "haversine"

    if source == "google":
        try:
            return _from_routes_api(locations)
        except NotImplementedError:
            log.warning("Routes API 尚未串接，自動退回 haversine 直線距離估算")
            return haversine_matrix(locations)

    if source == "fixture":
        return _from_fixture(locations)

    return haversine_matrix(locations)


def _from_fixture(locations: list[Location]) -> list[list[float]]:
    """
    讀 fixtures/distance_matrix.json，內容應為預先算好的
    len(locations) × len(locations) 矩陣（見 _from_routes_api 的說明）。
    """
    matrix = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    if len(matrix) != len(locations):
        raise ValueError(
            f"fixture 矩陣大小 {len(matrix)} 與 locations 數量 {len(locations)} 不符，"
            "fixture 可能是為別組案件資料算的，需重新產生"
        )
    return matrix


def _from_routes_api(locations: list[Location]) -> list[list[float]]:
    """
    真實路程矩陣，串接 Google Routes API 的 ComputeRouteMatrix。

    尚未實作。實作時務必注意（spec.md §4.3 ⚠️）：
      1. X-Goog-FieldMask 是必填 HTTP header（不是 body），遺漏直接 400
      2. 計費按元素數計算，30×30 = 900 元素，務必在 Google Cloud
         設每日用量上限，避免現場或測試時把配額燒光
      3. 算出結果後存成 fixture（見 _from_fixture），Demo 現場不要即時打 API
    """
    raise NotImplementedError(f"Routes API 尚未串接，見 docs/spec.md §4.3（{len(locations)} 個地點待查）")