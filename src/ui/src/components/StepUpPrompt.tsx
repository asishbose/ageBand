import type { StepUpMessage, StepUpAction } from '../types'

interface Props {
  stepUp: StepUpMessage | null
  onAction: (action: StepUpAction) => void
}

const ACTION_LABELS: Record<StepUpAction, string> = {
  confirm: 'Confirm Age',
  restrict: 'Restrict Session',
  handoff: 'Hand Off',
}

export function StepUpPrompt({ stepUp, onAction }: Props) {
  if (!stepUp) return null

  return (
    <div className="card stepup-card" role="alert">
      <h2 className="card-title stepup-title">⚠ Step-Up Required</h2>
      <p className="stepup-message">{stepUp.message_text}</p>
      <div className="stepup-actions">
        {(['confirm', 'restrict', 'handoff'] as StepUpAction[]).map((action) => (
          <button
            key={action}
            className={`btn btn-${action}`}
            onClick={() => onAction(action)}
          >
            {ACTION_LABELS[action]}
          </button>
        ))}
      </div>
    </div>
  )
}
