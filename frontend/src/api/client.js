// 對接 docs/api.md 的實際契約。統一外殼 { ok, data, error }，這裡拆開，
// 成功回傳 data，失敗丟出 Error，呼叫端用 try/catch 處理。
const BASE = import.meta.env.VITE_API_BASE || '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  let body
  try {
    body = await res.json()
  } catch {
    throw new Error(`伺服器回應格式錯誤（${res.status}）`)
  }
  if (!body.ok) throw new Error(body.error || '請求失敗')
  return body.data
}

export const api = {
  health: () => request('/health'),
  applicantTypes: () => request('/applicant-types'),
  schedule: () => request('/schedule'),
  submitCase: (payload) => request('/cases', { method: 'POST', body: JSON.stringify(payload) }),
  classifyPhoto: (payload) => request('/photo/classify', { method: 'POST', body: JSON.stringify(payload) }),
  getCase: (caseId) => request(`/cases/${caseId}`),
  updateCaseStatus: (payload) =>
    request('/cases/status', { method: 'POST', body: JSON.stringify(payload) }),
  reviewCase: (payload) =>
    request('/cases/review', { method: 'POST', body: JSON.stringify(payload) }),
  proposeInsertion: (payload) =>
    request('/insertion/propose', { method: 'POST', body: JSON.stringify(payload) }),
  acceptInsertion: (payload) =>
    request('/insertion/accept', { method: 'POST', body: JSON.stringify(payload) }),
  reset: () => request('/reset', { method: 'POST' }),
}

// image_base64 欄位要求「純 base64，不含 data: 前綴」（見 docs/api.md）。
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}