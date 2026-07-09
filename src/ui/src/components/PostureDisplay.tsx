import type { SafetyPosture, PostureLevel } from '../types'

interface Props {
  posture: SafetyPosture
}

const POSTURE_STYLES: Record<PostureLevel, { cls: string; label: string }> = {
  standard: { cls: 'posture-standard', label: 'Standard' },
  caution: { cls: 'posture-caution', label: 'Caution' },
  restricted: { cls: 'posture-restricted', label: 'Restricted' },
  blocked: { cls: 'posture-blocked', label: 'Blocked' },
}

// Ordered lowest → highest severity: drives the posture ladder/gauge.
const POSTURE_ORDER: PostureLevel[] = ['standard', 'caution', 'restricted', 'blocked']

export function PostureDisplay({ posture }: Props) {
  const { cls, label } = POSTURE_STYLES[posture.level]
  const activeFlags = Object.entries(posture.flags).filter(([, v]) => v)
  const activeIndex = POSTURE_ORDER.indexOf(posture.level)

  return (
    <div className="card">
      <h2 className="card-title">Safety Posture</h2>
      <span className={`badge posture-badge ${cls}`} data-testid="posture-badge">
        {label}
      </span>
      {/* Posture ladder: all four levels shown as a gauge; current one lit, rest dimmed */}
      <div className="posture-ladder" aria-hidden="true">
        {POSTURE_ORDER.map((level, i) => (
          <div
            key={level}
            className={`posture-rung posture-rung-${level}${i === activeIndex ? ' posture-rung-active' : ''}`}
          />
        ))}
      </div>
      {activeFlags.length > 0 && (
        <div className="flags">
          {activeFlags.map(([key]) => (
            <span key={key} className="chip">{key}</span>
          ))}
        </div>
      )}
    </div>
  )
}
