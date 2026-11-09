import { useState, useEffect } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

interface HealthStatus {
  status: string
  service: string
  database: string
}

function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [ping, setPing] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch(`${API_URL}/health`).then(r => r.json()),
      fetch(`${API_URL}/health/ping`).then(r => r.json()),
    ])
      .then(([h, p]) => {
        setHealth(h as HealthStatus)
        setPing(p.pong)
      })
      .catch(err => {
        console.error('Connection failed:', err)
      })
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="app">
      <header className="header">
        <h1>Zamp Invoice Intelligence</h1>
        <p className="subtitle">AI-powered invoice processing workflow</p>
      </header>

      <main className="main">
        {loading ? (
          <div className="status-card pending">Connecting to backend…</div>
        ) : (
          <>
            <div className={`status-card ${health?.status === 'ok' ? 'ok' : 'error'}`}>
              <h2>Backend Status</h2>
              <p>Service: {health?.service}</p>
              <p>Database: {health?.database}</p>
            </div>

            <div className={`status-card ${ping ? 'ok' : 'error'}`}>
              <h2>Ping</h2>
              <p>{ping ? 'pong ✓' : 'failed ✗'}</p>
            </div>

            <div className="info-card">
              <h2>Next Steps</h2>
              <ul>
                <li>Phase 2: Database models and seed data</li>
                <li>Phase 3: PDF extraction and LLM integration</li>
                <li>Phase 4–6: Matching, validation, decision engine</li>
                <li>Phase 7: Full frontend dashboard</li>
              </ul>
            </div>
          </>
        )}
      </main>
    </div>
  )
}

export default App
