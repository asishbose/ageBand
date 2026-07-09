import type { AgeBand, PostureLevel } from '../types'

export interface TranscriptEntry {
  id: number
  text: string
  band: AgeBand
  confidence: number
  posture: PostureLevel
}

const BAND_COLOR: Record<string, string> = {
  child: '#ef4444',
  teen: '#f59e0b',
  adult: '#22c55e',
  unknown: '#64748b',
}

export function ChatTranscript({ entries }: { entries: TranscriptEntry[] }) {
  return (
    <div className="card">
      <h2 className="card-title">Chat transcript{entries.length ? ` (${entries.length})` : ''}</h2>
      {entries.length === 0 ? (
        <p className="sub-label">
          Send a message, run a demo persona, or start the continuous stream to watch turns
          arrive and the posture evolve.
        </p>
      ) : (
        <div className="transcript">
          {entries.map((e) => (
            <div className="transcript-row" key={e.id}>
              <div className="transcript-msg">{e.text}</div>
              <div className="transcript-meta">
                <span className="pill" style={{ background: BAND_COLOR[e.band] ?? '#64748b' }}>
                  {e.band}
                </span>
                <span className="transcript-conf">{Math.round(e.confidence * 100)}%</span>
                <span className={`badge posture-${e.posture}`}>{e.posture}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
