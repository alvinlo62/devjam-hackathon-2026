import { useEffect, useRef, useState } from 'react'
import { api, fileToBase64 } from '../api/client.js'
import MessageBlock from '../components/MessageBlock.jsx'

// 目前只有這三個行政區有真的班次資料（fixtures/demo_cases.json）。
const DISTRICTS = ['信義區', '大安區', '松山區']

// pickup 輪詢間隔。案件進入終態（completed/rejected）就停止輪詢。
const POLL_INTERVAL_MS = 5000
const TERMINAL_STATUSES = new Set(['completed', 'rejected'])

// 清運進度四步驟（對應 CaseStatus，deferred 視覺上等同 scheduled 那一格）。
const PROGRESS_STEPS = [
  { key: 'pending', label: '已送出' },
  { key: 'scheduled', label: '已排程' },
  { key: 'collecting', label: '清運中' },
  { key: 'completed', label: '已完成' },
]
function progressIndex(status) {
  if (status === 'deferred') return 1
  const idx = PROGRESS_STEPS.findIndex((s) => s.key === status)
  return idx === -1 ? 0 : idx
}

export default function CitizenPage() {
  const [applicantOptions, setApplicantOptions] = useState([])
  const [applicantType, setApplicantType] = useState('household')
  const [district, setDistrict] = useState(DISTRICTS[0])
  const [address, setAddress] = useState('')
  const [note, setNote] = useState('')
  const [photoFile, setPhotoFile] = useState(null)
  const [photoPreview, setPhotoPreview] = useState(null)

  const [messages, setMessages] = useState([])
  const [caseId, setCaseId] = useState(null)
  const [pickup, setPickup] = useState(null)
  const [caseStatus, setCaseStatus] = useState(null)
  const [started, setStarted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [errorMsg, setErrorMsg] = useState(null)

  useEffect(() => {
    api
      .applicantTypes()
      .then((data) => setApplicantOptions(data.options ?? []))
      .catch(() => setApplicantOptions([{ label: '一般家庭及住戶', value: 'household' }]))
  }, [])

  // 送出後同一頁面輪詢進度（已送出/已排程/清運中/已完成），不用另外開查詢頁。
  const pollRef = useRef(null)
  useEffect(() => {
    if (!caseId || TERMINAL_STATUSES.has(caseStatus)) {
      clearInterval(pollRef.current)
      return
    }
    pollRef.current = setInterval(() => {
      api
        .getCase(caseId)
        .then((data) => {
          setCaseStatus(data.case.status)
          setPickup(data.pickup)
        })
        .catch(() => {})
    }, POLL_INTERVAL_MS)
    return () => clearInterval(pollRef.current)
  }, [caseId, caseStatus])

  function handlePhotoChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setPhotoFile(file)
    setPhotoPreview(URL.createObjectURL(file))
  }

  function appendAgentMessage(message, resultCase) {
    setMessages((prev) => [...prev, message])
    if (resultCase) {
      setCaseId(resultCase.id)
      setCaseStatus(resultCase.status)
    }
  }

  async function handleSubmit() {
    if (!photoFile) {
      setErrorMsg('請先上傳物品照片')
      return
    }
    setSubmitting(true)
    setErrorMsg(null)
    try {
      const image_base64 = await fileToBase64(photoFile)
      // ⚠️ 暫時實作：目前沒有真的 geocoding，把行政區名稱放進 note 開頭，
      // 讓後端的關鍵字比對能找到（見 docs/api.md POST /api/cases 的說明）。
      const composedNote = [district, address, note].filter(Boolean).join('，')
      const data = await api.submitCase({
        image_base64,
        note: composedNote,
        applicant_type: applicantType,
      })
      setStarted(true)
      appendAgentMessage(data.message, data.case)
    } catch (err) {
      setErrorMsg(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleChoice(value) {
    if (!caseId) return
    setSubmitting(true)
    setErrorMsg(null)
    try {
      const data = await api.submitCase({
        case_id: caseId,
        applicant_type: applicantType,
        answers: { decoration_source: value },
      })
      appendAgentMessage(data.message, data.case)
    } catch (err) {
      setErrorMsg(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const lastMessage = messages[messages.length - 1]
  const awaitingChoice = lastMessage?.blocks?.some((b) => b.type === 'choices')

  // 步驟指示器只是把既有狀態換一種呈現方式，不是新的流程狀態機：
  // 1 上傳照片＝還沒送出，2 確認資料＝agent 還在追問，3 查看結果＝已有結果可看。
  const step = !started ? 1 : awaitingChoice ? 2 : 3

  const lastResultCase = [...messages]
    .reverse()
    .flatMap((m) => m.blocks)
    .find((b) => b.type === 'result')?.case

  const progressIdx = caseStatus ? progressIndex(caseStatus) : -1

  return (
    <div className="app-root">
      <div className="gov-banner">
        <div className="gov-banner-inner">
          <span className="gov-banner-agency">臺北市政府環境保護局</span>
          <span className="gov-banner-divider" aria-hidden="true" />
          <span className="gov-banner-system">大型廢棄物收運調度系統</span>
          <span className="gov-banner-flag">原型展示</span>
        </div>
      </div>

      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href="/">
            <span className="brand-mark">🚛</span>
            <span>
              <strong>CityTask</strong>
              <small>大型廢棄物清運服務</small>
            </span>
          </a>
          <div className="header-actions">
            <span className="header-trust">
              市民服務<span className="demo-pill">DEMO</span>
            </span>
            <a href="/dashboard">班長工作台 →</a>
          </div>
        </div>
      </header>

      <main className="citizen-shell">
        <section className="conversation-column">
          <header className="conversation-intro">
            <span className="doc-label">申請作業</span>
            <h1>大型廢棄物線上申請</h1>
            <p>上傳物品照片後，系統會逐項確認資格；判定結果僅供參考。</p>
          </header>

          <ol className="process-steps" aria-label="申請進度">
            <li className={step === 1 ? 'is-current' : 'is-done'}>
              <span>1</span>
              <strong>上傳照片</strong>
            </li>
            <li className={step === 2 ? 'is-current' : step > 2 ? 'is-done' : ''}>
              <span>2</span>
              <strong>確認資料</strong>
            </li>
            <li className={step === 3 ? 'is-current' : ''}>
              <span>3</span>
              <strong>查看結果</strong>
            </li>
          </ol>

          {!started && (
            <>
              <section className="stage">
                <div className="stage-head">
                  <span className="agent-avatar">🧭</span>
                  <div>
                    <strong>收運申請助理</strong>
                    <small>依收運規則逐項確認；資格判定由規則函式產生，非模型自由回答</small>
                  </div>
                </div>
                <div className="stage-body">
                  <div className="block-stack">
                    <div className="text-block text-block--info">
                      請上傳一張包含完整物品的照片。系統會辨識物品內容，並依收運規則逐項確認。
                    </div>

                    <label className="upload-target" htmlFor="photo-input">
                      <span className="upload-icon">📷</span>
                      <span className="upload-copy">
                        <strong>{photoFile ? photoFile.name : '拍照／上傳物品照片'}</strong>
                        <small>支援手機相機或相簿照片</small>
                      </span>
                      <span className="upload-arrow">→</span>
                    </label>
                    <input
                      id="photo-input"
                      className="upload-target__input"
                      type="file"
                      accept="image/*"
                      onChange={handlePhotoChange}
                    />
                  </div>
                </div>
              </section>

              <div className="supplement-panel">
                <div className="field">
                  <label>申請人身份</label>
                  <div className="choice-row">
                    {applicantOptions.map((opt) => (
                      <button
                        key={opt.value}
                        className={`pill-btn${applicantType === opt.value ? ' pill-btn--active' : ''}`}
                        onClick={() => setApplicantType(opt.value)}
                        type="button"
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="field">
                  <label>行政區</label>
                  <div className="choice-row">
                    {DISTRICTS.map((d) => (
                      <button
                        key={d}
                        className={`pill-btn${district === d ? ' pill-btn--active' : ''}`}
                        onClick={() => setDistrict(d)}
                        type="button"
                      >
                        {d}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="field">
                  <label>詳細地址（選填）</label>
                  <input type="text" value={address} onChange={(e) => setAddress(e.target.value)} />
                </div>

                <label htmlFor="note">
                  補充說明 <span>選填</span>
                </label>
                <textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
                <small>不填寫亦可完成送件流程</small>

                {errorMsg && <p className="error-banner">{errorMsg}</p>}

                <div style={{ marginTop: 14 }}>
                  <button className="primary-button" onClick={handleSubmit} disabled={submitting}>
                    {submitting ? '送出中…' : '送出申請'}
                  </button>
                </div>
              </div>
            </>
          )}

          {started && (
            <section className="stage">
              <div className="stage-head">
                <span className="agent-avatar">🧭</span>
                <div>
                  <strong>收運申請助理</strong>
                  <small>依收運規則逐項確認；資格判定由規則函式產生，非模型自由回答</small>
                </div>
              </div>
              <div className="stage-body">
                <div className="block-stack">
                  {messages.flatMap((msg, i) =>
                    msg.blocks.map((block, j) => (
                      <MessageBlock key={`${i}-${j}`} block={block} disabled={submitting} onChoice={handleChoice} />
                    )),
                  )}
                  {errorMsg && <p className="error-banner">{errorMsg}</p>}
                  {submitting && <div className="text-block">處理中…</div>}
                </div>
              </div>
            </section>
          )}

          {started && progressIdx >= 0 && (
            <div className="progress-card">
              <ol className="progress-track">
                {PROGRESS_STEPS.map((s, i) => (
                  <li
                    key={s.key}
                    className={`progress-step${i === progressIdx ? ' is-current' : i < progressIdx ? ' is-done' : ''}`}
                  >
                    {i > 0 && <span className={`progress-line${i <= progressIdx ? ' is-filled' : ''}`} />}
                    <span className="progress-icon">{i < progressIdx ? '✓' : i + 1}</span>
                    <span className="progress-label">{s.label}</span>
                  </li>
                ))}
              </ol>
              {pickup && (
                <p className="progress-pickup">
                  預計 {pickup.date} 於{pickup.district}清運（第 {pickup.seq} 站）
                </p>
              )}
            </div>
          )}
          {started && caseStatus === 'rejected' && <p className="error-banner">本案件不符合收運資格。</p>}

          <p className="citizen-footer">本服務提供大型廢棄物收運初步判定；實際資格與收運安排仍以清潔隊通知為準。</p>
        </section>

        <aside className="case-aside">
          <div className="aside-card preview-card">
            <div className="aside-heading">
              <span>物品照片</span>
              {lastResultCase && (
                <span className="aside-state">
                  <span />
                  已收到
                </span>
              )}
            </div>
            {photoPreview ? (
              <div className="photo-frame">
                <img src={photoPreview} alt="物品預覽" />
              </div>
            ) : (
              <div className="photo-empty">
                <span>🖼️</span>
                <strong>照片會顯示在這裡</strong>
                <p>請拍攝完整物品，並保留周圍空間，幫助判斷尺寸。</p>
              </div>
            )}
            {lastResultCase && (
              <div className="case-meta">
                <div>
                  <small>辨識物品</small>
                  <strong>{lastResultCase.items?.[0]?.name ?? '—'}</strong>
                </div>
                <div>
                  <small>案件編號</small>
                  <strong>{lastResultCase.id}</strong>
                </div>
              </div>
            )}
          </div>

          <div className="aside-card privacy-card">
            <span className="privacy-card__icon">🛡️</span>
            <div>
              <strong>照片使用說明</strong>
              <p>照片僅用於辨識物品與建立本次案件，請避免拍入人臉、門牌或其他個人資料。</p>
            </div>
          </div>
        </aside>
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
