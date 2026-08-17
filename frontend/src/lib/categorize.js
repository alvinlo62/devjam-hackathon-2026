// 品項分類，僅供班長端圓餅圖顯示分組用 —— 鏡射自 backend/data/rules.py 的
// ACCEPTED_ITEMS / ITEM_ALIASES（✅ 官方公告品項清單 + 🔧 別名對照）。
// 這裡不做資格判定，資格判定仍完全由後端 services/ 負責；
// 這份對照表只是把同一份真實資料拿來畫圖，不是新規則。
// special_handling（含冷媒需特殊處理）直接讀後端回傳的 item.attributes，
// 不在這裡重新判斷，避免前端自己猜。

const ITEM_ALIASES = {
  辦公椅: '桌椅', 電腦椅: '桌椅', 餐椅: '桌椅',
  書桌: '桌椅', 餐桌: '桌椅', 椅子: '桌椅', 桌子: '桌椅',
  沙發椅: '沙發', 沙發床: '沙發',
  床墊: '彈簧床墊', 床架: '床組',
  冰箱: '電冰箱', 分離式冷氣: '冷氣機', 電視: '電視機',
}

const FURNITURE = new Set([
  '彈簧床墊', '床組', '手推車', '電風扇', '沙發', '桌椅', '櫥櫃',
])
const CYCLES = new Set(['腳踏車', '電動腳踏車', '微型電動二輪車'])
const APPLIANCES = new Set([
  '抽油煙機', '瓦斯爐', '大型飲水機', '電視機', '電冰箱',
  '洗衣機', '冷氣機', '立燈', '落地燈',
])

// 色票取自 frontend/reference/班長端.html 的環圈圖（色盲安全檢核過的配色）。
export const CATEGORY_COLORS = {
  furniture: '#008f74',
  appliance: '#d19a3a',
  appliance_special: '#4a86d6',
  cycle: '#6f47a3',
  other: '#9ca3af',
}

export const CATEGORY_LABELS = {
  furniture: '家具類',
  appliance: '一般家電',
  appliance_special: '含冷媒家電',
  cycle: '自行車與金屬物',
  other: '其他',
}

export function categorizeItem(item) {
  const canonical = ITEM_ALIASES[item.name] ?? item.name
  if (item.attributes?.special_handling) return 'appliance_special'
  if (APPLIANCES.has(canonical)) return 'appliance'
  if (CYCLES.has(canonical)) return 'cycle'
  if (FURNITURE.has(canonical)) return 'furniture'
  return 'other'
}

// items: WasteItem[]（可能跨多個案件），回傳依分類彙總的陣列，供圓餅圖與圖例使用。
export function summarizeCategories(items) {
  const counts = new Map()
  for (const item of items) {
    const key = categorizeItem(item)
    counts.set(key, (counts.get(key) ?? 0) + (item.quantity ?? 1))
  }
  const total = [...counts.values()].reduce((a, b) => a + b, 0)
  return [...counts.entries()]
    .map(([key, count]) => ({
      key,
      label: CATEGORY_LABELS[key],
      color: CATEGORY_COLORS[key],
      count,
      pct: total ? (count / total) * 100 : 0,
    }))
    .sort((a, b) => b.count - a.count)
}

// 環圈圖的 stroke-dasharray／stroke-dashoffset 算法，鏡射自
// frontend/reference/班長端.html 的 SVG 環圈圖片段（circle + rotate(-90) 起點在 12 點鐘方向）。
export function donutSlices(breakdown, radius = 54) {
  const circumference = 2 * Math.PI * radius
  let acc = 0
  return breakdown.map((b) => {
    const length = (b.pct / 100) * circumference
    const slice = {
      ...b,
      dasharray: `${length} ${circumference - length}`,
      dashoffset: -acc,
    }
    acc += length
    return slice
  })
}