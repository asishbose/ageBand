export type AgeBand = 'child' | 'teen' | 'adult' | 'unknown'
export type PostureLevel = 'standard' | 'caution' | 'restricted' | 'blocked'
export type StepUpAction = 'confirm' | 'restrict' | 'handoff'

export interface Cue {
  type: string
  value: string
  weight: number
}

export interface EvidenceSummary {
  session_id: string
  cues: Cue[]
  corroboration_score: number
  turn_count: number
}

export interface SafetyPosture {
  level: PostureLevel
  flags: Record<string, boolean>
}

export interface StepUpMessage {
  message_text: string
  action: StepUpAction
}

export interface TraceEntry {
  action_type: string
  params: Record<string, unknown>
  result?: unknown
}

export interface SessionState {
  session_id: string
  band: AgeBand
  confidence: number
  posture: SafetyPosture
  evidence: EvidenceSummary | null
  trace: TraceEntry[]
  step_up: StepUpMessage | null
}
