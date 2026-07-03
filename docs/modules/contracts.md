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

---

## Data Models

All models use `ConfigDict(extra="forbid")` — unexpected fields raise a `ValidationError` at construction time, preventing accidental data leakage or LLM hallucination of extra fields.

### `Cue`
A single age-relevant signal extracted from one turn.

```python
class Cue(BaseModel):
    type: Literal["vocab", "topic", "disclosure", "style", "reading_level"]
    value: str
    weight: float  # [0.0, 1.0]
```

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
    cited_cues: list[str]        # cue descriptions that influenced the estimate
    evasion_flag: bool           # True if the user appears to be dodging age signals
    contradictions: list[str]    # inconsistencies in the evidence
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
    corroboration_score: float   # [0.0, 1.0] — weighted sum of cue weights
    turn_count: int
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
```

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
tests/unit/contracts/test_models.py      — model instantiation, serialization, invariants
tests/unit/contracts/test_protocols.py   — runtime_checkable, method signatures
```
