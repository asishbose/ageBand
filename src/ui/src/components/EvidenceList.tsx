import type { EvidenceSummary } from '../types'

interface Props {
  evidence: EvidenceSummary | null
}

export function EvidenceList({ evidence }: Props) {
  if (!evidence || evidence.cues.length === 0) {
    return (
      <div className="card">
        <h2 className="card-title">Evidence Cues</h2>
        <p className="empty-state">No cues collected yet.</p>
      </div>
    )
  }

  return (
    <div className="card">
      <h2 className="card-title">Evidence Cues</h2>
      <p className="sub-label">
        Corroboration score: {Math.round(evidence.corroboration_score * 100)}% · {evidence.turn_count} turn(s)
      </p>
      <ul className="cue-list">
        {evidence.cues.map((cue, i) => (
          <li key={i} className="cue-item">
            <span className="chip cue-type">{cue.type}</span>
            <span className="cue-value">{cue.value}</span>
            <div className="mini-bar" title={`Weight: ${cue.weight.toFixed(2)}`}>
              <div className="mini-bar-fill" style={{ width: `${Math.round(cue.weight * 100)}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
