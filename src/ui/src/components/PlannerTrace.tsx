import { useState } from 'react'
import type { TraceEntry } from '../types'

interface Props {
  trace: TraceEntry[]
}

function summariseParams(params: Record<string, unknown>): string {
  const keys = Object.keys(params)
  if (keys.length === 0) return '—'
  return keys
    .slice(0, 3)
    .map((k) => `${k}: ${JSON.stringify(params[k])}`)
    .join(', ')
}

export function PlannerTrace({ trace }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div className="card">
      <button className="card-title collapsible" onClick={() => setOpen((o) => !o)}>
        Planner Trace ({trace.length} step{trace.length !== 1 ? 's' : ''}) {open ? '▲' : '▼'}
      </button>
      {open && (
        <ol className="trace-list">
          {trace.length === 0 && <li className="empty-state">No steps yet.</li>}
          {trace.map((entry, i) => (
            <li key={i} className="trace-item">
              <span className="trace-step">{i + 1}</span>
              <span className="trace-action">{entry.action_type}</span>
              <span className="trace-params">{summariseParams(entry.params)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
