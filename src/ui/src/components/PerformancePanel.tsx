import { useState } from 'react'
import type { EvalResult, BenchmarkResult } from '../types'
import { runEval, runBenchmark } from '../api/agentClient'
import { AmdTelemetryBadge } from './AmdTelemetryBadge'

// Captured headline numbers from the real AMD Instinct MI300X run (2026-07-09),
// gemma-3-27b-it bf16. Shown as the reference; the buttons below reproduce them live.
const CAPTURED = [
  { label: 'Sessions / GPU', value: '≥10', sub: 'p95 < 5s through 10 concurrent' },
  { label: 'p95 latency', value: '2.1 s', sub: 'per turn (3.1 s @ 10 concurrent)' },
  { label: 'Sustained tok/s', value: '598.6', sub: '@ concurrency 10' },
  { label: '$ / 1k turns', value: '$0.139', sub: 'at $1.99/hr MI300X' },
  { label: 'Eval accuracy', value: '100%', sub: '15/15 synthetic fixtures' },
]

const BAND_COLS = ['child', 'teen', 'adult', 'unknown']

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`
}

export function PerformancePanel() {
  const [evalResult, setEvalResult] = useState<EvalResult | null>(null)
  const [evalLoading, setEvalLoading] = useState(false)
  const [evalError, setEvalError] = useState<string | null>(null)

  const [bench, setBench] = useState<BenchmarkResult | null>(null)
  const [benchLoading, setBenchLoading] = useState(false)
  const [benchError, setBenchError] = useState<string | null>(null)

  async function handleEval() {
    setEvalLoading(true)
    setEvalError(null)
    try {
      setEvalResult(await runEval())
    } catch (e) {
      setEvalError(e instanceof Error ? e.message : String(e))
    } finally {
      setEvalLoading(false)
    }
  }

  async function handleBench() {
    setBenchLoading(true)
    setBenchError(null)
    try {
      setBench(await runBenchmark({ concurrency: [1, 5, 10], samples: 20, gpu_hourly_cost: 1.99 }))
    } catch (e) {
      setBenchError(e instanceof Error ? e.message : String(e))
    } finally {
      setBenchLoading(false)
    }
  }

  const m = evalResult?.metrics

  return (
    <div className="perf">
      <div className="perf-header-row">
        <div style={{ flex: '1 1 0', minWidth: 0 }}>
          <h2 className="card-title">Measured on AMD Instinct MI300X — gemma-3-27b-it</h2>
          <div className="perf-stat-row">
            {CAPTURED.map((s) => (
              <div className="card perf-stat" key={s.label}>
                <div className="perf-stat-value">{s.value}</div>
                <div className="perf-stat-label">{s.label}</div>
                <div className="sub-label">{s.sub}</div>
              </div>
            ))}
          </div>
        </div>
        <AmdTelemetryBadge />
      </div>

      {/* ── Accuracy eval ─────────────────────────────────────── */}
      <div className="card perf-test">
        <h2 className="card-title">Accuracy eval — 15 synthetic fixtures</h2>
        <p className="sub-label">
          Replays child / teen / adult / adversarial transcripts through the pipeline and
          scores band accuracy, settle rate, and a confusion matrix. Deterministic Python
          decides the band; the model only estimates.
        </p>
        <code className="perf-cmd">python scripts/eval_pipeline_against_synthetic.py</code>
        <div className="roster-controls">
          <button className="btn btn-demo" onClick={handleEval} disabled={evalLoading}>
            {evalLoading ? 'Running eval…' : '▶ Run accuracy eval'}
          </button>
        </div>
        {evalError && <div className="error-banner">{evalError}</div>}
        {m && (
          <div className="perf-results">
            <div className="perf-stat-row">
              <div className="card perf-stat">
                <div className="perf-stat-value">{pct(m.overall_accuracy)}</div>
                <div className="perf-stat-label">Accuracy</div>
              </div>
              <div className="card perf-stat">
                <div className="perf-stat-value">{pct(m.settled_rate)}</div>
                <div className="perf-stat-label">Settled rate</div>
              </div>
              <div className="card perf-stat">
                <div className="perf-stat-value">{m.total_samples}</div>
                <div className="perf-stat-label">Samples</div>
              </div>
              <div className="card perf-stat">
                <div className="perf-stat-value">{evalResult?.inference_mode}</div>
                <div className="perf-stat-label">Mode</div>
              </div>
            </div>

            <h3 className="sub-label">Confusion matrix (rows = truth, cols = predicted)</h3>
            <table className="roster-table">
              <thead>
                <tr>
                  <th>truth ↓ / pred →</th>
                  {BAND_COLS.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.keys(m.confusion_matrix).map((gt) => (
                  <tr key={gt}>
                    <td><span className={`badge band-${gt}`}>{gt}</span></td>
                    {BAND_COLS.map((pred) => {
                      const v = m.confusion_matrix[gt]?.[pred] ?? 0
                      return (
                        <td key={pred} style={v > 0 && gt === pred ? { fontWeight: 700 } : undefined}>
                          {v}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>

            <h3 className="sub-label">Per-band precision / recall / F1</h3>
            <table className="roster-table">
              <thead>
                <tr><th>band</th><th>precision</th><th>recall</th><th>F1</th></tr>
              </thead>
              <tbody>
                {Object.entries(m.per_band).map(([band, bm]) => (
                  <tr key={band}>
                    <td>{band}</td>
                    <td>{bm.precision.toFixed(3)}</td>
                    <td>{bm.recall.toFixed(3)}</td>
                    <td>{bm.f1.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Throughput / latency benchmark ────────────────────── */}
      <div className="card perf-test">
        <h2 className="card-title">Throughput + latency benchmark</h2>
        <p className="sub-label">
          Fires synthetic turns through the pipeline at increasing concurrency; reports p50/p95
          gate→posture latency, sustained tok/s (from vLLM /metrics), and $/1k turns.
        </p>
        <code className="perf-cmd">
          python scripts/benchmark_roster.py --concurrency 1 5 10 --samples 50 --gpu-hourly-cost 1.99
        </code>
        <div className="roster-controls">
          <button className="btn btn-demo" onClick={handleBench} disabled={benchLoading}>
            {benchLoading ? 'Running benchmark…' : '▶ Run latency + throughput benchmark'}
          </button>
        </div>
        {benchError && <div className="error-banner">{benchError}</div>}
        {bench && (
          <table className="roster-table">
            <thead>
              <tr>
                <th>concurrency</th>
                <th>p50 (ms)</th>
                <th>p95 (ms)</th>
                <th>tok/s</th>
                <th>$/1k turns</th>
                <th>success</th>
              </tr>
            </thead>
            <tbody>
              {bench.rows.map((r) => (
                <tr key={r.concurrency}>
                  <td>{r.concurrency}</td>
                  <td>{r.p50_ms}</td>
                  <td>{r.p95_ms}</td>
                  <td>{r.tok_per_sec || '—'}</td>
                  <td>{r.cost_per_1k_turns != null ? `$${r.cost_per_1k_turns}` : '—'}</td>
                  <td>{r.success}/{r.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {bench && bench.headline.tok_per_sec === 0 && (
          <p className="sub-label">
            tok/s and $/1k show “—” because no vLLM /metrics endpoint is reachable (offline /
            deterministic mode). On the MI300X these populate with live numbers.
          </p>
        )}
      </div>
    </div>
  )
}
