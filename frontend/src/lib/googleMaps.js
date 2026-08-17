// Google Maps JavaScript API（Places library）動態載入，只載入一次
// （多個元件掛載/卸載共用同一個 script tag，不重複注入）。
let loadPromise = null

export function loadGooglePlaces() {
  if (loadPromise) return loadPromise

  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY
  if (!apiKey) {
    return Promise.reject(new Error('缺少 VITE_GOOGLE_MAPS_API_KEY，無法載入地址選點'))
  }

  loadPromise = new Promise((resolve, reject) => {
    if (window.google?.maps?.places) {
      resolve(window.google.maps.places)
      return
    }
    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places&language=zh-TW&region=TW`
    script.async = true
    script.onload = () => {
      if (window.google?.maps?.places) resolve(window.google.maps.places)
      else reject(new Error('Google Maps 已載入，但 Places library 不存在'))
    }
    script.onerror = () => reject(new Error('Google Maps 腳本載入失敗，請確認金鑰或網路'))
    document.head.appendChild(script)
  })

  return loadPromise
}

// 跟 loadGooglePlaces 共用同一個 <script> 注入（loadPromise 只會建立一次），
// 差別只是回傳 window.google.maps 這個基礎命名空間（Map/Marker/Polyline/
// InfoWindow 都在這裡），不是 .places 子命名空間——路線地圖用這個。
export async function loadGoogleMaps() {
  await loadGooglePlaces()
  return window.google.maps
}

// 台北市地址的行政區在 Google 的分類裡是 administrative_area_level_2
// 或（某些回傳格式）sublocality_level_1，兩種都試，抓不到就回 null，
// 由呼叫端決定要不要用民眾自己選的行政區當備援。
export function extractDistrict(place) {
  const comp = place.address_components?.find(
    (c) => c.types.includes('administrative_area_level_2') || c.types.includes('sublocality_level_1'),
  )
  return comp?.long_name ?? null
}
