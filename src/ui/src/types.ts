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

export interface RosterRow {
  user_id: string
  username: string
  band: AgeBand
  confidence: number
  posture: PostureLevel
  message_count: number
  top_cues: string[]
  step_up: boolean
  evasion: boolean
}

// ── Performance tab: accuracy eval (/v1/eval) ────────────────────
export interface BandMetric {
  precision: number
  recall: number
  f1: number
}

export interface EvalMetrics {
  overall_accuracy: number
  settled_rate: number
  total_samples: number
  confusion_matrix: Record<string, Record<string, number>>
  per_band: Record<string, BandMetric>
  by_difficulty: Record<string, Record<string, number>>
}

export interface EvalResult {
  eval_model: string
  inference_mode: string
  settle_confidence_threshold: number
  metrics: EvalMetrics
}

// ── Performance tab: throughput/latency benchmark (/v1/benchmark) ──
export interface BenchmarkRow {
  concurrency: number
  p50_ms: number
  p95_ms: number
  success: number
  total: number
  tok_per_sec: number
  cost_per_1k_turns: number | null
}

export interface BenchmarkResult {
  rows: BenchmarkRow[]
  headline: {
    sessions_per_gpu: number | null
    p95_ms: number | null
    tok_per_sec: number | null
    cost_per_1k_turns: number | null
  }
  gpu_hourly_cost: number
}
