import type {
  SessionState,
  RosterRow,
  EvalResult,
  BenchmarkResult,
} from '../types'

const BASE = '/v1'

export async function fetchRoster(exportJson?: unknown): Promise<RosterRow[]> {
  const res = await fetch(`${BASE}/roster`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(exportJson ?? {}),
  })
  if (!res.ok) throw new Error(`Roster error: ${res.status}`)
  const data = (await res.json()) as { rows: RosterRow[] }
  return data.rows
}

// Runs the 15-fixture synthetic accuracy eval in-process on the agent.
export async function runEval(): Promise<EvalResult> {
  const res = await fetch(`${BASE}/eval`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) throw new Error(`Eval error: ${res.status}`)
  return (await res.json()) as EvalResult
}

// Runs a per-turn latency + throughput sweep on the agent.
export async function runBenchmark(params?: {
  concurrency?: number[]
  samples?: number
  gpu_hourly_cost?: number
}): Promise<BenchmarkResult> {
  const res = await fetch(`${BASE}/benchmark`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params ?? {}),
  })
  if (!res.ok) throw new Error(`Benchmark error: ${res.status}`)
  return (await res.json()) as BenchmarkResult
}

interface TinyAgentResponse {
  choices: [{ message: { content: string } }]
}

export async function sendTurn(sessionId: string, text: string): Promise<SessionState> {
  const res = await fetch(`${BASE}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'ageband',
      messages: [{ role: 'user', content: text }],
      stream: false,
      user: sessionId,
    }),
  })
  if (!res.ok) throw new Error(`Agent error: ${res.status}`)
  const data = (await res.json()) as TinyAgentResponse
  return extractSessionState(data)
}

function extractSessionState(data: TinyAgentResponse): SessionState {
  const content = data.choices[0].message.content
  try {
    return JSON.parse(content) as SessionState
  } catch {
    return {
      session_id: 'unknown',
      band: 'unknown',
      confidence: 0,
      posture: { level: 'standard', flags: {} },
      evidence: null,
      trace: [],
      step_up: null,
    }
  }
}
