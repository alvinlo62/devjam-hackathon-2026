// 示範案例：純前端假資料，不打真的後端。
//
// 原本試過把插畫轉成 JPEG 真的送進 Gemini 辨識，但實測 3 張參考設計的
// 插畫裡有 2 張「看不出品項」（抽象向量圖形，不是真照片，辨識率不穩定）；
// 而且示範案例本來的用途就是「不用真照片也能看完整流程」，用真 API 反而
// 多了辨識失敗風險、還要等真的網路來回。所以這裡直接組出跟真實
// POST /api/cases 回傳一模一樣形狀的 Message/Case（見 backend/models.py），
// 純前端組資料、完全不呼叫後端。
export const DEMO_CASES = [
  {
    name: '兩只行李箱',
    sub: '規則案例・未達門檻',
    src: 'data:image/svg+xml;charset=UTF-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20800%20560%22%3E%3Crect%20width%3D%22800%22%20height%3D%22560%22%20fill%3D%22%23e8edf2%22%2F%3E%3Crect%20y%3D%22380%22%20width%3D%22800%22%20height%3D%22180%22%20fill%3D%22%23a8b1b9%22%2F%3E%3Crect%20x%3D%22132%22%20y%3D%22155%22%20width%3D%22220%22%20height%3D%22300%22%20rx%3D%2228%22%20fill%3D%22%23405b68%22%2F%3E%3Crect%20x%3D%22438%22%20y%3D%22190%22%20width%3D%22196%22%20height%3D%22265%22%20rx%3D%2228%22%20fill%3D%22%23c77650%22%2F%3E%3Cpath%20d%3D%22M195%20155v-58h94v58M493%20190v-55h87v55%22%20fill%3D%22none%22%20stroke%3D%22%23263943%22%20stroke-width%3D%2216%22%2F%3E%3Cpath%20d%3D%22M186%20190v230M297%20190v230M485%20220v200M587%20220v200%22%20stroke%3D%22%23fff%22%20stroke-opacity%3D%22.24%22%20stroke-width%3D%228%22%2F%3E%3Ccircle%20cx%3D%22184%22%20cy%3D%22465%22%20r%3D%2218%22%20fill%3D%22%23263238%22%2F%3E%3Ccircle%20cx%3D%22304%22%20cy%3D%22465%22%20r%3D%2218%22%20fill%3D%22%23263238%22%2F%3E%3Ccircle%20cx%3D%22486%22%20cy%3D%22465%22%20r%3D%2218%22%20fill%3D%22%23263238%22%2F%3E%3Ccircle%20cx%3D%22590%22%20cy%3D%22465%22%20r%3D%2218%22%20fill%3D%22%23263238%22%2F%3E%3C%2Fsvg%3E',
    // 這組數字是真的實測結果照抄下來的（同一張插畫轉成 JPEG 送進真的
    // classify_photo() 跑出來的結果），不是憑空編的。
    case: {
      id: 'DEMO-01',
      location: { address: '示範地址（未實際送出）', district: '信義區', lat: 25.033, lng: 121.5654 },
      items: [{ name: '廢行李箱', category: '其他', quantity: 2, confidence: 0.92 }],
      eligibility: {
        status: 'ineligible',
        reasons: ['「廢行李箱」數量 2 只，未達 3 只（含）以上門檻'],
        rule_refs: [],
        clarification_needed: false,
      },
      status: 'rejected',
      resource_hint: null,
      note: null,
      trace: [],
    },
  },
]
