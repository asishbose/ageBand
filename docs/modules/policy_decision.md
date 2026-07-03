# Module: `policy_decision` — Deterministic Policy Engine (M5)

**Package:** `src/policy_decision/`  
**Phase:** B (parallel)  
**LLM calls:** None — pure deterministic Python  
**Protocol:** `IPolicyDecision`

---

## Purpose

Policy Decision is the **safety arbiter**. It maps `(band, confidence_bucket)` pairs to a `Decision` using a hardcoded lookup table. There is no LLM involvement, no probabilistic reasoning — this is deterministic policy enforcement that fails closed for unknown inputs.

---

## Files

| File | Contents |
|---|---|
| `table.py` | The policy table and `lookup()` function |
| `service.py` | `PolicyDecisionService` — wraps `lookup()` |
| `tool.py` | `@function_tool` wrapper (`policy_decide`) |

---

## Policy Table

Confidence is bucketed before lookup:

| Confidence | Bucket |
|---|---|
| < 0.40 | `low` |
| 0.40 – 0.69 | `medium` |
| ≥ 0.70 | `high` |

Full policy table:

| Band | Confidence | Action | Posture Level | Reason |
|---|---|---|---|---|
| `unknown` | low | `none` | `standard` | `unknown_low` |
| `unknown` | medium | `none` | `standard` | `unknown_medium` |
| `unknown` | high | `none` | `caution` | `unknown_high` |
| `adult` | low | `none` | `standard` | `adult_low` |
| `adult` | medium | `none` | `standard` | `adult_medium` |
| `adult` | high | `none` | `standard` | `adult_high` |
| `teen` | low | `apply` | `caution` | `teen_low` |
| `teen` | medium | `apply` | `restricted` | `teen_medium` |
| `teen` | high | `step_up` | `restricted` | `teen_high` |
| `child` | low | `apply` | `caution` | `child_low` |
| `child` | medium | `apply` | `restricted` | `child_medium` |
| `child` | high | `step_up` | `blocked` | `child_high` |

**Unrecognised band** → `Decision(action="none", posture_level="standard")` (fail closed, no over-restriction)

---

## Decision Actions

| Action | Meaning |
|---|---|
| `none` | No elevated safety action needed; apply posture level as-is |
| `apply` | Apply the posture level immediately |
| `step_up` | Trigger the step-up verification flow before settling (M7) |

---

## Fairness Design

- `unknown` band always maps to `standard` (low/medium confidence) or at most `caution` (high confidence). Insufficient evidence must **never** restrict a user.
- `adult` always maps to `standard` regardless of confidence — confirmed adults get full access.
- Graduated response: `teen/child + low` → caution only (not restricted), allowing for false positives.

---

## Interface

```python
class IPolicyDecision(Protocol):
    def decide(self, estimate: AgeBandEstimate, confidence: float) -> Decision: ...
```

**Input:** `AgeBandEstimate` (for `.band`), `float` confidence (deterministically computed)  
**Output:** `Decision`

---

## Tests

```
tests/unit/policy_decision/test_table.py   — every (band, bucket) combination, fail-closed
```
