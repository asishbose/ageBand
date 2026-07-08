# Module: `contracts` — Shared Data Contracts

**Package:** `src/contracts/`  
**Phase:** A (serial foundation — built first, never modified by other modules)  
**Role:** Defines all Pydantic models, module interface Protocols, and custom validators shared by every other module. This is the **frozen seam** that makes parallel development safe.

---

## Purpose

`contracts` is the single source of truth for data shapes and module boundaries in AgeBand. Every module depends on `contracts`; no module depends directly on another module's concrete classes.

---

## Files

| File | Contents |
|---|---|
| `models.py` | All Pydantic v2 data models |
| `protocols.py` | Python `Protocol` interfaces for each module (runtime-checkable) |
| `validators.py` | Custom validators that extend Pydantic's built-in checks |
| `runtime.py` | `use_llm() -> bool` — LLM-primary runtime mode helper (reads `AGEBAND_INFERENCE_MODE`) |
| `llm_client.py` | OpenAI-compatible async JSON completion client with per-delegate model selection and bounded retry (Ollama / vLLM / Fireworks) |
| `embeddings_client.py` | Lightweight async embeddings client for cross-turn persona consistency (Phase 5); offline no-op when `EMBEDDING_MODEL` is unset |

> **Structural note — `llm_client.py` placement:** this file is infrastructure code (an HTTP client), not a shared data model or protocol. It lives in `contracts/` because it was added during a broad gap-fix pass. It is a **candidate for relocation** to a dedicated `llm/` or `infra/` package post-hackathon — do not move it now, just be aware the placement is a known smell.

### `runtime.py` — `use_llm()` (LLM-primary framing, Phase 0)

**LLM-primary framing:** when a model endpoint is configured, the LLM is the *primary* perception path — it runs in-language, reasoning-rich inference on AMD MI300X. The deterministic path is the explicit offline safety-net, not a co-equal alternative.

| `AGEBAND_INFERENCE_MODE` | Behaviour |
|---|---|
| `deterministic` | Always use the deterministic offline fallback (keyword extractor + rule estimator). No LLM calls. |
| `llm` | Always use the LLM path. Fails fast if no model is configured. |
| `auto` (default) | **LLM-primary:** use LLM when `LOCAL_MODEL`, `EXTRACTOR_MODEL`, or `ESTIMATOR_MODEL` is set; otherwise fall back to deterministic. |

**Invariant unchanged:** `use_llm()` controls which *perception path* runs — the LLM still never sets a weight, confidence, or safety_posture. Python decides those regardless of path.

### `llm_client.py` — `complete_json()`

Bounded retry (Phase 0 addition): up to 3 total attempts with 0.5s / 1.0s exponential backoff on transient errors (network, 5xx, JSON parse). Client errors (4xx) propagate immediately without retry. The retry window is designed to recover the `gemma4:31b` unparseable-JSON case noted in `model_comparison.md` without masking real failures or materially inflating p95 latency.

Per-delegate model helpers: `extractor_model()` → `EXTRACTOR_MODEL` (fallback `LOCAL_MODEL`); `estimator_model()` → `ESTIMATOR_MODEL` (fallback `LOCAL_MODEL`). Pass these to `complete_json(model=...)` from the service layer.

---

## Module-level constants

### `STRONG_CUE_TYPES` (Phase 11 audit — boundary fix)

```python
STRONG_CUE_TYPES: frozenset[str] = frozenset({"disclosure", "topic"})
```

The set of cue `type` values that are strong enough for `rule_estimator` to establish a band lean on their own. Previously defined as `_STRONG_TYPES` inside `src/ageband_inference/rule_estimator.py`; promoted to `contracts/models.py` during the Phase 11 conformance audit to eliminate an M2 (`signal_extraction/maturity.py`) → M4 (`ageband_inference/rule_estimator.py`) cross-module dependency that violated the architecture's "depend on contracts, not on each other" rule.

Both `rule_estimator.py` (M4) and `maturity.py` (M2) now import from `contracts.models`. `rule_estimator.py` re-exports it as `_STRONG_TYPES` for backward compatibility with tests that import it from there.

---

## Data Models

All models use `ConfigDict(extra="forbid")` — unexpected fields raise a `ValidationError` at construction time, preventing accidental data leakage or LLM hallucination of extra fields.

### `Cue`
A single age-relevant signal extracted from one turn.

```python
class Cue(BaseModel):
    type: Literal["vocab", "topic", "disclosure", "style", "reading_level"]
    value: str
    weight: float   # [0.0, 1.0] — always re-stamped from the lexicon; never from LLM
    subtype: str    # optional (default ""); e.g. "guardian_reference", "adult_self_claim"
                    # drives deterministic weight lookup in signal_extraction/lexicon.py
```

`subtype` was added in PR #1 as an additive, backward-compatible field (default `""`). Existing cues without a subtype continue to validate. The field enables the deterministic cue lexicon to assign auditable weights independent of the LLM.

### `TurnEvent`
The payload arriving at the system boundary from the host product.

```python
class TurnEvent(BaseModel):
    session_id: str
    turn_text: str
    turn_number: int   # ≥ 0
    timestamp: datetime
```

### `SignalSet`
All cues extracted from a single turn (output of M2).

```python
class SignalSet(BaseModel):
    cues: list[Cue]   # default []
```

### `AgeBandEstimate` ⚠️ NO confidence field
The LLM's proposed age band. **Critically, this model has no `confidence` field.** Confidence is always computed deterministically in `src/ageband_inference/confidence.py`.

```python
class AgeBandEstimate(BaseModel):
    band: Literal["child", "teen", "adult", "unknown"]
    cited_cues: list[str]           # cue descriptions that influenced the estimate
    evasion_flag: bool              # True if the user appears to be dodging age signals
    contradictions: list[str]       # inconsistencies in the evidence
    # Additive (Phase 4): which masking patterns fired. Empty list → no evasion.
    # Patterns: "mismatch", "deflection", "register_switching", "over_insistence"
    evasion_patterns: list[str]     # default []
```

### `GateResult`
Output of the deterministic gate (M1.5).

```python
class GateResult(BaseModel):
    action: Literal["analyze", "reuse_posture"]
    reason: str  # e.g. "settled_session", "high_confidence", "proceed"
```

### `EvidenceSummary`
Accumulated session evidence (ephemeral — never persisted as a profile).

```python
class EvidenceSummary(BaseModel):
    session_id: str
    cues: list[Cue]
    corroboration_score: float       # [0.0, 1.0] — weighted sum of cue weights
    turn_count: int
    # Additive (Phase 3): band per turn for conversation uncertainty penalty.
    band_history: list[str]          # default [] — no penalty when empty (single-turn)
    # Additive (Phase 5): cosine similarity to session centroid (embedding consistency).
    embedding_similarity: float | None  # None = offline no-op, contributes 0 penalty
```

### `Decision`
Output of the deterministic policy engine (M5).

```python
class Decision(BaseModel):
    action: Literal["apply", "step_up", "none"]
    posture_level: Literal["standard", "caution", "restricted", "blocked"]
    flags: dict[str, bool]
    reason: str   # e.g. "child_high", "teen_medium"
```

### `safety_posture`
What AgeBand emits to the host. The host product is responsible for honouring it.

```python
class safety_posture(BaseModel):  # lowercase: canonical glossary name
    level: Literal["standard", "caution", "restricted", "blocked"]
    flags: dict[str, bool]
    # Standard flag keys: mature_content, feature_full, tone_strict
```

### `PlannerAction`
A typed action request from the planner-supervisor LLM. Unknown `action_type` values are rejected at validation time (fail closed).

```python
class PlannerAction(BaseModel):
    action_type: Literal["gate_check", "read_evidence", "update_evidence",
                          "compute_confidence", "policy_decide", "emit_posture",
                          "persist_confirmed", "delegate_extract",
                          "delegate_estimate", "delegate_stepup", "finish"]
    params: dict[str, object]
```

### `StepUpMessage`
Composed by the `stepup_composer` delegate when a confirmation is needed.

```python
class StepUpMessage(BaseModel):
    message_text: str
    action: Literal["confirm", "restrict", "handoff"]
```

### `AgeBandContext`
Live per-session state carried through the planner loop.

```python
class AgeBandContext(BaseModel):
    session_id: str
    current_band: Literal["child", "teen", "adult", "unknown"]  # default "unknown"
    confidence: float          # [0.0, 1.0] — deterministic, never from LLM
    settled: bool              # True when session has stable high-confidence estimate
    turn_count: int
    evidence_summary: EvidenceSummary | None
    posture: safety_posture | None
    last_turn_text: str        # transient; populated by gateway_session.ingest()
                               # used by gate tripwire; never persisted to disk
```

`last_turn_text` was added in PR #1 as an additive, backward-compatible field (default `""`). It is populated on every call to `GatewaySessionService.ingest()` but is intentionally **never written to durable storage** — it is a within-turn scratch field used by the always-on tripwire in `gate_service.py`.

---

## Protocols

All Protocols are `@runtime_checkable`, allowing `isinstance()` checks at import time.

| Protocol | Module | Key methods |
|---|---|---|
| `IGateway` | M1 | `async ingest(turn) → AgeBandContext` |
| `IGate` | M1.5 | `check(ctx) → GateResult` |
| `ISignalExtractor` | M2 | `async extract(turn) → SignalSet` |
| `IEvidenceFabric` | M3 | `read(sid)`, `update(sid, signals)`, `decay(sid)` |
| `IAgeBandInference` | M4 | `async estimate(evidence) → AgeBandEstimate` |
| `IPolicyDecision` | M5 | `decide(estimate, confidence) → Decision` |
| `IEnforcement` | M6 | `emit(decision) → safety_posture` |
| `IStepupVerification` | M7 | `async compose(ctx)`, `persist_confirmed(sid, band)` |
| `IAudit` | M8 | `record(sid, action, payload)` |
| `IOrchestration` | M9/M10 | `async run_turn(turn) → safety_posture` |

---

## Custom Validators

### `validate_ageband_estimate(data)`
Ensures the raw LLM output (dict or model) does not contain any `confidence`-like field before constructing an `AgeBandEstimate`. Rejects keys like `confidence`, `conf`, `certainty`, `probability`.

### `validate_planner_action(data)`
Checks that `action_type` is a recognised value from `_VALID_ACTION_TYPES`. Rejects unknown action types (fail closed — unknown actions could be adversarial planner outputs).

---

## Invariants

- `extra="forbid"` on all models — no silent data smuggling
- `AgeBandEstimate` has **no** `confidence` field — enforced structurally + by `validate_ageband_estimate`
- All safety-critical names (`safety_posture`, `PlannerAction`, etc.) match the canonical glossary exactly
- Never modify `contracts/` after Phase A without explicit team approval — it is the frozen seam

---

## Tests

```
tests/unit/contracts/test_models.py           — model instantiation, serialization, invariants
tests/unit/contracts/test_protocols.py        — runtime_checkable, method signatures
tests/unit/contracts/test_llm_client.py       — _parse_json paths, complete_json (httpx mocked); delegate model override
tests/unit/contracts/test_embeddings_client.py — cosine similarity, centroid, offline no-op, mocked HTTP paths
```
