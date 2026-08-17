// 決策軌跡面板（spec.md §5.3，本專案最重要的 UI 元件）。
// 民眾端跟班長端共用同一份資料跟邏輯，只是視覺外殼不同（variant）：
// 民眾端用 .decision-step（單畫面逐題卡片風格），
// 班長端用 .trace-step（調度決策紀錄時間軸風格）。
// is_pivot 標出「超載→改查明日」這類 agent 自己改變計畫的關鍵步驟，
// 不需要前端自己猜哪一步是轉折點。
export default function TraceList({ steps, variant = 'dashboard' }) {
  if (!steps || steps.length === 0) {
    return variant === 'dashboard' ? <p className="trace-placeholder">尚無決策紀錄</p> : null
  }

  if (variant === 'decision') {
    return (
      <>
        {steps.map((step, i) => (
          <div
            key={i}
            className={`decision-step decision-step--done${step.is_pivot ? ' decision-step--pivot' : ''}`}
          >
            <span className="decision-icon">{step.icon}</span>
            <span>
              <strong>{step.action}</strong>
              <small>{step.detail}</small>
            </span>
          </div>
        ))}
      </>
    )
  }

  return (
    <div className="trace-list">
      {steps.map((step, i) => (
        <div key={i} className={`trace-step${step.is_pivot ? ' trace-step--warning' : ''}`}>
          <span>{step.icon}</span>
          <div>
            <strong>{step.action}</strong>
            <p>{step.detail}</p>
          </div>
          {i < steps.length - 1 && <i />}
        </div>
      ))}
    </div>
  )
}
