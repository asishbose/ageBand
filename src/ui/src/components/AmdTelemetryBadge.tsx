/**
 * AmdTelemetryBadge — live AMD GPU / vLLM throughput badge.
 *
 * Polls GET /health every 5 seconds for the `telemetry` block added by Phase P1-D.
 * When telemetry is unavailable (offline mode / no GPU), shows a plainly-labelled
 * "offline" state rather than stale or fabricated numbers.
 */

import { useEffect, useState } from 'react'

interface Telemetry {
  available: boolean
  reason?: string
  gpu_model: string
  rocm_version: string
  vram_used_mb: number | string
  vram_total_mb: number | string
  tok_per_sec: number | string
  running_requests: number | string
  extractor_model: string
  estimator_model: string
}

const POLL_INTERVAL_MS = 5_000

async function fetchTelemetry(): Promise<Telemetry | null> {
  try {
    const resp = await fetch('/health')
    if (!resp.ok) return null
    const data = await resp.json()
    return (data?.telemetry as Telemetry) ?? null
  } catch {
    return null
  }
}

function TelemetryRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', fontSize: '0.72rem' }}>
      <span style={{ color: '#94a3b8' }}>{label}</span>
      <span style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>{String(value)}</span>
    </div>
  )
}

export function AmdTelemetryBadge() {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function poll() {
      const t = await fetchTelemetry()
      if (!cancelled) {
        setTelemetry(t)
        setLoading(false)
      }
    }
    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const containerStyle: React.CSSProperties = {
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: '0.5rem',
    padding: '0.75rem 1rem',
    minWidth: '260px',
    maxWidth: '320px',
  }

  const headerStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginBottom: '0.5rem',
  }

  const dotStyle = (available: boolean): React.CSSProperties => ({
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    background: available ? '#22c55e' : '#64748b',
    flexShrink: 0,
  })

  if (loading) {
    return (
      <div style={containerStyle}>
        <div style={{ color: '#64748b', fontSize: '0.75rem' }}>Loading telemetry…</div>
      </div>
    )
  }

  const t = telemetry
  const available = t?.available ?? false

  return (
    <div style={containerStyle}>
      <div style={headerStyle}>
        <div style={dotStyle(available)} />
        <span style={{ color: '#f1f5f9', fontWeight: 600, fontSize: '0.8rem' }}>
          AMD Instinct MI300X
        </span>
        {!available && (
          <span style={{ color: '#64748b', fontSize: '0.7rem', marginLeft: 'auto' }}>
            offline
          </span>
        )}
      </div>

      {available && t ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
          <TelemetryRow label="GPU" value={t.gpu_model} />
          <TelemetryRow label="ROCm" value={t.rocm_version} />
          <TelemetryRow
            label="VRAM"
            value={
              t.vram_used_mb !== 'N/A' && t.vram_total_mb !== 'N/A'
                ? `${t.vram_used_mb} / ${t.vram_total_mb} MB`
                : 'N/A'
            }
          />
          <TelemetryRow
            label="Tok/s"
            value={typeof t.tok_per_sec === 'number' ? t.tok_per_sec.toFixed(1) : t.tok_per_sec}
          />
          <TelemetryRow label="In-flight" value={t.running_requests} />
          <div style={{ borderTop: '1px solid #334155', marginTop: '0.4rem', paddingTop: '0.4rem' }}>
            <TelemetryRow label="Extractor" value={t.extractor_model || 'N/A'} />
            <TelemetryRow label="Estimator" value={t.estimator_model || 'N/A'} />
          </div>
        </div>
      ) : (
        <div style={{ color: '#64748b', fontSize: '0.72rem' }}>
          {t?.reason ?? 'No AMD GPU detected — running in offline/deterministic mode.'}
        </div>
      )}
    </div>
  )
}
