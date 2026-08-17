"""
記憶體儲存：案件與班次的唯一存放處。刻意不用資料庫（AGENTS.md「刻意不做的事」）。

放在 data/ 而不是 services/，理由跟 data/distance_source.py 一樣：
這裡會做 I/O（讀 fixtures/demo_cases.json）而且本質上是可變狀態（模組級
dict），完全不符合 services/ 的「純函式、同輸入同輸出、不得 I/O」鐵則。
這裡是呼叫端，負責串起 services/eligibility、services/attributes、
services/scheduler 三個純函式模組，把結果放進記憶體——判定/計算邏輯
本身仍在 services/，這裡只負責「串起來、存起來」。
"""
import json
import threading
from pathlib import Path

from models import Case, CaseStatus, Eligibility, Location, Shift, WasteItem
from services import attributes, eligibility, scheduler

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "demo_cases.json"

_shifts: dict[str, Shift] = {}
_cases: dict[str, Case] = {}
# (district, "today" | "tomorrow") -> shift_id，load() 時依 fixture 的 day 標籤建立。
# 用邏輯標籤而不是比對真實日期，demo 隔天再跑也不會失準。
_shift_index: dict[tuple[str, str], str] = {}
_loaded = False
_next_seq = 1
# main.py 的 endpoint 都是同步 def，FastAPI 會丟進 threadpool 平行執行，
# 不是單一 event loop 排隊——_next_seq 這種「讀取→遞增→寫回」不是原子操作，
# 兩人同時送件有機會拿到同一個 case_id、其中一筆蓋掉另一筆，故需要這把鎖。
_seq_lock = threading.Lock()


def ensure_loaded() -> None:
    """第一次呼叫任何查詢前先確保 fixture 已載入，避免每支 endpoint 自己記得呼叫 load()。"""
    if not _loaded:
        load()


def load() -> None:
    """
    從 fixtures/demo_cases.json 載入案件、補上屬性、跑資格判定、建立初始班次。
    重複呼叫會整個重置成 fixture 的初始狀態（demo 現場重來一次用）。
    """
    global _loaded, _next_seq

    raw = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    _shifts.clear()
    _cases.clear()
    _shift_index.clear()

    shift_meta = {s["shift_id"]: s for s in raw["shifts"]}
    for s in raw["shifts"]:
        _shift_index[(s["district"], s["day"])] = s["shift_id"]

    cases_for_shift: dict[str, list[Case]] = {sid: [] for sid in shift_meta}

    for c in raw["cases"]:
        location = Location(**c["location"])
        raw_items = [
            WasteItem(name=i["name"], category=i["category"], quantity=i["quantity"])
            for i in c["items"]
        ]
        annotated_items = attributes.annotate_all(raw_items)
        result = eligibility.check(annotated_items)

        status = {
            Eligibility.ELIGIBLE: CaseStatus.SCHEDULED,
            Eligibility.NEEDS_REVIEW: CaseStatus.PENDING,
            Eligibility.INELIGIBLE: CaseStatus.REJECTED,
        }[result.status]

        case = Case(
            id=c["id"],
            location=location,
            items=annotated_items,
            eligibility=result,
            status=status,
            resource_hint=attributes.resource_hint(annotated_items),
        )
        _cases[case.id] = case

        if status == CaseStatus.SCHEDULED:
            cases_for_shift[c["shift_id"]].append(case)

    for shift_id, meta in shift_meta.items():
        shift = scheduler.build_shift(
            shift_id=shift_id,
            district=meta["district"],
            date=meta["date"],
            cases=cases_for_shift[shift_id],
            capacity_units=meta["capacity_units"],
        )
        _shifts[shift_id] = shift

    _next_seq = len(_cases) + 1
    _loaded = True


def all_shifts() -> list[Shift]:
    ensure_loaded()
    return list(_shifts.values())


def get_shift(shift_id: str) -> Shift | None:
    ensure_loaded()
    return _shifts.get(shift_id)


def put_shift(shift: Shift) -> None:
    """寫回更新後的 Shift（例如 apply_insertion 的結果）。"""
    ensure_loaded()
    _shifts[shift.id] = shift


def today_shift(district: str) -> Shift | None:
    ensure_loaded()
    shift_id = _shift_index.get((district, "today"))
    return _shifts.get(shift_id) if shift_id else None


def next_day_shift(district: str) -> Shift | None:
    ensure_loaded()
    shift_id = _shift_index.get((district, "tomorrow"))
    return _shifts.get(shift_id) if shift_id else None


def add_case(case: Case) -> None:
    """現場即時追加的案件（spec.md §8.3），存進記憶體供後續查詢/排程使用。"""
    ensure_loaded()
    _cases[case.id] = case


def sync_case_in_shifts(case: Case) -> None:
    """
    案件已經排進某個班次之後，Shift.stops[].case 是那個當下的完整快照，
    不是參照——之後這筆案件的欄位再變（例如班長標記開始清運/已收運），
    _cases 這份 store 更新了，但 Shift.stops 裡嵌的那份不會跟著動，
    兩邊會分岔。update_case_status() 改狀態後要呼叫這個函式，把案件所在
    的那個 Stop 也一起換成新版本，班長端讀 /api/schedule 時兩邊資料
    才會一致。
    """
    ensure_loaded()
    for shift in _shifts.values():
        for i, stop in enumerate(shift.stops):
            if stop.case.id == case.id:
                new_stops = list(shift.stops)
                new_stops[i] = stop.model_copy(update={"case": case})
                _shifts[shift.id] = shift.model_copy(update={"stops": new_stops})
                return


def get_case(case_id: str) -> Case | None:
    ensure_loaded()
    return _cases.get(case_id)


def pending_review() -> list[Case]:
    """needs_review 待審佇列（spec.md §6.1），交班長裁量。"""
    ensure_loaded()
    return [case for case in _cases.values() if case.status == CaseStatus.PENDING]


def completed_cases() -> list[Case]:
    """
    今日已完成案件，供班長端「今日已完成」區塊顯示。特別是現場複核
    直接核准（見 main.py review_case）的案件從沒被排進任何 Shift.stops，
    完成後只有 _cases 這份記錄看得到，不能只從 all_shifts() 找。
    """
    ensure_loaded()
    return [case for case in _cases.values() if case.status == CaseStatus.COMPLETED]


def next_case_id() -> str:
    """接續 fixture 裡最大的 id 序號，現場追加案件用。"""
    ensure_loaded()
    global _next_seq
    with _seq_lock:
        case_id = f"C{_next_seq:02d}"
        _next_seq += 1
    return case_id