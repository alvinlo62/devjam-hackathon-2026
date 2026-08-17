import { useEffect, useRef, useState } from 'react'
import { api, fileToBase64 } from '../api/client.js'
import MessageBlock from '../components/MessageBlock.jsx'
import { DEMO_CASES } from '../lib/demoCases.js'
import { extractDistrict, loadGooglePlaces } from '../lib/googleMaps.js'
import { normalizeToJpeg } from '../lib/imageNormalize.js'
import logo from '../assets/logo.jpg'

// 目前只有這三個行政區有真的班次資料（fixtures/demo_cases.json）。
const DISTRICTS = ['信義區', '大安區', '松山區']

// pickup 輪詢間隔。案件進入終態（completed/rejected）就停止輪詢。
const POLL_INTERVAL_MS = 5000
const TERMINAL_STATUSES = new Set(['completed', 'rejected'])

// 案件資料本身在後端 data/store.py 就有（記憶體 store，伺服器活著就在），
// 真正會不見的是前端「記得剛剛在追蹤哪個案件」這件事——切到 /dashboard
// 讓 CitizenPage 卸載，caseId 這些 React state 就沒了。存最近一次送出
// 的 case id，回到這頁時用既有的 GET /api/cases/{id} 撈回狀態，
// 不需要新的後端端點或資料庫。
const STORAGE_KEY = 'citytask_case_id'

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

// 上傳照片之後、正式送出之前，逐題問清楚身份/行政區/地址/清運日期，
// 對應後端 SubmitCaseRequest 的 applicant_type / location / preferred_day
// ——問完最後一題才真的呼叫一次 /api/cases，中間都是前端自己的狀態。
const WIZARD_QUESTIONS = ['applicant', 'district', 'address', 'date']

// weight_band 只是 light/medium/heavy 三級距，不是精確公斤數；這個對應
// 表是前端自己給的參考區間，跟 backend/data/rules.py 的常識推估屬於
// 同一等級的「系統參考值」，不是官方秤重數據。
const WEIGHT_BAND_LABEL = { light: '10–30 kg', medium: '30–60 kg', heavy: '60–100 kg' }

// 地址步驟用真的 Google Places Autocomplete，不是純視覺樣式——選定地點後
// 直接帶出 formatted_address + 真實經緯度，取代原本用文字關鍵字猜行政區
// 的暫時做法。
function AddressStep({ district, onConfirm }) {
  const inputRef = useRef(null)
  const [status, setStatus] = useState('loading') // loading | ready | error
  const [errorMsg, setErrorMsg] = useState(null)

  useEffect(() => {
    let cancelled = false
    let autocomplete

    loadGooglePlaces()
      .then((places) => {
        if (cancelled || !inputRef.current) return
        autocomplete = new places.Autocomplete(inputRef.current, {
          fields: ['formatted_address', 'geometry', 'address_components'],
          componentRestrictions: { country: 'tw' },
        })
        autocomplete.addListener('place_changed', () => {
          const place = autocomplete.getPlace()
          if (!place.geometry) return
          onConfirm({
            address: place.formatted_address,
            district: extractDistrict(place) ?? district,
            lat: place.geometry.location.lat(),
            lng: place.geometry.location.lng(),
          })
        })
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
  }, [district])

  return (
    <div className="choices-block">
      <h2>請輸入清運地址（{district}）</h2>
      <input
        ref={inputRef}
        type="text"
        className="address-input"
        placeholder={status === 'ready' ? '輸入地址，從建議清單中選取' : '地圖載入中…'}
        disabled={status !== 'ready'}
      />
      {status === 'error' && <p className="error-banner">{errorMsg}</p>}
      <p className="field__hint">從下拉建議清單選取地址後會自動進入下一步</p>
    </div>
  )
}

export default function CitizenPage() {
  const fileInputRef = useRef(null)
  const [applicantOptions, setApplicantOptions] = useState([])
  const [shifts, setShifts] = useState([])
  const [photoFile, setPhotoFile] = useState(null)
  const [photoPreview, setPhotoPreview] = useState(null)
  const [analyzedItems, setAnalyzedItems] = useState(null) // POST /api/photo/classify 的結果
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState(null)

  // wizardStep：null＝不在問答流程；0~3＝目前問到第幾題（WIZARD_QUESTIONS
  // 索引）；'confirm'＝四題答完了，等民眾看過摘要再按「建立清運案件」，
  // 不是答完最後一題就直接送出。
  const [wizardStep, setWizardStep] = useState(null)
  const [wizardAnswers, setWizardAnswers] = useState({
    applicant_type: 'household',
    district: null,
    location: null,
    preferred_day: null,
    preferred_date_label: null, // 給確認畫面顯示的真實日期文字，例如 "2026-08-19"
  })

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
    // 清運日期那一題要秀真的日期跟真的載重%，不是編出來的日曆。
    api
      .schedule()
      .then((data) => setShifts(data.shifts ?? []))
      .catch(() => {})
  }, [])

  // 回到這頁時，如果先前有送出過案件，把畫面恢復成查看結果的狀態
  // （跳過表單/問答），而不是每次都從頭開始。查不到（例如伺服器重
  // 開過，記憶體 store 清空了）就當作沒這回事，留在正常的送件表單。
  useEffect(() => {
    const savedId = localStorage.getItem(STORAGE_KEY)
    if (!savedId) return
    api
      .getCase(savedId)
      .then((data) => {
        setCaseId(data.case.id)
        setCaseStatus(data.case.status)
        setPickup(data.pickup)
        setStarted(true)
        setWizardStep(null)
        setMessages([{ role: 'agent', blocks: [{ type: 'result', case: data.case }] }])
      })
      .catch(() => localStorage.removeItem(STORAGE_KEY))
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

  // 選完照片就先辨識（不是等民眾答完四題才辨識），這樣「確認資料」
  // 最後的摘要頁才有真的物品資訊可以顯示；辨識結果直接帶進最終送出的
  // /api/cases 呼叫（見 submitFinal），同一張照片不會被辨識兩次。
  async function handlePhotoChange(e) {
    let file = e.target.files?.[0]
    if (!file) return
    // 選完照片的第一時間就統一轉成 JPEG（見 lib/imageNormalize.js），
    // 讓預覽、辨識、送出用的都是同一份格式一致的檔案。
    try {
      file = await normalizeToJpeg(file)
    } catch (err) {
      setErrorMsg(err.message)
      return
    }
    setPhotoFile(file)
    setPhotoPreview(URL.createObjectURL(file))
    setStarted(true)
    setWizardStep(0)
    setErrorMsg(null)
    setAnalyzedItems(null)
    setAnalyzeError(null)
    setAnalyzing(true)
    try {
      const image_base64 = await fileToBase64(file)
      const data = await api.classifyPhoto({ image_base64 })
      setAnalyzedItems(data.items)
    } catch (err) {
      setAnalyzeError(err.message)
    } finally {
      setAnalyzing(false)
    }
  }

  // 重新選照片：回到上傳畫面，讓民眾可以換一張重來，不用重新整理頁面。
  // 只在案件還沒真的送出前（inWizard）才會顯示這顆按鈕，見 JSX 端。
  function resetPhoto() {
    setPhotoFile(null)
    setPhotoPreview(null)
    setAnalyzedItems(null)
    setAnalyzeError(null)
    setAnalyzing(false)
    setWizardStep(null)
    setStarted(false)
    setErrorMsg(null)
    // 清空 input 的值，不然選同一個檔案時瀏覽器不會觸發 onChange。
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function appendAgentMessage(message, resultCase, persist = true) {
    setMessages((prev) => [...prev, message])
    if (resultCase) {
      setCaseId(resultCase.id)
      setCaseStatus(resultCase.status)
      // 示範案例（persist=false）是純前端假資料，這個 id 在後端查不到，
      // 存了只會在下次載入時被 404 清掉，乾脆不存。
      if (persist) localStorage.setItem(STORAGE_KEY, resultCase.id)
    }
  }

  async function submitFinal(file, answers) {
    setSubmitting(true)
    setErrorMsg(null)
    try {
      // 已經有 handlePhotoChange 辨識好的結果就直接帶過去，不用再送一次
      // 照片、再辨識一次；辨識失敗或還沒辨識完（極端情況）才退回原本
      // 「帶照片給後端自己辨識」的路徑。
      const payload = {
        applicant_type: answers.applicant_type,
        location: answers.location,
        preferred_day: answers.preferred_day,
      }
      if (analyzedItems) {
        payload.items = analyzedItems
      } else {
        payload.image_base64 = await fileToBase64(file)
      }
      const data = await api.submitCase(payload)
      setWizardStep(null)
      appendAgentMessage(data.message, data.case)
    } catch (err) {
      setErrorMsg(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  // 逐題作答：填完最後一題（清運日期）先進確認摘要畫面，不會直接送出，
  // 讓民眾看過所有資訊、按下「建立清運案件」才真的打後端。
  function answerWizard(key, value, extra = {}) {
    const next = { ...wizardAnswers, [key]: value, ...extra }
    setWizardAnswers(next)
    const nextStep = wizardStep + 1
    if (nextStep >= WIZARD_QUESTIONS.length) {
      setWizardStep('confirm')
    } else {
      setWizardStep(nextStep)
    }
  }

  // 回上一題改答案；不清掉 wizardAnswers，回去看到的還是原本選的值，
  // 重新選才會覆蓋。第 0 題（申請人身份）沒有上一步——再上去是照片
  // 上傳，那是另一個獨立動作，不是這個問答流程的一部分。
  function goBackWizard() {
    if (wizardStep === 'confirm') {
      setWizardStep(WIZARD_QUESTIONS.length - 1)
    } else if (typeof wizardStep === 'number' && wizardStep > 0) {
      setWizardStep(wizardStep - 1)
    }
  }

  // 續答「裝潢廢料來源」這類送出後才觸發的追問，跟上面的 wizard 是不同機制
  // ——這是後端資格判定當下決定要問的，不是送件前的固定題目。
  async function handleChoice(value) {
    if (!caseId) return
    setSubmitting(true)
    setErrorMsg(null)
    try {
      const data = await api.submitCase({
        case_id: caseId,
        applicant_type: wizardAnswers.applicant_type,
        answers: { decoration_source: value },
      })
      appendAgentMessage(data.message, data.case)
    } catch (err) {
      setErrorMsg(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  function handleDemoCase(demo) {
    setErrorMsg(null)
    setPhotoPreview(demo.src)
    setStarted(true)
    setWizardStep(null) // 示範案例純前端假資料，跳過整個問答流程
    const reasons = demo.case.eligibility?.reasons ?? []
    appendAgentMessage(
      {
        role: 'agent',
        blocks: [
          { type: 'text', content: reasons.join('\n') },
          { type: 'result', case: demo.case },
        ],
      },
      demo.case,
      false,
    )
  }

  const lastMessage = messages[messages.length - 1]
  const awaitingChoice = lastMessage?.blocks?.some((b) => b.type === 'choices')
  const inWizard = wizardStep !== null

  // 步驟指示器：1 上傳照片＝還沒選照片，2 確認資料＝問答中或還在等 agent
  // 追問，3 查看結果＝已經有最終結果可看。
  const step = !started ? 1 : inWizard || awaitingChoice ? 2 : 3

  const lastResultCase = [...messages]
    .reverse()
    .flatMap((m) => m.blocks)
    .find((b) => b.type === 'result')?.case

  const progressIdx = caseStatus ? progressIndex(caseStatus) : -1

  const districtShifts = shifts
    .filter((s) => s.district === wizardAnswers.district)
    .sort((a, b) => a.date.localeCompare(b.date))

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
            <img className="brand-mark" src={logo} alt="CityTask" />
            <span>
              <strong>CityTask</strong>
              <small>大型廢棄物清運服務</small>
            </span>
          </a>
          <div className="header-actions">
            <span className="header-trust">
              市民服務<span className="demo-pill">DEMO</span>
            </span>
            <a href="/dashboard">清潔隊工作台 →</a>
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
                      請上傳一張包含完整物品的照片。系統會辨識物品內容，接著逐項確認身份、地址與清運日期。
                    </div>

                    <label className="upload-target" htmlFor="photo-input">
                      <span className="upload-icon">📷</span>
                      <span className="upload-copy">
                        <strong>拍照／上傳物品照片</strong>
                        <small>支援手機相機或相簿照片</small>
                      </span>
                      <span className="upload-arrow">→</span>
                    </label>
                    <input
                      id="photo-input"
                      ref={fileInputRef}
                      className="upload-target__input"
                      type="file"
                      accept="image/*"
                      onChange={handlePhotoChange}
                    />
                  </div>
                </div>
              </section>

              <section className="demo-cases" aria-labelledby="demo-cases-title">
                <div className="section-heading">
                  <h2 id="demo-cases-title">示範案例</h2>
                  <span className="fixture-note">展示模式</span>
                </div>
                <p className="section-note">可直接選取以檢視完整判定流程，不用自己找照片。</p>
                <div className="demo-grid">
                  {DEMO_CASES.map((demo) => (
                    <button
                      key={demo.name}
                      type="button"
                      className="demo-card"
                      onClick={() => handleDemoCase(demo)}
                      disabled={submitting}
                    >
                      <img alt="" src={demo.src} />
                      <span>
                        <strong>{demo.name}</strong>
                        <small>{demo.sub}</small>
                      </span>
                      <span className="demo-card__arrow">→</span>
                    </button>
                  ))}
                </div>
              </section>
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
                  {inWizard && wizardStep !== 0 && (
                    <button type="button" className="wizard-back" onClick={goBackWizard}>
                      ← 上一步
                    </button>
                  )}
                  {wizardStep === 0 && (
                    <div className="choices-block">
                      <h2>這批物品是由哪一類申請者處理？</h2>
                      <div className="choice-list">
                        {applicantOptions.map((opt) => (
                          <button
                            key={opt.value}
                            className="choice-button"
                            onClick={() => answerWizard('applicant_type', opt.value)}
                          >
                            <span className="choice-button__body">
                              <strong>{opt.label}</strong>
                            </span>
                            <span className="choice-button__arrow">→</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {wizardStep === 1 && (
                    <div className="choices-block">
                      <h2>請選擇物品所在行政區</h2>
                      <div className="choice-list">
                        {DISTRICTS.map((d) => (
                          <button key={d} className="choice-button" onClick={() => answerWizard('district', d)}>
                            <span className="choice-button__body">
                              <strong>{d}</strong>
                            </span>
                            <span className="choice-button__arrow">→</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {wizardStep === 2 && (
                    <AddressStep
                      district={wizardAnswers.district}
                      onConfirm={(location) => answerWizard('location', location)}
                    />
                  )}

                  {wizardStep === 3 && (
                    <div className="choices-block">
                      <h2>請選擇預計清運日期（週日不收運）</h2>
                      <div className="choice-list">
                        {districtShifts.map((s, i) => (
                          <button
                            key={s.id}
                            className="choice-button"
                            onClick={() =>
                              answerWizard('preferred_day', i === 0 ? 'today' : 'tomorrow', {
                                preferred_date_label: s.date,
                              })
                            }
                          >
                            <span className="choice-button__body">
                              <strong>{s.date}</strong>
                              <small>目前載重 {Math.round(s.load_ratio * 100)}%</small>
                            </span>
                            <span className="choice-button__arrow">→</span>
                          </button>
                        ))}
                      </div>
                      {districtShifts.length === 0 && (
                        <p className="block-text block-text--muted">查無班次資料，將由清潔隊另行安排。</p>
                      )}
                    </div>
                  )}

                  {wizardStep === 'confirm' && (
                    <div className="choices-block">
                      <h2>請確認以下資訊</h2>

                      <h3 className="confirm-summary__label">照片觀察</h3>
                      {analyzing && <p className="block-text block-text--muted">辨識中…</p>}
                      {analyzeError && <p className="error-banner">{analyzeError}（送出時將重新嘗試辨識）</p>}
                      {analyzedItems && analyzedItems.length > 0 && (
                        <>
                          <div className="observation-grid">
                            {analyzedItems
                              .flatMap((item, i) => [
                                <span key={`${i}-name`}>
                                  {item.name} × {item.quantity}
                                </span>,
                                item.attributes?.max_dimension_cm && (
                                  <span key={`${i}-dim`}>長度約 {item.attributes.max_dimension_cm} cm</span>
                                ),
                                item.attributes?.material && <span key={`${i}-mat`}>材質：{item.attributes.material}</span>,
                                item.attributes?.weight_band && (
                                  <span key={`${i}-wb`}>重量級距：{WEIGHT_BAND_LABEL[item.attributes.weight_band]}</span>
                                ),
                                item.attributes && (
                                  <span key={`${i}-dis`}>{item.attributes.dismantlable ? '可拆解' : '不可拆解'}</span>
                                ),
                              ])
                              .filter(Boolean)}
                          </div>
                          <p className="confidence">
                            影像辨識信心度{' '}
                            {Math.round(
                              (analyzedItems.reduce((sum, i) => sum + (i.confidence ?? 1), 0) / analyzedItems.length) *
                                100,
                            )}
                            %
                          </p>
                        </>
                      )}

                      <h3 className="confirm-summary__label">送件資訊</h3>
                      <dl className="confirm-summary">
                        <div>
                          <dt>申請人身份</dt>
                          <dd>
                            {applicantOptions.find((o) => o.value === wizardAnswers.applicant_type)?.label ??
                              wizardAnswers.applicant_type}
                          </dd>
                        </div>
                        <div>
                          <dt>行政區</dt>
                          <dd>{wizardAnswers.district}</dd>
                        </div>
                        <div>
                          <dt>地址</dt>
                          <dd>{wizardAnswers.location?.address}</dd>
                        </div>
                        <div>
                          <dt>清運日期</dt>
                          <dd>{wizardAnswers.preferred_date_label}</dd>
                        </div>
                      </dl>
                      <p className="field__hint">確認無誤後按下方按鈕建立案件，系統會立即進行資格判定。</p>
                      {errorMsg && <p className="error-banner">{errorMsg}</p>}
                      <div style={{ marginTop: 14 }}>
                        <button
                          className="primary-button"
                          onClick={() => submitFinal(photoFile, wizardAnswers)}
                          disabled={submitting}
                        >
                          {submitting ? '送出中…' : '建立清運案件'}
                        </button>
                      </div>
                    </div>
                  )}

                  {!inWizard &&
                    messages.flatMap((msg, i) =>
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

          {started && !inWizard && progressIdx >= 0 && (
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
          {started && !inWizard && caseStatus === 'rejected' && (
            <p className="error-banner">本案件不符合收運資格。</p>
          )}

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
              {photoPreview && inWizard && (
                <button type="button" className="photo-reset" onClick={resetPhoto}>
                  重新選擇照片
                </button>
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
