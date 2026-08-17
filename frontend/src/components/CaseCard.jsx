import TraceList from './TraceList.jsx'

// eligibility.status -> result-card 的視覺變體與文字（對應 frontend/reference 的 .result-card 系統）。
const STATUS_META = {
  eligible: { modifier: '', eyebrow: '符合資格', icon: '✓' },
  ineligible: { modifier: ' result-card--ineligible', eyebrow: '不符合資格', icon: '✕' },
  needs_review: { modifier: ' result-card--needs_review', eyebrow: '需人工複核', icon: '!' },
}

// 案件結果卡片。民眾端「查看結果」步驟用這個渲染 agent 的判定結果。
export default function CaseCard({ case_, showTrace = true }) {
  if (!case_) return null
  const elig = case_.eligibility
  const meta = STATUS_META[elig?.status] ?? STATUS_META.eligible
  const hasSpecialHandling = case_.items?.some((item) => item.attributes?.special_handling)

  return (
    <div className={`result-card${meta.modifier}`}>
      <div className="result-header">
        <span className="result-status-icon">{meta.icon}</span>
        <div>
          <div className="eyebrow">{meta.eyebrow}</div>
          <h2>{case_.id}</h2>
        </div>
      </div>

      <div className="result-section">
        <h3>辨識物品</h3>
        <div className="observation-grid">
          {case_.items?.map((item, i) => (
            <span key={i}>
              {item.name} × {item.quantity}
            </span>
          ))}
        </div>
      </div>

      {elig && (
        <div className="result-section">
          <h3>資格判定依據</h3>
          <ul>
            {elig.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {hasSpecialHandling && (
        <div className="special-handling">⚠ 含冷媒等需特殊處理設備，系統將安排特殊處理流程</div>
      )}

      {case_.resource_hint && (
        <div className="result-section result-suggestion">
          <p>💡 {case_.resource_hint}</p>
        </div>
      )}

      {showTrace && case_.trace?.length > 0 && (
        <div className="result-section">
          <h3>判定過程</h3>
          <div className="block-stack">
            <TraceList steps={case_.trace} variant="decision" />
          </div>
        </div>
      )}

      <p className="disclaimer">本結果為系統初步判定，僅供參考；實際資格與收運安排仍以清潔隊現場複核為準。</p>
    </div>
  )
}
