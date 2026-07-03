# Module: `gate` — Deterministic Tripwire (M1.5)

**Package:** `src/gate/`  
**Phase:** B (parallel)  
**LLM calls:** None — pure deterministic Python  
**Protocol:** `IGate`

---

## Purpose

The gate is a cheap, no-LLM decision: **should this turn trigger a full inference pipeline, or can the existing posture be reused?** It prevents unnecessary LLM calls for settled sessions and avoids thrashing on sessions with insufficient evidence.

---

## Files

| File | Contents |
|---|---|
| `gate_service.py` | `GateService` — implements `IGate` |
| `config.py` | Env-configurable thresholds |
| `tool.py` | `@function_tool` wrapper for the planner |

---

## Decision Logic

```
GateService.check(ctx: AgeBandContext) → GateResult
```

Priority order (first matching condition wins):

| Condition | Result | Reason |
|---|---|---|
| `ctx.settled == True` | `reuse_posture` | `settled_session` |
| `ctx.confidence >= CONFIDENCE_REUSE_THRESHOLD` | `reuse_posture` | `high_confidence` |
| `ctx.turn_count < MIN_TURNS_FOR_ANALYSIS` **AND** `ctx.posture is not None` | `reuse_posture` | `insufficient_data` |
| (all else) | `analyze` | `proceed` |

> **Key design note:** The `insufficient_data` condition only fires when an existing posture is already present. On a brand-new session (turn 1, no posture), the gate **always** returns `analyze` — evidence collection must begin immediately, even with no history.

---

## Configuration

| Env var | Default | Description |
|---|---|---|
| `GATE_CONFIDENCE_THRESHOLD` | `0.85` | Confidence level above which posture is reused |
| `GATE_MIN_TURNS` | `2` | Minimum turns before `insufficient_data` short-circuit applies |

All values are read at module import time; reload the module or restart the service to pick up changes.

---

## Invariants

- No LLM calls, no I/O — pure CPU logic
- Satisfies `IGate` protocol verified with `isinstance()` at import time (fail closed if not)
- Never modifies session state — read-only access to `AgeBandContext`

---

## Interface

```python
class IGate(Protocol):
    def check(self, ctx: AgeBandContext) -> GateResult: ...
```

**Input:** `AgeBandContext` (current session state)  
**Output:** `GateResult(action="analyze"|"reuse_posture", reason=str)`

---

## Tests

```
tests/unit/gate/test_gate_service.py
```

Covers: settled session, high confidence, first-turn with/without posture, env-var override, boundary values.
