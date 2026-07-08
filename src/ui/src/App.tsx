import { useState, useEffect, useRef } from 'react'
import type { SessionState, StepUpAction } from './types'
import { sendTurn } from './api/agentClient'
import { BandDisplay } from './components/BandDisplay'
import { PostureDisplay } from './components/PostureDisplay'
import { EvidenceList } from './components/EvidenceList'
import { PlannerTrace } from './components/PlannerTrace'
import { StepUpPrompt } from './components/StepUpPrompt'
import { ChatInput } from './components/ChatInput'
import { RosterTable } from './components/RosterTable'
import { AmdTelemetryBadge } from './components/AmdTelemetryBadge'

import clearAdult from './fixtures/clear_adult.json'
import youngTeen from './fixtures/young_teen.json'
import ambiguousAdult from './fixtures/ambiguous_adult.json'
import adversarial from './fixtures/adversarial.json'

type DemoFixture = { role: string; text: string }[]

const DEMOS: Record<string, DemoFixture> = {
  'Clear Adult': clearAdult as DemoFixture,
  'Young Teen': youngTeen as DemoFixture,
  'Ambiguous Adult': ambiguousAdult as DemoFixture,
  'Adversarial': adversarial as DemoFixture,
}

const INITIAL_STATE: SessionState = {
  session_id: '',
  band: 'unknown',
  confidence: 0,
  posture: { level: 'standard', flags: {} },
  evidence: null,
  trace: [],
  step_up: null,
}

export function App() {
  const sessionId = useRef(crypto.randomUUID())
  const [state, setState] = useState<SessionState>({ ...INITIAL_STATE, session_id: sessionId.current })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [demoQueue, setDemoQueue] = useState<DemoFixture>([])
  const [demoName, setDemoName] = useState<string | null>(null)
  const [view, setView] = useState<'session' | 'roster'>('session')

  useEffect(() => {
    if (demoQueue.length === 0) return
    const [next, ...rest] = demoQueue
    const timer = setTimeout(async () => {
      await handleSend(next.text)
      setDemoQueue(rest)
    }, 900)
    return () => clearTimeout(timer)
  }, [demoQueue])  // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSend(text: string) {
    setLoading(true)
    setError(null)
    try {
      const next = await sendTurn(sessionId.current, text)
      setState(next)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  function handleStepUpAction(action: StepUpAction) {
    handleSend(`[step-up-response:${action}]`).catch(() => undefined)
  }

  function startDemo(name: string) {
    sessionId.current = crypto.randomUUID()
    setState({ ...INITIAL_STATE, session_id: sessionId.current })
    setDemoName(name)
    setDemoQueue([...DEMOS[name]])
  }

  const isDemoRunning = demoQueue.length > 0

  return (
    <div className="app">
      <header className="app-header">
        <h1>AgeBand <span className="header-sub">Live Session Monitor</span></h1>
        <div className="view-tabs">
          <button
            className={`btn btn-tab ${view === 'session' ? 'btn-tab-active' : ''}`}
            onClick={() => setView('session')}
          >
            Session
          </button>
          <button
            className={`btn btn-tab ${view === 'roster' ? 'btn-tab-active' : ''}`}
            onClick={() => setView('roster')}
          >
            Roster
          </button>
        </div>
        {view === 'session' && (
          <div className="demo-controls">
            {Object.keys(DEMOS).map((name) => (
              <button
                key={name}
                className={`btn btn-demo ${demoName === name ? 'btn-demo-active' : ''}`}
                onClick={() => startDemo(name)}
                disabled={isDemoRunning}
              >
                ▶ {name}
              </button>
            ))}
          </div>
        )}
      </header>

      {view === 'roster' && (
        <main className="app-main">
          <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 0', minWidth: 0 }}>
              <RosterTable />
            </div>
            <AmdTelemetryBadge />
          </div>
        </main>
      )}

      {view === 'session' && (
      <main className="app-main">
        <div className="primary-col">
          <div className="band-posture-row">
            <BandDisplay band={state.band} confidence={state.confidence} />
            <PostureDisplay posture={state.posture} />
          </div>
          <EvidenceList evidence={state.evidence} />
          {state.step_up && (
            <StepUpPrompt stepUp={state.step_up} onAction={handleStepUpAction} />
          )}
          {error && <div className="error-banner">{error}</div>}
          <ChatInput onSend={handleSend} disabled={loading || isDemoRunning} />
          {loading && <p className="loading-label">Processing…</p>}
        </div>

        <aside className="sidebar-col">
          <PlannerTrace trace={state.trace} />
        </aside>
      </main>
      )}
    </div>
  )
}
