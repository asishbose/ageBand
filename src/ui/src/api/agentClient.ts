import type { SessionState, RosterRow } from '../types'

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
