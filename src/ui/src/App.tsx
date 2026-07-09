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
import { PerformancePanel } from './components/PerformancePanel'
import { ChatTranscript, type TranscriptEntry } from './components/ChatTranscript'

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

// Continuous simulator: a long rotating stream fed into ONE evolving session so
// the band/confidence/posture visibly builds over many turns.
const CONTINUOUS_POOL: string[] = [
  'hey what’s up',
  'just got home from school, so much homework ugh',
  'my mom won’t let me stay up late on a school night',
  'i’m in 7th grade btw',
  'we played tag at recess today lol',
  'can you help me with my science project?',
  'my teacher assigned like 3 worksheets',
  'i can’t wait for summer break',
  'my parents set a curfew for the weekend',
  'do you play video games? i play after homework',
  'i got in trouble for texting in class',
  'what should i be for halloween?',
]

const INITIAL_STATE: SessionState = {
  session_id: '',
  band: 'unknown',
  confidence: 0,
  posture: { level: 'standard', flags: {} },
  evidence: null,
  trace: [],
  step_up: null,
}

// crypto.randomUUID() only exists in a secure context (HTTPS or localhost).
// Served over plain HTTP to a public IP (e.g. an AMD GPU box) it is undefined
// and would throw on render, blanking the page. Fall back to a Math.random
// v4 UUID in that case.
function genId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c && typeof c.randomUUID === 'function') {
    return c.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    const v = ch === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export function App() {
  // Apply dark theme when ?theme=dark is present in the URL.
  // This is the ONLY consumer of data-theme="dark" — the default (:root) is never touched.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('theme') === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark')
    }
  }, [])

  const sessionId = useRef(genId())
  const [state, setState] = useState<SessionState>({ ...INITIAL_STATE, session_id: sessionId.current })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [demoQueue, setDemoQueue] = useState<DemoFixture>([])
  const [demoName, setDemoName] = useState<string | null>(null)
  const [view, setView] = useState<'session' | 'roster' | 'performance'>('session')
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([])
  const [streaming, setStreaming] = useState(false)
  const transcriptId = useRef(0)
  const streamIdx = useRef(0)

  // Drain the demo/stream queue one message at a time (900ms apart).
  useEffect(() => {
    if (demoQueue.length === 0) return
    const [next, ...rest] = demoQueue
    const timer = setTimeout(async () => {
      await handleSend(next.text)
      setDemoQueue(rest)
    }, 900)
    return () => clearTimeout(timer)
  }, [demoQueue])  // eslint-disable-line react-hooks/exhaustive-deps

  // Continuous mode: when the queue drains and streaming is on, refill the next
  // chunk so the same session keeps evolving until the user stops it.
  useEffect(() => {
    if (!streaming || demoQueue.length > 0) return
    const chunk: DemoFixture = []
    for (let k = 0; k < 4; k++) {
      chunk.push({ role: 'user', text: CONTINUOUS_POOL[streamIdx.current % CONTINUOUS_POOL.length] })
      streamIdx.current += 1
    }
    setDemoQueue(chunk)
  }, [streaming, demoQueue])

  async function handleSend(text: string) {
    setLoading(true)
    setError(null)
    try {
      const next = await sendTurn(sessionId.current, text)
      setState(next)
      transcriptId.current += 1
      setTranscript((prev) => [
        ...prev,
        {
          id: transcriptId.current,
          text,
          band: next.band,
          confidence: next.confidence,
          posture: next.posture.level,
        },
      ])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  function handleStepUpAction(action: StepUpAction) {
    handleSend(`[step-up-response:${action}]`).catch(() => undefined)
  }

  function resetSession() {
    sessionId.current = genId()
    setState({ ...INITIAL_STATE, session_id: sessionId.current })
    setTranscript([])
    transcriptId.current = 0
  }

  function startDemo(name: string) {
    setStreaming(false)
    resetSession()
    setDemoName(name)
    setDemoQueue([...DEMOS[name]])
  }

  function startContinuous() {
    resetSession()
    setDemoName('Continuous stream')
    streamIdx.current = 0
    setDemoQueue([])
    setStreaming(true)
  }

  function stopStream() {
    setStreaming(false)
    setDemoQueue([])
  }

  const isDemoRunning = demoQueue.length > 0 || streaming

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
          <button
            className={`btn btn-tab ${view === 'performance' ? 'btn-tab-active' : ''}`}
            onClick={() => setView('performance')}
          >
            Performance
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
            {streaming ? (
              <button className="btn btn-restrict" onClick={stopStream}>
                ■ Stop stream
              </button>
            ) : (
              <button
                className={`btn btn-demo ${demoName === 'Continuous stream' ? 'btn-demo-active' : ''}`}
                onClick={startContinuous}
                disabled={isDemoRunning}
              >
                ▶ Continuous stream
              </button>
            )}
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

      {view === 'performance' && (
        <main className="app-main">
          <div style={{ flex: '1 1 0', minWidth: 0 }}>
            <PerformancePanel />
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
          <ChatTranscript entries={transcript} />
        </div>

        <aside className="sidebar-col">
          <PlannerTrace trace={state.trace} />
        </aside>
      </main>
      )}
    </div>
  )
}
