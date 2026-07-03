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

export function PostureDisplay({ posture }: Props) {
  const { cls, label } = POSTURE_STYLES[posture.level]
  const activeFlags = Object.entries(posture.flags).filter(([, v]) => v)

  return (
    <div className="card">
      <h2 className="card-title">Safety Posture</h2>
      <span className={`badge posture-badge ${cls}`} data-testid="posture-badge">
        {label}
      </span>
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
