import CaseCard from './CaseCard.jsx'
import TraceList from './TraceList.jsx'

// 訊息流的最小渲染單位（spec.md §3.1, §5.3）。type 決定要看哪個欄位，
// 跟 models.MessageBlock 的設計一致。視覺外殼對應 frontend/reference/民眾端.html
// 的 .text-block / .choices-block / .result-card 系統。
export default function MessageBlock({ block, onChoice, disabled }) {
  switch (block.type) {
    case 'text':
      return <div className="text-block">{block.content}</div>

    case 'choices':
      return (
        <div className="choices-block">
          {block.question && <h2>{block.question}</h2>}
          <div className="choice-list">
            {block.options?.map((opt) => (
              <button
                key={opt.value}
                className="choice-button"
                disabled={disabled}
                onClick={() => onChoice?.(opt.value)}
              >
                <strong>{opt.label}</strong>
                <span className="choice-button__arrow">→</span>
              </button>
            ))}
          </div>
        </div>
      )

    case 'upload':
      return <div className="text-block text-block--info">{block.content}</div>

    case 'result':
      return <CaseCard case_={block.case} />

    case 'trace':
      return (
        <div className="block-stack">
          <TraceList steps={block.trace} variant="decision" />
        </div>
      )

    default:
      return null
  }
}
