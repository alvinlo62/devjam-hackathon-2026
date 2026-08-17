import { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import TraceList from '../components/TraceList.jsx'
import { donutSlices, summarizeCategories } from '../lib/categorize.js'

const ELIGIBILITY_TAG = {
  needs_review: { label: '待班長判定', className: 'tag tag--warning' },
}

// 路線示意：純粹依 stop.seq 排序畫出的示意圖，座標用簡單波形排列產生，
// 不是真實地理路徑（手上只有近似座標，見 backend/data/rules.py 的 DEPOTS 註解）——
// 跟組員參考設計標示的「靜態示意」用途相同。
function RouteMap({ stops }) {
  const n = stops.length
  if (n === 0) return <p className="route-map-empty">目前沒有站點</p>
  const w = 1000
  const h = 260
  const points = stops.map((stop, i) => {
    const x = n === 1 ? w / 2 : 70 + i * ((w - 140) / (n - 1))
    const y = h / 2 + Math.sin(i * 1.3) * (h / 2 - 46)
    return { x, y, stop }
  })
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')

  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`收運路線示意圖，共 ${n} 站`}>
      <defs>
        <pattern id="street-grid" width="60" height="60" patternUnits="userSpaceOnUse">
          <rect width="60" height="60" fill="#eef1ee" />
          <path d="M0 30h60M30 0v60" stroke="#ffffff" strokeWidth="7" />
        </pattern>
      </defs>
      <rect width={w} height={h} fill="url(#street-grid)" />
      <path d={path} fill="none" stroke="#ffffff" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
      <path d={path} fill="none" stroke="var(--brand)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
      {points.map((p) => {
        const warn = p.stop.case.eligibility?.status === 'needs_review'
        return (
          <g key={p.stop.case.id} className="route-pin" transform={`translate(${p.x} ${p.y})`}>
            <circle r="15" fill="#ffffff" />
            <circle r="12" fill={warn ? 'var(--orange)' : 'var(--brand)'} />
            <text y="4" textAnchor="middle">
              {p.stop.seq}
            </text>
            <title>{`第 ${p.stop.seq} 站　${p.stop.case.items?.[0]?.name ?? ''}　${p.stop.case.location?.address ?? ''}`}</title>
          </g>
        )
      })}
    </svg>
  )
}

function CategoryDonut({ items }) {
  const breakdown = summarizeCategories(items)
  const total = items.reduce((sum, i) => sum + (i.quantity ?? 1), 0)
  if (breakdown.length === 0) return <p className="donut-empty">目前沒有品項資料</p>
  const slices = donutSlices(breakdown, 54)

  return (
    <div className="donut-block">
      <div className="donut-figure">
        <svg viewBox="0 0 140 140" role="img" aria-label={`物品處理類別組成環圈圖，共 ${total} 件`}>
          <circle cx="70" cy="70" r="54" fill="none" stroke="#eef1ef" strokeWidth="26" />
          {slices.map((s) => (
            <circle
              key={s.key}
              cx="70"
              cy="70"
              r="54"
              fill="none"
              stroke={s.color}
              strokeWidth="26"
              strokeDasharray={s.dasharray}
              strokeDashoffset={s.dashoffset}
              transform="rotate(-90 70 70)"
            >
              <title>{`${s.label}：${s.count} 件（${Math.round(s.pct)}%）`}</title>
            </circle>
          ))}
        </svg>
        <div className="donut-center">
          <strong>{total}</strong>
          <small>件・目前班次</small>
        </div>
      </div>
      <table className="donut-legend">
        <thead>
          <tr>
            <th scope="col">處理類別</th>
            <th scope="col">件數</th>
            <th scope="col">占比</th>
          </tr>
        </thead>
        <tbody>
          {slices.map((s) => (
            <tr key={s.key}>
              <th scope="row">
                <i aria-hidden="true" style={{ background: s.color }} />
                {s.label}
              </th>
              <td>{s.count}</td>
              <td>{Math.round(s.pct)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="donut-note">依收運品項自動歸類；統計範圍為目前選取的行政區班次。</p>
    </div>
  )
}

// 建議橫幅：自動試算最佳插入班次（優先今日，超載則退而求其次找下一個可行班次），
// 一鍵接受——跟參考設計「單顆按鈕接受建議」的體驗一致；
// 差別是我們背後真的呼叫 propose/accept 兩支 API，不是預先寫死的文字。
function RecommendationBanner({ case_, shifts, onAccepted }) {
  const [plan, setPlan] = useState(null)
  const [shiftId, setShiftId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setPlan(null)
    setShiftId(null)
    const candidates = shifts
      .filter((s) => s.district === case_.location?.district)
      .sort((a, b) => a.date.localeCompare(b.date))

    async function findPlan() {
      for (const s of candidates) {
        try {
          const data = await api.proposeInsertion({ case_id: case_.id, shift_id: s.id })
          if (cancelled) return
          if (data.plan.feasible) {
            setShiftId(s.id)
            setPlan(data.plan)
            return
          }
        } catch {
          // 這個班次試算失敗，換下一個候選班次
        }
      }
    }
    if (candidates.length > 0) findPlan()
    return () => {
      cancelled = true
    }
  }, [case_.id, case_.location?.district, shifts])

  async function handleAccept() {
    if (!plan || !shiftId) return
    setBusy(true)
    setError(null)
    try {
      await api.acceptInsertion({ case_id: case_.id, shift_id: shiftId, position: plan.position })
      onAccepted()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const shift = shifts.find((s) => s.id === shiftId)

  return (
    <section className="recommendation-banner">
      <div className="recommendation-alert">!</div>
      <div>
        <span className="doc-label">新案件待確認</span>
        <h2>
          {case_.id}　{case_.location?.district}
        </h2>
        {plan && shift ? (
          <p>
            建議排入 {shift.date} 第 {plan.position} 站後，插入後載重 {Math.round(plan.resulting_load_ratio * 100)}%
          </p>
        ) : (
          <p>試算插入位置中…</p>
        )}
        {error && <p style={{ color: 'var(--red)', marginTop: 4 }}>{error}</p>}
      </div>
      <button type="button" onClick={handleAccept} disabled={!plan || busy}>
        {busy ? '處理中…' : '接受建議'}
      </button>
    </section>
  )
}

export default function DashboardPage() {
  const [shifts, setShifts] = useState([])
  const [pendingReview, setPendingReview] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedDistrict, setSelectedDistrict] = useState(null)
  const [selectedDateIdx, setSelectedDateIdx] = useState(0)

  function load() {
    setLoading(true)
    setError(null)
    api
      .schedule()
      .then((data) => {
        setShifts(data.shifts)
        setPendingReview(data.pending_review)
        setSelectedDistrict((prev) => prev ?? data.shifts[0]?.district ?? null)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  async function handleReset() {
    if (!confirm('重置回劇本初始狀態？現場追加的案件會消失。')) return
    await api.reset()
    load()
  }

  if (loading || error) {
    return (
      <div className="dashboard-root">
        <main className="dashboard-shell">
          {loading && <p className="text-block">載入中…</p>}
          {error && <p className="error-banner">{error}</p>}
        </main>
      </div>
    )
  }

  const districts = [...new Set(shifts.map((s) => s.district))]
  const districtShifts = shifts.filter((s) => s.district === selectedDistrict).sort((a, b) => a.date.localeCompare(b.date))
  const selectedShift = districtShifts[selectedDateIdx] ?? districtShifts[0] ?? null

  const totalPool = shifts.reduce((sum, s) => sum + s.stops.length, 0) + pendingReview.length
  const earliestDate = shifts.reduce((min, s) => (min && min < s.date ? min : s.date), null)
  const scheduledToday = shifts.filter((s) => s.date === earliestDate).reduce((sum, s) => sum + s.stops.length, 0)
  const needsReviewCount = pendingReview.filter((c) => c.eligibility?.status === 'needs_review').length
  const eligiblePending = pendingReview.filter((c) => c.eligibility?.status === 'eligible')
  const needsReviewCases = pendingReview.filter((c) => c.eligibility?.status === 'needs_review')

  const traceCase = eligiblePending[0] ?? selectedShift?.stops?.[0]?.case ?? null

  return (
    <div className="dashboard-root">
      <div className="gov-banner">
        <div className="gov-banner-inner">
          <span className="gov-banner-agency">臺北市政府環境保護局</span>
          <span className="gov-banner-divider" aria-hidden="true" />
          <span className="gov-banner-system">大型廢棄物收運調度系統</span>
          <span className="gov-banner-flag">原型展示</span>
        </div>
      </div>

      <header className="dashboard-header">
        <div className="dashboard-header-inner">
          <a href="/dashboard" className="dispatch-brand">
            <span>🚛</span>
            <div>
              <strong>CityTask 調度台</strong>
              <small>清潔隊班長作業系統</small>
            </div>
          </a>
          <nav>
            <a href="/">民眾送件</a>
            <button type="button" onClick={handleReset}>
              重置示範資料
            </button>
          </nav>
        </div>
      </header>

      <main className="dashboard-shell">
        <section className="dashboard-title-row">
          <div>
            <h1>今日清運作業</h1>
            <p className="doc-meta">
              <span>行政區班次 {districts.length}</span>
              <span>資料來源 排程服務</span>
            </p>
          </div>
          <span className="api-status">
            <i />
            即時資料
          </span>
        </section>

        <section className="metric-grid" aria-label="今日案件摘要">
          <article>
            <small>案件池</small>
            <strong>
              {totalPool} <em>件</em>
            </strong>
            <p>含現場新增案件</p>
          </article>
          <article>
            <small>今日已排</small>
            <strong>
              {scheduledToday} <em>件</em>
            </strong>
            <p>{districts.length} 個行政區班次</p>
          </article>
          <article>
            <small>待人工判定</small>
            <strong>
              {needsReviewCount} <em>件</em>
            </strong>
            <p>保留班長裁量</p>
          </article>
          <article>
            <small>{selectedDistrict ?? '—'}載重</small>
            <strong>{selectedShift ? Math.round(selectedShift.load_ratio * 100) : '—'}%</strong>
            <p>{selectedShift?.overloaded ? '已超過容量上限' : '容量正常'}</p>
          </article>
        </section>

        {eligiblePending.length === 0 && (
          <div className="recommendation-empty">目前沒有待確認的新案件建議。</div>
        )}
        {eligiblePending.map((c) => (
          <RecommendationBanner key={c.id} case_={c} shifts={shifts} onAccepted={load} />
        ))}
        {needsReviewCases.length > 0 && (
          <div className="review-note">
            <strong>需清潔隊現場複核（{needsReviewCases.length}）：</strong>{' '}
            {needsReviewCases.map((c) => `${c.id}（${c.items?.[0]?.name ?? ''}）`).join('、')}
          </div>
        )}

        {selectedShift && (
          <section className="route-map-panel">
            <div className="panel-header--compact">
              <h2>
                {selectedShift.district}
                {selectedShift.date} 路線
              </h2>
              <div className="route-map-meta">
                <span className="map-badge">靜態示意</span>
                <span>{selectedShift.stops.length} 站</span>
              </div>
            </div>
            <div className="route-map-canvas">
              <RouteMap stops={selectedShift.stops} />
            </div>
            <p className="route-map-legend">
              <span className="dot dot--route" />
              目前路線
              <span className="dot dot--warn" />
              待班長判定
              <em>站點位置依收運順序示意繪製，非實際地理路徑。</em>
            </p>
          </section>
        )}

        <div className="dashboard-grid">
          <section className="route-panel">
            <div className="panel-header">
              <h2>今日任務清單</h2>
              <span>{selectedShift?.stops.length ?? 0} 站</span>
            </div>

            <div className="district-tabs" role="tablist" aria-label="行政區">
              {districts.map((d) => {
                const shift = shifts.find((s) => s.district === d && s.date === earliestDate) ?? shifts.find((s) => s.district === d)
                return (
                  <button
                    key={d}
                    type="button"
                    role="tab"
                    aria-selected={d === selectedDistrict}
                    onClick={() => {
                      setSelectedDistrict(d)
                      setSelectedDateIdx(0)
                    }}
                  >
                    <strong>{d}</strong>
                    <small>
                      {shift?.stops.length ?? 0} 件・載重 {shift ? Math.round(shift.load_ratio * 100) : 0}%
                    </small>
                  </button>
                )
              })}
            </div>

            {districtShifts.length > 1 && (
              <div style={{ padding: '10px 16px 0' }} className="scope-switch" role="group" aria-label="班次日期">
                {districtShifts.map((s, i) => (
                  <button key={s.id} type="button" aria-pressed={i === selectedDateIdx} onClick={() => setSelectedDateIdx(i)}>
                    {s.date}（{Math.round(s.load_ratio * 100)}%）
                  </button>
                ))}
              </div>
            )}

            <div className="route-table-body">
              <table className="route-table">
                <thead>
                  <tr>
                    <th scope="col">順序</th>
                    <th scope="col">物品</th>
                    <th scope="col">收運地址</th>
                    <th scope="col">註記</th>
                    <th scope="col">案件編號</th>
                  </tr>
                </thead>
                <tbody>
                  {(selectedShift?.stops ?? []).map((stop) => {
                    const specialHandling = stop.case.items?.some((i) => i.attributes?.special_handling)
                    const reviewTag = ELIGIBILITY_TAG[stop.case.eligibility?.status]
                    return (
                      <tr key={stop.case.id}>
                        <td>
                          <span className="stop-number">{stop.seq}</span>
                        </td>
                        <td className="route-item">
                          {stop.case.items?.map((i) => `${i.name} × ${i.quantity}`).join('、')}
                        </td>
                        <td className="route-addr">{stop.case.location?.address}</td>
                        <td className="route-tags">
                          {specialHandling && <span className="tag tag--special">含冷媒設備，需特殊處理</span>}
                          {reviewTag && <span className={reviewTag.className}>{reviewTag.label}</span>}
                        </td>
                        <td className="route-id">{stop.case.id}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <div className="route-pagination">
              <p>顯示第 1–{selectedShift?.stops.length ?? 0} 站，共 {selectedShift?.stops.length ?? 0} 站</p>
            </div>
          </section>

          <aside className="dashboard-aside">
            <section className="chart-panel">
              <div className="panel-header--compact">
                <h2>物品類別組成</h2>
              </div>
              <CategoryDonut items={selectedShift?.stops.flatMap((s) => s.case.items ?? []) ?? []} />
            </section>

            <section className="trace-panel">
              <div className="panel-header--compact">
                <h2>調度決策紀錄</h2>
              </div>
              <div className="trace-list">
                <TraceList steps={traceCase?.trace} variant="dashboard" />
              </div>
            </section>
          </aside>
        </div>
      </main>

      <footer className="gov-footer">
        <div className="gov-footer-inner">
          <div className="gov-footer-org">
            <strong>臺北市政府環境保護局</strong>
            <dl>
              <div>
                <dt>地址</dt>
                <dd>臺北市信義區市府路 1 號</dd>
              </div>
              <div>
                <dt>服務專線</dt>
                <dd>1999（外縣市請撥 02-2720-8889）</dd>
              </div>
              <div>
                <dt>服務時間</dt>
                <dd>週一至週五 08:30–17:30</dd>
              </div>
            </dl>
          </div>
          <nav className="gov-footer-links" aria-label="網站政策">
            <ul>
              <li>
                <a href="#policy">隱私權政策</a>
              </li>
              <li>
                <a href="#policy">資訊安全政策</a>
              </li>
              <li>
                <a href="#policy">政府網站資料開放宣告</a>
              </li>
              <li>
                <a href="#policy">無障礙說明</a>
              </li>
            </ul>
          </nav>
        </div>
        <div className="gov-footer-meta">
          <p>本系統為大型廢棄物調度助手原型展示，判定結果僅供參考，非臺北市政府正式收運預約管道。</p>
        </div>
      </footer>
    </div>
  )
}
