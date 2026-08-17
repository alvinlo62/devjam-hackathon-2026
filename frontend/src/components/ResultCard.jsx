const LABEL = { pass: '符合', warn: '接近', fail: '不符合' }

export default function ResultCard({ result }) {
  const { item, status, score, reasons, gap } = result
  return (
    <div className={`card result ${status}`}>
      <div className="row">
        <strong>{item.name}</strong>
        <span className={`tag ${status}`}>{LABEL[status]}</span>
      </div>
      <p className="score">分數 {score}</p>
      <ul>
        {reasons.map((r, i) => <li key={i}>{r}</li>)}
      </ul>
      {gap && <p className="gap">還差一點：{gap}</p>}
    </div>
  )
}
