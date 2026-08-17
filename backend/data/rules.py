"""
大型廢棄物收運資格判定的規則表（純資料，無邏輯）。

來源分兩種，逐條標註：
- ✅ 轉錄自 docs/spec.md §6.2（該文件標示「已確認，來源：臺北市環保局常見問答」）
- 🔧 本專案為了讓 agent 能觸發追問/分類而設計的關鍵字啟發式，
  不是法規原文的窮舉，僅供 Demo 判斷用，之後應以官方公告校正

★ 未經查證的內容一律標 TODO，不得自行編造數值（尤其罰則金額，
  spec.md §6.4 已標示 ⚠️ 待查證，本檔案不引用）。
"""

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

# ---------- 查證狀態 ----------
# 已比對臺北市環保局公告原文，ACCEPTED_ITEMS / QUANTITY_THRESHOLDS /
# EXCLUDED_APPLICANTS / 服務時間 / EXCLUDED_APPLICANT_REFERRAL 逐字相符。
# STONE_KEYWORDS 仍待查證：兩篇原文都只寫「非石材類」，未定義石材具體範圍。
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
}