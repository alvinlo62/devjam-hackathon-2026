import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import TraceList from '../components/TraceList.jsx'
import { donutSlices, summarizeCategories } from '../lib/categorize.js'
import { loadGoogleMaps } from '../lib/googleMaps.js'

const ELIGIBILITY_TAG = {
  needs_review: { label: '待班長判定', className: 'tag tag--warning' },
}

// 真的 Google Map，標記位置用 Case.location 的真實經緯度（民眾端地址
// 選點來自 Google Places、fixture 案件是查證過的真實台北市座標，見
// fixtures/demo_cases.json）。站與站之間走 Directions API 算出來的
// 真實道路路徑，不是直線——但保留我們自己排定的收運順序
// （optimizeWaypoints: false），不讓 Google 自己重新排點，因為順序是
// compute_insertion 算出來的，不是這裡的責任。少數情況（超過 25 站、
// 路網真的算不出來）才會退回直線示意，並且用虛線＋較淡的顏色跟真實
// 路徑做視覺區分，不會讓人誤以為那也是道路路徑。
function GoogleRouteMap({ stops }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const overlaysRef = useRef([])
  const directionsRendererRef = useRef(null)
  const [status, setStatus] = useState('loading') // loading | ready | error
  const [errorMsg, setErrorMsg] = useState(null)
  const [routeFallback, setRouteFallback] = useState(false)
  const [routeSummary, setRouteSummary] = useState(null) // { distanceKm, durationMin }

  useEffect(() => {
    let cancelled = false
    loadGoogleMaps()
      .then((maps) => {
        if (cancelled || !containerRef.current) return
        if (!mapRef.current) {
          mapRef.current = new maps.Map(containerRef.current, {
            zoom: 14,
            center: { lat: 25.033, lng: 121.5654 },
            mapTypeControl: false,
            streetViewControl: false,
            fullscreenControl: false,
          })
          directionsRendererRef.current = new maps.DirectionsRenderer({
            map: mapRef.current,
            suppressMarkers: true, // 用我們自己的編號圓形標記，不要 Google 預設的 A/B 大頭針
            preserveViewport: true, // 視角由我們自己的 fitBounds 控制
            polylineOptions: { strokeColor: '#0b5a4a', strokeOpacity: 0.9, strokeWeight: 4 },
          })
        }
        setStatus('ready')
      })
      .catch((err) => {
        if (!cancelled) {
          setStatus('error')
          setErrorMsg(err.message)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (status !== 'ready' || !mapRef.current || !window.google?.maps) return
    const maps = window.google.maps

    // 切行政區/日期會重新跑這個 effect，先清掉上一輪畫的 marker/路線，
    // 不然舊圖會疊在新圖上面。
    overlaysRef.current.forEach((overlay) => overlay.setMap(null))
    overlaysRef.current = []
    directionsRendererRef.current.setDirections({ routes: [] })
    setRouteFallback(false)
    setRouteSummary(null)
    if (stops.length === 0) return

    const bounds = new maps.LatLngBounds()

    stops.forEach((stop) => {
      const position = { lat: stop.case.location.lat, lng: stop.case.location.lng }
      bounds.extend(position)

      const warn = stop.case.eligibility?.status === 'needs_review'
      const marker = new maps.Marker({
        position,
        map: mapRef.current,
        label: { text: String(stop.seq), color: '#fff', fontSize: '12px', fontWeight: '700' },
        icon: {
          path: maps.SymbolPath.CIRCLE,
          scale: 14,
          fillColor: warn ? '#97601a' : '#0b5a4a',
          fillOpacity: 1,
          strokeColor: '#ffffff',
          strokeWeight: 2,
        },
        title: `第 ${stop.seq} 站　${stop.case.items?.[0]?.name ?? ''}`,
      })
      const info = new maps.InfoWindow({
        content: `<div style="font-size:13px;line-height:1.6"><strong>第 ${stop.seq} 站</strong><br>${
          stop.case.items?.map((i) => `${i.name} × ${i.quantity}`).join('、') ?? ''
        }<br>${stop.case.location?.address ?? ''}</div>`,
      })
      marker.addListener('click', () => info.open({ anchor: marker, map: mapRef.current }))
      overlaysRef.current.push(marker)
    })

    mapRef.current.fitBounds(bounds, 60)

    function drawStraightFallback() {
      const path = stops.map((s) => ({ lat: s.case.location.lat, lng: s.case.location.lng }))
      const fallback = new maps.Polyline({
        path,
        geodesic: true,
        strokeOpacity: 0,
        icons: [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 0.7, scale: 3 }, offset: '0', repeat: '14px' }],
        strokeColor: '#97601a',
        map: mapRef.current,
      })
      overlaysRef.current.push(fallback)
      setRouteFallback(true)
    }

    if (stops.length < 2) return // 只有一站，沒有路線可畫

    if (stops.length > 25) {
      // Directions API 一次最多 origin+destination+23 個 waypoints
      drawStraightFallback()
      return
    }

    const directionsService = new maps.DirectionsService()
    directionsService.route(
      {
        origin: { lat: stops[0].case.location.lat, lng: stops[0].case.location.lng },
        destination: {
          lat: stops[stops.length - 1].case.location.lat,
          lng: stops[stops.length - 1].case.location.lng,
        },
        waypoints: stops.slice(1, -1).map((s) => ({
          location: { lat: s.case.location.lat, lng: s.case.location.lng },
          stopover: true,
        })),
        optimizeWaypoints: false, // 保留 compute_insertion 排定的順序，不給 Google 重排
        travelMode: maps.TravelMode.DRIVING,
      },
      (result, dStatus) => {
        if (dStatus === 'OK') {
          directionsRendererRef.current.setDirections(result)
          const legs = result.routes[0].legs
          const distanceM = legs.reduce((sum, leg) => sum + leg.distance.value, 0)
          const durationS = legs.reduce((sum, leg) => sum + leg.duration.value, 0)
          setRouteSummary({ distanceKm: distanceM / 1000, durationMin: Math.round(durationS / 60) })
        } else {
          drawStraightFallback()
        }
      },
    )
  }, [stops, status])

  return (
    <div className="route-map-canvas">
      <div ref={containerRef} className="google-map" />
      {status === 'loading' && <p className="route-map-empty">地圖載入中…</p>}
      {status === 'error' && <p className="route-map-empty">{errorMsg}</p>}
      {status === 'ready' && stops.length === 0 && <p className="route-map-empty">目前沒有站點</p>}
      {routeFallback && <p className="route-map-fallback-note">⚠ 道路路徑算不出來，以直線示意收運順序</p>}
      {routeSummary && (
        <p className="route-map-summary">
          全程約 {routeSummary.distanceKm.toFixed(1)} 公里・預估 {routeSummary.durationMin} 分鐘
        </p>
      )}
    </div>
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
          <small>件物品</small>
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

    // agent 送件當下已經決定過要插哪一天了（case_.proposed_date，見
    // ai/agent.py _derive_case_updates、調度決策紀錄面板顯示的就是這個
    // 決策過程）。這裡優先照那一天重新試算，不要自己從今天開始重新
    // 一個個班次試——不然萬一送件之後班次狀態有變動（後面又有其他案件
    // 被接受、載重跟著變），這裡跟調度決策紀錄會算出兩個不同答案，
    // 明明是同一筆案件卻對不起來。查不到 proposed_date 時（理論上
    // 不會發生，防呆用）才退回原本「照日期一個個試」的邏輯。
    const preferred = case_.proposed_date
      ? candidates.filter((s) => s.date === case_.proposed_date)
      : []
    const orderedCandidates = preferred.length > 0 ? preferred : candidates

    async function findPlan() {
      for (const s of orderedCandidates) {
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
    if (orderedCandidates.length > 0) findPlan()
    return () => {
      cancelled = true
    }
  }, [case_.id, case_.location?.district, case_.proposed_date, shifts])

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
        <p className="recommendation-items">
          {case_.items?.map((i) => `${i.name} × ${i.quantity}`).join('、')}
        </p>
        {plan && shift ? (
          <p>
            建議排入 {shift.date} 第 {plan.position} 站後，+{Math.round(plan.added_minutes)} 分鐘，插入後載重{' '}
            {Math.round(plan.resulting_load_ratio * 100)}%
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

// needs_review 存在的意義就是「規則判不了，交清潔隊現場裁量」，所以這裡
// 一定要有實際能按的裁決動作，不能只是靜態列出案件——那樣班長看了也
// 不知道下一步該做什麼。
function ReviewRow({ case_, onResolved }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function handleReview(approved) {
    setBusy(true)
    setError(null)
    try {
      await api.reviewCase({ case_id: case_.id, approved })
      onResolved()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="review-row">
      <div className="review-row__main">
        <strong>
          {case_.id}（{case_.items?.map((i) => `${i.name} × ${i.quantity}`).join('、')}）
        </strong>
        {case_.eligibility?.reasons?.[0] && <p>{case_.eligibility.reasons[0]}</p>}
        {error && <p style={{ color: 'var(--red)' }}>{error}</p>}
      </div>
      <div className="review-row__actions">
        <button type="button" className="status-btn" disabled={busy} onClick={() => handleReview(true)}>
          確認可收運
        </button>
        <button
          type="button"
          className="status-btn status-btn--danger"
          disabled={busy}
          onClick={() => handleReview(false)}
        >
          確認不可收運
        </button>
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const [shifts, setShifts] = useState([])
  const [pendingReview, setPendingReview] = useState([])
  const [completedCases, setCompletedCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedDistrict, setSelectedDistrict] = useState(null)
  const [selectedDateIdx, setSelectedDateIdx] = useState(0)
  const [updatingId, setUpdatingId] = useState(null)

  function load() {
    setLoading(true)
    setError(null)
    api
      .schedule()
      .then((data) => {
        setShifts(data.shifts)
        setPendingReview(data.pending_review)
        setCompletedCases(data.completed ?? [])
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

  // 「開始清運」「標記已收運」——每一站各自手動標記，不是依日期/時間
  // 自動推斷（見 backend 的 UpdateCaseStatusRequest 說明），民眾端的
  // 四步驟進度條就是靠這兩個狀態變化來同步。
  async function handleMarkStatus(caseId, status) {
    setUpdatingId(caseId)
    try {
      await api.updateCaseStatus({ case_id: caseId, status })
      load()
    } catch (err) {
      alert(err.message)
    } finally {
      setUpdatingId(null)
    }
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
            <strong>需清潔隊現場複核（{needsReviewCases.length}）</strong>
            {needsReviewCases.map((c) => (
              <ReviewRow key={c.id} case_={c} onResolved={load} />
            ))}
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
                <span className="map-badge">Google Map</span>
                <span>{selectedShift.stops.length} 站</span>
              </div>
            </div>
            <GoogleRouteMap stops={selectedShift.stops} />
            <p className="route-map-legend">
              <span className="dot dot--route" />
              目前路線
              <span className="dot dot--warn" />
              待班長判定
              <em>標記位置為真實座標；路徑為 Google Directions 規劃之道路路線，順序依調度結果排定。</em>
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
                      {shift?.stops.length ?? 0} 站・載重 {shift ? Math.round(shift.load_ratio * 100) : 0}%
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
                    <th scope="col">狀態</th>
                    <th scope="col">案件編號</th>
                  </tr>
                </thead>
                <tbody>
                  {(selectedShift?.stops ?? []).map((stop) => {
                    const specialHandling = stop.case.items?.some((i) => i.attributes?.special_handling)
                    const reviewTag = ELIGIBILITY_TAG[stop.case.eligibility?.status]
                    const isUpdating = updatingId === stop.case.id
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
                        <td className="route-status">
                          {stop.case.status === 'completed' && <span className="status-done">✓ 已完成</span>}
                          {stop.case.status === 'collecting' && (
                            <button
                              type="button"
                              className="status-btn"
                              disabled={isUpdating}
                              onClick={() => handleMarkStatus(stop.case.id, 'completed')}
                            >
                              {isUpdating ? '更新中…' : '標記已收運'}
                            </button>
                          )}
                          {(stop.case.status === 'scheduled' || stop.case.status === 'deferred') && (
                            <button
                              type="button"
                              className="status-btn"
                              disabled={isUpdating}
                              onClick={() => handleMarkStatus(stop.case.id, 'collecting')}
                            >
                              {isUpdating ? '更新中…' : '開始清運'}
                            </button>
                          )}
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

        {completedCases.length > 0 && (
          <details className="completed-panel">
            <summary>今日已完成（{completedCases.length}）</summary>
            <ul className="completed-list">
              {completedCases.map((c) => (
                <li key={c.id}>
                  <span className="completed-list__id">{c.id}</span>
                  <span className="completed-list__items">
                    {c.items?.map((i) => `${i.name} × ${i.quantity}`).join('、')}
                  </span>
                  <span className="completed-list__addr">{c.location?.address}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
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
