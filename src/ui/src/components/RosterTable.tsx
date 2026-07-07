import { useState } from 'react'
import type { RosterRow } from '../types'
import { fetchRoster } from '../api/agentClient'

const BAND_COLOR: Record<string, string> = {
  child: '#c62828',
  teen: '#ef6c00',
  adult: '#2e7d32',
  unknown: '#616161',
}
const POSTURE_COLOR: Record<string, string> = {
  standard: '#2e7d32',
  caution: '#f9a825',
  restricted: '#ef6c00',
  blocked: '#c62828',
}

export function RosterTable() {
  const [rows, setRows] = useState<RosterRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  async function load(exportJson?: unknown) {
    setLoading(true)
    setError(null)
    try {
      setRows(await fetchRoster(exportJson))
      setLoaded(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const parsed = JSON.parse(await file.text())
      await load(parsed)
    } catch {
      setError('Could not parse that file as DiscordChatExporter JSON.')
    }
  }

  return (
    <div className="roster">
      <div className="roster-controls">
        <button className="btn btn-demo" onClick={() => load()} disabled={loading}>
          {loading ? 'Analyzing…' : '▶ Load sample export'}
        </button>
        <label className="btn btn-demo" style={{ cursor: 'pointer' }}>
          ⬆ Upload export
          <input type="file" accept="application/json,.json" onChange={onFile} style={{ display: 'none' }} />
        </label>
        <span className="roster-hint">
          Replays a DiscordChatExporter export — one AgeBand session per user. Upload
          your own <code>chat_export.json</code> or use the bundled sample.
        </span>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {loaded && rows.length === 0 && !loading && <p>No users found in export.</p>}
      {rows.length > 0 && (
        <table className="roster-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Band</th>
              <th>Confidence</th>
              <th>Posture</th>
              <th>Msgs</th>
              <th>Top cues</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.user_id}>
                <td>{r.username}</td>
                <td>
                  <span className="pill" style={{ background: BAND_COLOR[r.band] }}>
                    {r.band}
                  </span>
                </td>
                <td>
                  <div className="conf-bar">
                    <div
                      className="conf-fill"
                      style={{ width: `${Math.round(r.confidence * 100)}%` }}
                    />
                    <span className="conf-num">{r.confidence.toFixed(2)}</span>
                  </div>
                </td>
                <td>
                  <span className="pill" style={{ background: POSTURE_COLOR[r.posture] }}>
                    {r.posture}
                  </span>
                </td>
                <td>{r.message_count}</td>
                <td className="cues-cell">{r.top_cues.join(', ') || '—'}</td>
                <td>
                  {r.step_up && <span className="flag flag-stepup">step-up</span>}
                  {r.evasion && <span className="flag flag-evasion">evasion</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
