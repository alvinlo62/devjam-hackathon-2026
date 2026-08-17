"""
前後端契約，也是 ai/ 與 services/ 之間傳遞的資料形狀。

改這裡 = 前後端都要改，成本最高。修改前必須先問（見 AGENTS.md）。

只定義資料形狀，不放任何判定/計算邏輯——邏輯屬於 services/，
ai/ 只負責填值與講解，不得反過來覆寫這裡定義的欄位語意。
"""
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field


# ==================== 列舉 ====================

class Eligibility(str, Enum):
    """
    資格判定的三種狀態。刻意設計為三態，不可簡化為二態（合格/不合格）。

    理由（spec.md §6.1, §6.4）：規則含有查不到資料的裁量條款
    （例如「是否為裝修業主修繕」無資料庫可查），若只有二態，
    系統只能亂猜或誤判成「合格」，一旦民眾依指示棄置卻遭拒收，
    可能因此受罰。needs_review 讓系統誠實承認「這件判不了」，
    交給清潔隊班長裁量，而不是假裝全自動。
    """
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NEEDS_REVIEW = "needs_review"


class WeightBand(str, Enum):
    """物品重量級距，屬性標記用，非精確秤重。"""
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


class BlockType(str, Enum):
    """
    訊息流區塊型態（spec.md §3.1）。民眾端與班長端共用同一套區塊渲染邏輯。

    trace 是政府端專用的決策軌跡區塊（spec.md §5.3），
    與民眾端的 text/choices/upload/result 並列，讓兩端能重用同一份
    「把 agent 每一步渲染成區塊」的前端邏輯。
    """
    TEXT = "text"
    CHOICES = "choices"
    UPLOAD = "upload"
    RESULT = "result"
    TRACE = "trace"


class CaseStatus(str, Enum):
    """
    案件生命週期狀態。

    pending    — 剛送出，尚未排入任何班次（含 needs_review 待審中的案件）
    scheduled  — 已排入某班次的路線（班長按接受，見 /api/insertion/accept）
    deferred   — 因當班超載，改排至明日班次（spec.md §4.2 的「建議移至明日」）
    rejected   — 判定 ineligible，不進入排程
    collecting — 班長手動標記「開始清運」，車輛已在處理這一站
    completed  — 班長手動標記「已收運」

    collecting/completed 是民眾端進度同步用（送出後同一頁面顯示
    已送出→已排程→清運中→已完成），觸發方式是班長手動點按（每一站
    各自獨立標記），不是自動依日期/時間推斷——見 /api/cases/status。
    """
    PENDING = "pending"
    SCHEDULED = "scheduled"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    COLLECTING = "collecting"
    COMPLETED = "completed"


# ==================== 領域模型 ====================

class Location(BaseModel):
    """案件地點。district 用於分組排班（spec.md §4.1 行政區分組，查表非演算法）。"""
    address: str
    district: str
    lat: float
    lng: float


class ItemAttributes(BaseModel):
    """
    物品客觀屬性標記（spec.md §7.1）。

    這裡只放「觀察」（事實），不放「建議」（例如建議配置幾人搬運）。
    建議文字由 ai/ 依這些屬性生成，明確標註為系統參考值，
    避免主張「無來源依據」的具體工具/人力清單。
    """
    weight_band: WeightBand
    max_dimension_cm: float
    dismantlable: bool
    special_handling: bool  # 含冷媒等需特殊處理設備（spec.md §7.2）
    volume_units: float     # 用於載重加總（Shift.used_units）
    material: str | None = None  # 常識推估的材質組成，跟 weight_band/
    # max_dimension_cm 同一等級的「系統參考值」，非官方規範（見 data/rules.py）


class WasteItem(BaseModel):
    """單一廢棄物品項，多半來自 Gemini 視覺辨識（spec.md §5.1 環節 1）。"""
    name: str
    category: str
    quantity: int = 1
    confidence: float = Field(ge=0, le=1, default=1.0)
    attributes: ItemAttributes | None = None  # 辨識當下若資訊不足可能尚未算出


class ItemEligibility(BaseModel):
    """
    單一品項的資格判定明細。

    案件整體狀態（EligibilityResult.status）是取所有品項裡最嚴重者的彙整，
    這個型別讓班長端能標示「第幾項有問題」，而不是只看到案件層級的單一狀態。
    """
    item_index: int  # 對應 Case.items 的索引
    item_name: str
    status: Eligibility
    reasons: list[str] = []
    rule_refs: list[str] = []


class EligibilityResult(BaseModel):
    """
    資格判定結果，一律由 services/eligibility.py 產出（spec.md §5.1 環節 2）。

    reasons 與 rule_refs 讓判定「逐條可追溯」，畫面上可標註
    「初步判定，實際以清潔隊認定為準」（spec.md §10.2 風險對策）。
    """
    status: Eligibility                 # 案件層級彙整（取所有品項最嚴重者）
    reasons: list[str] = []             # 人話說明，可能會顯示給使用者看
    # 內部除錯/測試追溯用，標出每條 reasons 對應哪個規則來源
    # （data/rules.py 常數或本專案規格章節），不對外顯示。
    rule_refs: list[str] = []
    clarification_needed: bool = False  # 是否需要 agent 向民眾追問（見 §6.3 裝潢廢料流程）
    items: list[ItemEligibility] = []   # 逐品項判定明細


# ==================== Agent ====================
# TraceStep 定義在這裡（而不是排在 Stop/Shift/InsertionPlan 之後），
# 是因為下面的 Case 需要引用它存放 trace 欄位；Agent 概念上仍屬於
# 「訊息流／agent」那一群，只是提前宣告避免前向參照。

class TraceStep(BaseModel):
    """
    決策軌跡面板的單一步驟（spec.md §5.3），本專案最重要的 UI 元件的資料來源。

    is_pivot 標記 agent「改變計畫」的關鍵步驟——例如 check_capacity
    回傳超載後，agent 自行決定改呼叫 query_next_day，而非照原計畫塞入
    當班（spec.md §5.2「超載 → 於是改查明日」即為 agent 自主決策的證據）。
    此欄位讓前端能特別標示這一行（entry 動畫、顏色強調），
    不需要前端自己猜哪一步是「轉折點」。
    """
    icon: str
    action: str
    detail: str
    tool: str | None = None   # 對應呼叫的 services/ai 工具名稱，例如 check_capacity
    is_pivot: bool = False


class Case(BaseModel):
    """一筆清運案件，貫穿民眾端送件與班長端排程兩端。"""
    id: str
    location: Location
    items: list[WasteItem]
    eligibility: EligibilityResult | None = None  # 送出當下尚未判定時為 None
    status: CaseStatus = CaseStatus.PENDING
    resource_hint: str | None = None  # AI 生成的資源建議白話文（例如建議配置人力）
    note: str | None = None           # 民眾補充說明或裁量備註
    # 民眾指定的清運日偏好（"today" | "tomorrow"），送件當下就決定，
    # 不是 agent 反應式追問出來的，跟 applicant_type 同一類輸入。
    # agent 會優先試這一天，該天班次滿了才改排另一天並告知民眾
    # （見 ai/agent.py run_scripted 的查詢順序、main.py 的排程結果文案）。
    preferred_day: str | None = None
    # agent 建議插入的班次日期（YYYY-MM-DD），來自 query_shifts 最後一次
    # 成功查到班次的結果。status 停在 PENDING 時（尚未由班長人工接受，
    # 見 spec.md §4.4）這是唯一能告訴民眾「系統打算排哪一天」的欄位；
    # 一旦被接受插入，改看 Stop 所在的 Shift.date 才是真的排定日期。
    proposed_date: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    # agent 處理這筆案件時收集的完整決策軌跡（spec.md §5.3），跟著案件存下來，
    # 讓班長端事後也能看到，不是只存在送件當下那次 API response 裡。
    trace: list[TraceStep] = []


# ==================== 排程 ====================

class Stop(BaseModel):
    """路線上的一站，對應一筆已排入班次的案件。"""
    seq: int             # 站序，第 1 站、第 2 站...
    case: Case
    eta_minutes: float   # 預估抵達此站所需時間（累計）


class Shift(BaseModel):
    """
    一個班次（單車、單一行政區、單日）。對應 spec.md §4.1 的
    「單車路線排序 + 行政區分組」，不做跨區多車分派（VRP）。
    """
    id: str
    district: str
    date: str  # YYYY-MM-DD；比賽時間有限，用字串而非 date 型別省去序列化麻煩
    capacity_units: float
    used_units: float = 0.0
    stops: list[Stop] = []
    total_minutes: float = 0.0

    # @computed_field（不是普通 @property）：pydantic 預設不會把純
    # @property 序列化進 model_dump()/JSON，前端會拿不到這兩個欄位、
    # 得自己重算 used_units / capacity_units。這裡明確標成 computed
    # field，讓 API 回應直接帶著算好的值，不用前後端各算一次。
    @computed_field
    @property
    def load_ratio(self) -> float:
        """已用容量佔比，例如 0.96 代表 96%（spec.md §4.2）。"""
        if self.capacity_units <= 0:
            return 0.0
        return self.used_units / self.capacity_units

    @computed_field
    @property
    def overloaded(self) -> bool:
        """超過容量閾值即為超載，觸發畫面紅色警示與 agent 改查明日班次。"""
        return self.load_ratio > 1.0


class InsertionPlan(BaseModel):
    """
    新案件插入某班次的成本試算結果（spec.md §4.4）。

    只顯示建議、不自動生效——feasible=False 時代表會導致超載，
    agent 應改呼叫 query_next_day 而非硬塞（spec.md §5.2 關鍵決策點）。
    """
    shift_id: str
    position: int             # 建議插入在第幾站之後
    added_minutes: float      # 插入後總時間 − 原總時間
    resulting_load_ratio: float
    feasible: bool
    reason: str | None = None


# ==================== 訊息流 ====================

class Choice(BaseModel):
    """choices 區塊裡的單一選項按鈕。"""
    label: str
    value: str


class MessageBlock(BaseModel):
    """
    訊息流的最小渲染單位，民眾端與班長端共用（spec.md §3.1, §5.3）。

    欄位依 type 選擇性使用：
    - text     → content
    - choices  → question, options
    - upload   → content（提示文字）
    - result   → case
    - trace    → trace
    """
    type: BlockType
    content: str | None = None
    question: str | None = None
    options: list[Choice] | None = None
    case: Case | None = None
    trace: list[TraceStep] | None = None


class Message(BaseModel):
    """訊息流裡的一則訊息，由多個區塊組成。"""
    role: Literal["user", "agent"]
    blocks: list[MessageBlock]


# ==================== API ====================

class ApiResponse(BaseModel):
    """所有 endpoint 統一用這個外殼包，前端只要寫一套錯誤處理。"""
    ok: bool = True
    data: Any | None = None
    error: str | None = None


class SubmitCaseRequest(BaseModel):
    """
    民眾端送件（spec.md §3.1）。輸入以點擊為主，自由輸入僅供補充說明。

    case_id 與 answers 用於支援單一案件內的多輪追問（例如 §6.3
    裝潢廢料來源提問），並非 spec.md §3.1 明確禁止的「多輪上下文持久化」
    ——同一案件流程內的往返，送完即結束，不做跨案件的歷史記錄。
    此為補充假設，spec 未列出本 request 的完整欄位。
    """
    case_id: str | None = None  # 續答同一案件的追問時帶入；首次送件為 None
    image_base64: str | None = None
    location: Location | None = None
    note: str | None = None
    answers: dict[str, str] = {}  # 對 agent 追問的回覆，例如 {"decoration_source": "self"}
    # 申請人身份（spec.md §6.2 服務對象限一般家庭及住戶）。跟 answers 不同，
    # 這是判定資格「之前」就要知道的輸入，不是 agent 反應式追問出來的；
    # 預設值只是前端沒送這欄位時的備援，不是強制值。選項清單見
    # GET /api/applicant-types（data.rules.EXCLUDED_APPLICANTS）。
    applicant_type: str = "household"
    # 民眾指定的清運日偏好（"today" | "tomorrow"），只在首次送件時有意義；
    # 續答追問時從已存的 Case.preferred_day 讀，不靠前端重送這個欄位。
    preferred_day: str | None = None
    # 前端在「確認資料」頁面已經先呼叫過 POST /api/photo/classify 拿到
    # 辨識結果時帶入，讓這裡不用重跑一次 classify_photo（省一次 Gemini
    # 呼叫，也避免同一張照片辨識兩次可能得到不完全一樣的結果）。有給
    # 這個欄位就不會再看 image_base64；沒給且沒有 image_base64 才會退回
    # 文字猜測（_guess_items_from_text）。
    items: list[WasteItem] | None = None


class SubmitCaseResponse(BaseModel):
    """民眾端送件的回應，可能是追問（choices）或最終判定結果（result）。"""
    message: Message
    case: Case | None = None  # 已產生案件時附上，尚在追問中則為 None


class ClassifyPhotoRequest(BaseModel):
    """民眾端「確認資料」頁面用：只辨識照片、算屬性，不建立案件。"""
    image_base64: str


class ClassifyPhotoResponse(BaseModel):
    """辨識結果（含屬性），供確認頁面顯示「照片觀察」；不含資格判定。"""
    items: list[WasteItem]


class ScheduleResponse(BaseModel):
    """班長儀表板讀取今日排程（spec.md §3.2）。"""
    shifts: list[Shift]
    pending_review: list[Case] = []  # needs_review 待審佇列（spec.md §6.1）
    # 已完成的案件，供「今日已完成」區塊顯示。特別是現場複核直接核准的
    # 案件（見 POST /api/cases/review）從沒被排進任何 Shift.stops，
    # 完成後只有這裡看得到，不加這個欄位會完全找不到那些案件。
    completed: list[Case] = []


class ProposeInsertionRequest(BaseModel):
    """向某班次試算插入成本（spec.md §4.4）。"""
    case_id: str
    shift_id: str


class ProposeInsertionResponse(BaseModel):
    """
    插入試算結果，連同決策軌跡一併回傳（spec.md §5.3 補充：
    不需 streaming，後端把步驟收集為陣列，前端逐行動畫顯示）。
    """
    plan: InsertionPlan
    trace: list[TraceStep] = []


class AcceptInsertionRequest(BaseModel):
    """班長點擊接受建議，路線更新（spec.md §4.4，人工接受，不全自動）。"""
    case_id: str
    shift_id: str
    position: int


class UpdateCaseStatusRequest(BaseModel):
    """
    班長手動標記案件進度（開始清運/已收運）。只接受 CaseStatus.COLLECTING /
    COMPLETED——其餘狀態轉換各自有專屬流程（送件走 ai/agent.run()，
    排入班次走 AcceptInsertionRequest），不透過這支通用改。
    """
    case_id: str
    status: CaseStatus


class ReviewCaseRequest(BaseModel):
    """
    班長現場複核 needs_review 案件（spec.md §6.1：規則含裁量條款，
    查不到資料的案件由系統誠實承認「判不了」，交清潔隊班長現場裁量，
    不是系統幫忙猜——這支端點就是那個裁量動作的出口）。
    """
    case_id: str
    approved: bool          # True＝現場確認可收運，False＝確認不可收運
    note: str | None = None  # 複核備註，選填