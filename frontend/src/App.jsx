import { useState } from 'react'
import { api, fileToBase64 } from './api/client'
import ResultCard from './components/ResultCard'

export default function App() {
  const [text, setText] = useState('')
  const [image, setImage] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit() {
    setLoading(true)
    setError(null)
    try {
      const payload = { text }
      if (image) payload.image_base64 = await fileToBase64(image)
      setData(await api.analyze(payload))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="container">
      <header>
        <h1>專案名稱</h1>
        <p className="sub">一句話說明這個系統在解決什麼問題</p>
      </header>

      <section className="card">
        <textarea
          rows={4}
          value={text}
          placeholder="輸入描述…"
          onChange={(e) => setText(e.target.value)}
        />
        <input type="file" accept="image/*" onChange={(e) => setImage(e.target.files[0])} />
        <button onClick={handleSubmit} disabled={loading}>
          {loading ? '分析中…' : '開始分析'}
        </button>
      </section>

      {error && <p className="error">發生錯誤：{error}</p>}

      {data && (
        <section>
          <div className="card summary">
            <h2>分析結果</h2>
            <p>{data.summary}</p>
            {data.used_fixture && <span className="badge">示範資料</span>}
          </div>
          {data.results.map((r, i) => (
            <ResultCard key={i} result={r} />
          ))}
        </section>
      )}
    </main>
  )
}
