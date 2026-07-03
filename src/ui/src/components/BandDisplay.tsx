import type { AgeBand } from '../types'

interface Props {
  band: AgeBand
  confidence: number
}

const BAND_STYLES: Record<AgeBand, { bg: string; label: string }> = {
  child: { bg: 'band-child', label: 'Child' },
  teen: { bg: 'band-teen', label: 'Teen' },
  adult: { bg: 'band-adult', label: 'Adult' },
  unknown: { bg: 'band-unknown', label: 'Unknown' },
}

export function BandDisplay({ band, confidence }: Props) {
  const { bg, label } = BAND_STYLES[band]
  const pct = Math.round(confidence * 100)

  return (
    <div className="card">
      <h2 className="card-title">Age Band</h2>
      <span className={`badge ${bg}`} data-testid="band-badge">
        {label}
      </span>
      <div className="confidence-section">
        <span className="confidence-label">Confidence: {pct}%</span>
        <div className="progress-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  )
}
