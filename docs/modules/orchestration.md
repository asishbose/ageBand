# Module: `orchestration` — Planner-Supervisor & Runtime Wiring (M9/M10)

**Package:** `src/orchestration/`  
**Phase:** C (serial join — built last, after all Phase B modules)  
**LLM calls:** Yes — planner-supervisor (in production), + delegate calls to M2/M4/M7  
**Protocol:** `IOrchestration`

---

## Purpose

Orchestration is the **safety-critical integration layer**. It wires all modules together under a planner-supervisor loop, enforces all safety invariants via deterministic guardrails, exposes an HTTP API for the host product and UI, and verifies the AMD/vLLM serving endpoint at startup.

---

## Files

| File | Contents |
|---|---|
| `runner.py` | `OrchestrationService` — planner loop, routing, action dispatch |
| `guardrails.py` | `PlannerState`, `enforce_preconditions`, `check_iteration_cap`, `SAFE_DEFAULT_POSTURE` |
| `api.py` | FastAPI app (`/health`, `/v1/turn`) |
| `amd_check.py` | AMD/vLLM endpoint startup verification + `collect_amd_telemetry()` for live GPU/throughput metrics |
| `planner_supervisor.yaml` | tinyagent YAML — LLM planner config + delegate wiring |
| `ageband_agent.yaml` | Root tinyagent entrypoint |
| `prompts/planner_supervisor_prompt.md` | Planner system prompt with explicit prohibitions |

---

## Planner Loop

```
run_turn(TurnEvent)
  ctx = gateway.ingest(turn)
  for iteration in range(MAX_ITERATIONS):
    if iteration_cap_hit: return SAFE_DEFAULT_POSTURE     # fail closed
    action = _route(state)                                # deterministic in lean build
    enforce_preconditions(action, state)                  # raises GuardrailViolationError if invalid
    result = _execute(action)
    record_action_completed(action, state)
    if done: break
  return posture
```

**Normal execution sequence:**
```
gate_check → [analyze path:]
  delegate_extract → update_evidence → read_evidence →
  delegate_estimate → compute_confidence → policy_decide →
  emit_posture → [step_up path:] delegate_stepup
```

---

## Guardrails

`guardrails.py` enforces **7 safety invariants** — all checked deterministically before any action executes. tinyagent will run whatever the LLM planner requests; these preconditions are the safety net.

| # | Invariant | Error if violated |
|---|---|---|
| 1 | `emit_posture` requires `policy_decided` | GuardrailViolationError |
| 2 | `policy_decide` requires `confidence_computed` | GuardrailViolationError |
| 3 | `compute_confidence` requires `estimate_done` | GuardrailViolationError |
| 4 | `delegate_extract` requires `gate_checked` | GuardrailViolationError |
| 5 | `update_evidence` requires `extract_done` | GuardrailViolationError |
| 6 | `persist_confirmed` requires `confirmed=True` | GuardrailViolationError |
| 7 | Iteration cap (`MAX_ITERATIONS=8`) hit | Returns `SAFE_DEFAULT_POSTURE` |

Any `GuardrailViolationError` or unhandled exception during action execution causes the runner to immediately return `SAFE_DEFAULT_POSTURE` (level=caution) and log the rejection.

### Safe Default Posture

```python
SAFE_DEFAULT_POSTURE = safety_posture(
    level="caution",
    flags={"mature_content": False, "feature_full": True, "tone_strict": True}
)
```

Applied on: iteration cap, guardrail violation, unhandled exception, unknown route.

---

## Routing (Lean Build)

`_route()` uses a module-level sequence list to avoid a long `if/elif` chain:

```python
_ROUTE_SEQUENCE = [
    ("gate_checked",        "gate_check"),
    ("extract_done",        "_gate_or_finish"),   # special: check gate result
    ("evidence_read",       "update_evidence"),
    ("estimate_done",       "delegate_estimate"),
    ("confidence_computed", "compute_confidence"),
    ("policy_decided",      "policy_decide"),
    ("posture_emitted",     "emit_posture"),
    ("step_up_requested",   "_stepup_if_needed"),
]
```

In the full tinyagent build, `_route()` is replaced by the LLM planner. The guardrails apply regardless of which routing strategy is active.

---

## Action Execution Dispatch

Actions dispatch to isolated handler methods. Each handler has CC ≤ 2 (grade A):

| Action | Handler | Side effect |
|---|---|---|
| `gate_check` | `_handle_gate_check` | Reads GateService |
| `delegate_extract` | `_handle_extract` | Calls LLM (or mock) |
| `update_evidence` | `_handle_update_evidence` | Writes to EvidenceFabric |
| `read_evidence` | `_handle_read_evidence` | Reads EvidenceFabric |
| `delegate_estimate` | `_handle_estimate` | Calls LLM (or mock) |
| `compute_confidence` | `_handle_confidence` | Pure Python math |
| `policy_decide` | `_handle_policy` | Pure Python table lookup |
| `emit_posture` | `_handle_emit_posture` | Builds safety_posture |
| `delegate_stepup` | `_handle_stepup` | Calls LLM (or mock) |
| `persist_confirmed` | `_handle_persist` | Writes confirmed band |

---

## HTTP API (`api.py`)

| Route | Method | Description |
|---|---|---|
| `/health` | GET | Liveness check — returns `{"status": "ok"}` |
| `/v1/turn` | POST | Process a turn; returns full verbose session state |
| `/v1/chat/completions` | POST | OpenAI-compatible endpoint — same pipeline; returns `SessionState` in the `choices[0].message.content` field (used by the UI's `agentClient`) |
| `/v1/confirm` | POST | Persist a confirmed age band for a session (`{"session_id": ..., "band": ...}`) |

### Turn request

```json
{
  "session_id": "sess-abc123",
  "turn_text": "I'm in 8th grade and need help with homework.",
  "turn_number": 1
}
```

### Turn response (verbose)

`/v1/turn` now returns the full session state, not just `posture`. The legacy `"posture"` key is preserved for back-compat:

```json
{
  "session_id": "sess-abc123",
  "band": "teen",
  "confidence": 0.61,
  "posture": {"level": "restricted", "flags": {"mature_content": false, "feature_full": false, "tone_strict": true}},
  "evidence": {"session_id": "sess-abc123", "cues": [...], "corroboration_score": 0.72, "turn_count": 3},
  "trace": [{"action_type": "gate_check", "params": {}}, ...],
  "step_up": null
}
```

### Confirm request

```json
{"session_id": "sess-abc123", "band": "adult"}
```

This calls `persist_confirmed(session_id, band, confirmed=True)` — the confirmed band overrides inference on all future turns for that session.

---

## AMD Endpoint Check and Telemetry (`amd_check.py`)

At startup (unless `SKIP_AMD_CHECK=true`), the service calls `verify_amd_endpoint()`:

1. GET `{LOCAL_API_BASE}/models`
2. Verifies HTTP 200
3. If `LOCAL_MODEL` is set, checks the model is in the `data[]` list
4. Raises `RuntimeError` with a helpful message if any check fails

In degraded mode (check fails at startup), the service logs a warning and continues — it will fall back to mock/empty responses until the vLLM endpoint becomes available.

### `collect_amd_telemetry()` — Live GPU Telemetry (Phase P1-D)

Provides real-time AMD GPU + vLLM throughput data for the UI telemetry badge.
Called by the `/health` endpoint:

```python
@app.get("/health")
async def health() -> dict[str, object]:
    from src.orchestration.amd_check import collect_amd_telemetry
    return {"status": "ok", "telemetry": collect_amd_telemetry()}
```

**Graceful degrade (required, explicitly tested):** when `AGEBAND_INFERENCE_MODE=deterministic` or when `amd-smi`/`rocm-smi` cannot be found and vLLM metrics are unreachable, the function returns:

```json
{
  "available": false,
  "reason": "deterministic/offline mode — no LLM endpoint configured",
  "gpu_model": "unavailable",
  "tok_per_sec": "N/A",
  ...
}
```

All required keys (`available`, `gpu_model`, `rocm_version`, `vram_used_mb`, `vram_total_mb`, `tok_per_sec`, `running_requests`, `extractor_model`, `estimator_model`) are **always present** even in the degrade path — the UI badge can safely access any key without defensive checks.

Telemetry sources (scraped synchronously, graceful on any failure):
- `_scrape_vllm_metrics()` — Prometheus `/metrics` endpoint (running_requests, gen_tokens_total, gpu_cache_usage_pct)
- `_query_amd_smi()` — shells out to `amd-smi showmeminfo vram --json` (or `rocm-smi`); configurable via `AMD_SMI_PATH`/`ROCM_SMI_PATH`

---

## Configuration

| Env var | Default | Description |
|---|---|---|
| `LOCAL_API_BASE` | `http://localhost:8000/v1` | vLLM/AMD OpenAI-compatible endpoint |
| `LOCAL_MODEL` | `google/gemma-3-4b-it` | Shared fallback model (overridden by `EXTRACTOR_MODEL`/`ESTIMATOR_MODEL`) |
| `LOCAL_API_KEY` | `EMPTY` | API key (vLLM default = "EMPTY") |
| `AGEBAND_INFERENCE_MODE` | `auto` | `deterministic` / `llm` / `auto` — selects offline or LLM inference path |
| `PLANNER_MAX_ITERATIONS` | `8` | Iteration cap per turn |
| `SKIP_AMD_CHECK` | `false` | Skip endpoint verification at startup |

---

## tinyagent YAML

`planner_supervisor.yaml` configures the runtime LLM planner with:
- All deterministic tools (`gate_check`, `read_evidence`, etc.)
- Three delegate subagents (`signal_extractor`, `ageband_estimator`, `stepup_composer`)
- `max_iterations: 8` (matches `PLANNER_MAX_ITERATIONS`)
- `tool_choice: required` — planner must always call a tool, never reply directly

---

## Interface

```python
class IOrchestration(Protocol):
    async def run_turn(self, turn: TurnEvent) -> safety_posture: ...
```

---

## Complexity budget

| Method | CC | Grade |
|---|---|---|
| `run_turn` | 4 | A |
| `_step` | 5 | A |
| `_resolve_route` | 7 | B (justified: 3-branch router) |
| All handlers | 1–2 | A |

**Maintainability index note:** `runner.py` currently scores MI ≈ 37 (radon grade A, below the project's MI ≥ 75 target). This reflects structural breadth — the file is the integration seam and owns the planner loop, all action handlers, result appliers, and dispatch table. Every individual method stays at CC grade A; the low MI is a consequence of the file's size, not of tangled logic. The appropriate refactor (splitting into `ActionExecutor` + `ResultApplier` sub-objects) is deferred until the action set stabilises post-hackathon.

---

## Tests

```
tests/unit/orchestration/test_guardrails.py           — all 7 invariants, happy path, cap
tests/unit/orchestration/test_amd_check.py            — reachable, timeout, model mismatch; collect_amd_telemetry degrade path
tests/integration/test_api.py                         — /v1/turn (verbose), /v1/chat/completions, /v1/confirm
tests/integration/test_happy_path.py                  — adult, teen, unknown
tests/integration/test_gate_short_circuit.py          — settled session reuse
tests/integration/test_stepup_flow.py                 — child+high confidence
tests/integration/test_guardrail_integration.py       — out-of-order rejection
tests/e2e/test_offline_scenarios.py                   — all four demo scenarios (offline/deterministic path)
tests/e2e/test_clear_adult.py                         — standard posture, fairness
tests/e2e/test_young_teen.py                          — elevated posture
tests/e2e/test_ambiguous_adult.py                     — fairness: unknown+low → standard
tests/e2e/test_adversarial.py                         — evasion detection
```
