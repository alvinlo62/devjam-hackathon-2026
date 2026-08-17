"""
大型廢棄物收運規則表（純資料，無邏輯）：資格判定 + 品項屬性 + 清潔隊駐地。

來源分四種，逐條標註：
- ✅ 轉錄自 docs/spec.md §6.2（該文件標示「已確認，來源：臺北市環保局常見問答」）
- 🔧 本專案為了讓 agent 能觸發追問/分類而設計的關鍵字啟發式，
  不是法規原文的窮舉，僅供 Demo 判斷用，之後應以官方公告校正
- 📏 常識推估的物理屬性（重量、尺寸），非官方規範，僅供 Demo 呈現，
  spec.md §7.1 明講這類數字沒有來源依據，畫面上只能當「系統參考值」
- 📍 地址查證自臺北市環保局清潔隊聯絡資訊頁（見 SOURCE_URLS["depot_directory"]），
  但經緯度是用 OpenStreetMap Nominatim 對「街道」查詢得到的近似值，
  查不到精確門牌號碼，只有街道等級的精度，不是精確地理編碼結果，見下方註解

★ 未經查證的內容一律標 TODO，不得自行編造數值（尤其罰則金額，
  spec.md §6.4 已標示 ⚠️ 待查證，本檔案不引用）。
"""
from models import Location, WeightBand

# ---------- ✅ 收運品項清單（spec.md §6.2）----------
# 分類 -> 品項名稱清單。用於資格判定的「在清單內即 eligible」判斷。
ACCEPTED_ITEMS: dict[str, list[str]] = {
    "廢棄家具": [
        "彈簧床墊", "床組", "手推車", "腳踏車", "電動腳踏車",
        "微型電動二輪車", "電風扇", "沙發", "桌椅", "櫥櫃",
    ],
    "家電用品": [
        "抽油煙機", "瓦斯爐", "大型飲水機", "電視機", "電冰箱",
        "洗衣機", "冷氣機", "立燈", "落地燈",
    ],
    "其他": [
        "樹枝",
        "廢行李箱",  # 需另達 QUANTITY_THRESHOLDS 門檻才算，見下
    ],
}

# ---------- 🔧 品項別名對照（Gemini 辨識用詞 -> 公告清單精確字串）----------
# 不是官方清單，是本專案的設計：Gemini 照實描述照片內容，不會自動套用
# 公告用詞（例如照片是辦公椅，它就講「辦公椅」，不會自己聯想成「桌椅」），
# 但 ACCEPTED_ITEMS 是精確字串比對。這裡列常見別名，判定前先轉成公告
# 清單裡的名稱，兩者是同一類物品、不是新增規則。查不到別名時比對邏輯
# 退回用原始名稱，不影響既有行為。
ITEM_ALIASES: dict[str, str] = {
    "辦公椅": "桌椅", "電腦椅": "桌椅", "餐椅": "桌椅",
    "書桌": "桌椅", "餐桌": "桌椅", "椅子": "桌椅", "桌子": "桌椅",
    "沙發椅": "沙發", "沙發床": "沙發",
    "床墊": "彈簧床墊", "床架": "床組",
    "冰箱": "電冰箱", "分離式冷氣": "冷氣機", "電視": "電視機",
}

# ---------- ✅ 數量門檻（spec.md §6.2「明確門檻」）----------
# 品項名稱 -> 最低收運數量（含）。低於此數量視為不合格。
QUANTITY_THRESHOLDS: dict[str, int] = {
    "廢行李箱": 3,  # 3 只（含）以上才算
}

# ---------- ✅ 排除申請對象（spec.md §6.2）----------
# 服務對象限「一般家庭及住戶」，以下代碼一律 ineligible。
# household（一般家庭）不在此表中，為預設可服務對象。
EXCLUDED_APPLICANTS: dict[str, str] = {
    "commercial_household": "住家兼營商業",
    "institution": "機構",
    "school": "學校",
    "military": "部隊",
    "corporate": "法人",
}

# ✅ 排除對象的轉介管道（來源見 SOURCE_URLS["excluded_applicant_referral"]）。
# 原文：「應由其所有人委託合格之代清除處理機構清運」，查詢窗口為廢棄物處理公會。
# 用於 ineligible 理由文字，對應 spec.md §6.3「請廠商施工 → ineligible
# （告知委託合格清除業者管道）」同一個設計需求。
EXCLUDED_APPLICANT_REFERRAL = "應由所有人委託合格之代清除處理機構清運，可洽廢棄物處理公會查詢業者資訊（電話 2828-5177）"

# ---------- ✅ 服務時間（spec.md §6.2）----------
SUNDAY_NO_SERVICE = True       # 週日不收運
MIN_ADVANCE_DAYS = 1           # 至少提前一日預約
# ⚠️ spec.md 原文為「多數區」要求 21 時後排出，非全區一致；
# TODO：各行政區可能有例外時段，需向環保局逐區確認後再拆成 dict。
NIGHT_HOUR_AFTER = 21

# ---------- 🔧 石材類關鍵字（裁量條款排除項，spec.md §6.2「非石材類」）----------
# spec.md 只寫「非石材類」，未窮舉「石材類」的具體品項定義。
# TODO：需向環保局確認「石材類」的正式範圍，以下為 Demo 用推斷清單，
# 不得視為官方定義。
STONE_KEYWORDS: list[str] = ["石材", "大理石", "花崗岩", "磁磚", "洗石子", "石英"]

# ---------- 🔧 裝潢廢料關鍵字（觸發 agent 追問，spec.md §6.3）----------
# 用於偵測「疑似裝潢廢料」以觸發追問流程，非法規清單本身，
# 純粹是本專案的關鍵字啟發式設計，之後可依實測擴充。
RENOVATION_KEYWORDS: list[str] = [
    "木板", "角料", "木作", "系統櫃", "隔間板",
    "天花板板材", "裝潢廢料", "拆除廢料", "矽酸鈣板", "石膏板",
]

# ---------- 📏 品項屬性對照表（spec.md §7.1）----------
# 物品名 -> (重量級距, 最大尺寸cm, 可否拆解, 特殊處理, 容量單位[volume_units])
#
# ⚠️ 重量與尺寸為常識推估，非官方規範或實測數據，僅供 Demo 呈現用。
# 「系統參考值」的定位見 spec.md §7.1：這是觀察（事實），不是主張（建議）；
# 建議文字（人力配置等）由 services/attributes.py 的 resource_hint() 另外產生，
# 不放在這張表裡。
#
# 冰箱、冷氣依 spec.md §7.2 標記 special_handling=True（含冷媒設備，需特殊處理）。
ITEM_ATTRIBUTES: dict[str, tuple[WeightBand, float, bool, bool, float]] = {
    # 廢棄家具
    "彈簧床墊":     (WeightBand.HEAVY,  200.0, False, False, 3.0),
    "床組":         (WeightBand.HEAVY,  200.0, True,  False, 3.5),
    "手推車":       (WeightBand.MEDIUM, 100.0, False, False, 1.0),
    "腳踏車":       (WeightBand.MEDIUM, 170.0, False, False, 1.2),
    "電動腳踏車":   (WeightBand.HEAVY,  170.0, False, False, 1.5),
    "微型電動二輪車": (WeightBand.MEDIUM, 120.0, False, False, 1.0),
    "電風扇":       (WeightBand.LIGHT,  100.0, False, False, 0.5),
    "沙發":         (WeightBand.HEAVY,  200.0, False, False, 4.0),
    "桌椅":         (WeightBand.MEDIUM, 120.0, True,  False, 1.5),
    "櫥櫃":         (WeightBand.HEAVY,  180.0, True,  False, 3.0),
    # 家電用品
    "抽油煙機":     (WeightBand.MEDIUM, 90.0,  False, False, 1.0),
    "瓦斯爐":       (WeightBand.LIGHT,  70.0,  False, False, 0.5),
    "大型飲水機":   (WeightBand.MEDIUM, 100.0, False, False, 1.0),
    "電視機":       (WeightBand.MEDIUM, 140.0, False, False, 1.5),
    "電冰箱":       (WeightBand.HEAVY,  180.0, False, True,  3.0),  # 含冷媒設備
    "洗衣機":       (WeightBand.HEAVY,  90.0,  False, False, 1.5),
    "冷氣機":       (WeightBand.MEDIUM, 90.0,  False, True,  1.5),  # 含冷媒設備
    "立燈":         (WeightBand.LIGHT,  150.0, False, False, 0.3),
    "落地燈":       (WeightBand.LIGHT,  150.0, False, False, 0.3),
    # 其他
    "樹枝":         (WeightBand.LIGHT,  200.0, True,  False, 1.0),
    "廢行李箱":     (WeightBand.LIGHT,  80.0,  False, False, 0.4),
}

# 未知品項（不在上表）的預設值。中等重量、不可拆解、不特殊處理，
# 讓判定退回保守估計，而不是讓程式直接出錯。
DEFAULT_ITEM_ATTRIBUTES: tuple[WeightBand, float, bool, bool, float] = (
    WeightBand.MEDIUM, 100.0, False, False, 1.0,
)

# ---------- 📍 清潔隊駐地（spec.md §4.1 排程起點）----------
# 地址逐字轉錄自 SOURCE_URLS["depot_directory"]。
# 經緯度用 OpenStreetMap Nominatim 查該街道得到的街道等級近似值
# （查不到門牌號碼，Nominatim 對台灣地址的門牌資料很少見），
# 不是精確地理編碼結果，只是比完全瞎猜的座標可信，Demo 前若要
# 更精確（例如串 Google Geocoding API），可以直接替換這裡的 lat/lng，
# 不影響呼叫端的介面。
#
# 目前只查了 spec.md §4.1 範例會用到的三個行政區（信義/大安/松山），
# 其餘行政區未查證，落在 DEFAULT_DEPOT（非真實地址）。
DEPOTS: dict[str, Location] = {
    "信義區": Location(
        address="110台北市信義區福德街86號3樓（信義區清潔隊）",
        district="信義區", lat=25.0363, lng=121.5788,
    ),
    "大安區": Location(
        address="10677臺北市大安區通化街140巷19號（大安區清潔隊）",
        district="大安區", lat=25.0287, lng=121.5538,
    ),
    "松山區": Location(
        address="10574臺北市松山區民生東路四段133號4樓（松山區清潔隊）",
        district="松山區", lat=25.0581, lng=121.5537,
    ),
}

# 未涵蓋在 DEPOTS 裡的行政區用這個 fallback。
# TODO：非真實地址，只是讓排程邏輯在缺資料時仍能跑，不得當作查證資料使用。
DEFAULT_DEPOT = Location(address="清潔隊駐地（未查證，暫用預設值）", district="", lat=25.0375, lng=121.5637)

# ---------- 查證狀態 ----------
# 已比對臺北市環保局公告原文，ACCEPTED_ITEMS / QUANTITY_THRESHOLDS /
# EXCLUDED_APPLICANTS / 服務時間 / EXCLUDED_APPLICANT_REFERRAL / DEPOTS 地址
# 逐字相符。STONE_KEYWORDS 仍待查證：兩篇原文都只寫「非石材類」，
# 未定義石材具體範圍。DEPOTS 的經緯度只是街道等級近似值，非精確地理編碼。
# 罰則金額、代清除業者收費標準原文均未提及，本檔案不引用（見 spec.md §6.4 ⚠️）。
LAST_VERIFIED: str | None = "2026-08-17"
SOURCE_URLS: dict[str, str] = {
    "eligibility_rules": (
        "https://www.dep.gov.taipei/News_Content.aspx"
        "?n=ACEFA960B5A4ACD7&s=402ACF2A9AD6B8EB"
    ),
    "excluded_applicant_referral": (
        "https://www.dep.gov.taipei/News_Content.aspx"
        "?n=ACEFA960B5A4ACD7&s=80BCA379CDB2FF73"
    ),
    "depot_directory": "https://www.dep.gov.taipei/cp.aspx?n=F1AE8510EEF140EF",
}