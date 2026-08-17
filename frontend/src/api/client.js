// 所有後端呼叫集中在這一支。換 URL、加 header、統一錯誤處理都只改這裡。
const BASE = import.meta.env.VITE_API_BASE || '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  // 後端統一用 ApiResponse 外殼包，錯誤也是，所以要先試著解出 body
  // 才知道有沒有 json.error 可以顯示（例如 429 的「請求太頻繁」）。
  // body 不是合法 JSON（例如非 app 產生的錯誤頁）才退回純 HTTP 狀態碼。
  let json
  try {
    json = await res.json()
  } catch {
    throw new Error(`HTTP ${res.status}`)
  }

  if (!res.ok || !json.ok) throw new Error(json.error || `HTTP ${res.status}`)
  return json.data
}

export const api = {
  health: () => request('/health'),
  analyze: (payload) =>
    request('/analyze', { method: 'POST', body: JSON.stringify(payload) }),
}

// 圖片轉 base64，去掉 data URL 前綴（後端要的是純 base64）
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result.split(',')[1])
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}
