"""
距離矩陣的純計算部分。純函式，同輸入永遠同輸出，不依賴 ai 模組、不做任何 I/O。

可替換來源（fixture 讀檔、Google Routes API）不屬於這裡——那些是 I/O，
依 AGENTS.md 鐵則「services/ 不得有任何 I/O」不能放在 services/ 底下，
移到 data/distance_source.py（比照 db/cloudsql/client.py 的模式：
I/O 邏輯放在 services/ 外面一層）。haversine_matrix() 是唯一的資料來源
保底：不管上層怎麼選 source，最後永遠可以退回這裡。
"""
import math

from models import Location

# 📏 常識推估，非官方數據，僅供 Demo 用：
# 直線距離 × 修正係數 ≈ 實際路網距離；除以市區均速換算成分鐘。
_STRAIGHT_LINE_CORRECTION = 1.35
_AVG_URBAN_SPEED_KMH = 20.0
_EARTH_RADIUS_KM = 6371.0


def haversine_matrix(locations: list[Location]) -> list[list[float]]:
    """
    回傳 len(locations) × len(locations) 的行車分鐘數矩陣，對角線為 0。
    直線距離 × 修正係數，除以市區均速換算成分鐘。
    """
    n = len(locations)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            matrix[i][j] = leg_minutes(locations[i], locations[j])
    return matrix


def leg_minutes(a: Location, b: Location) -> float:
    """單一段路程的行車分鐘數，供排程逐段計算用（不需要整張矩陣時）。"""
    km = _haversine_km(a, b) * _STRAIGHT_LINE_CORRECTION
    return km / _AVG_URBAN_SPEED_KMH * 60


def _haversine_km(a: Location, b: Location) -> float:
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dlambda = math.radians(b.lng - a.lng)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(h))