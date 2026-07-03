# Module: `stepup_verification` — Step-Up Confirmation & Persistence (M7)

**Package:** `src/stepup_verification/`  
**Phase:** B (parallel)  
**LLM calls:** Yes — `stepup_composer` delegate composes the message  
**Protocol:** `IStepupVerification`

---

## Purpose

Step-Up Verification handles two distinct concerns:

1. **Composing a step-up message** — when the policy engine returns `action="step_up"`, an LLM delegate writes an appropriate age-confirmation request appropriate for the session context.
2. **Persisting confirmed age bands** — the only place in the system where an age band is ever written to storage. This happens exclusively when a user has explicitly confirmed their age.

> **Load-bearing invariant:** Inferred bands are **never** persisted. Only confirmed bands are stored. The `persist_confirmed()` function raises `PermissionError` if called with `confirmed=False`.

---

## Files

| File | Contents |
|---|---|
| `service.py` | `StepupVerificationService` — wires composer + persistence |
| `persistence.py` | `persist_confirmed()`, `get_confirmed()`, `clear_confirmed()` |
| `tool.py` | `@function_tool` wrapper (`persist_confirmed_tool`) |
| `stepup_composer.yaml` | tinyagent YAML for the `stepup_composer` delegate |
| `prompts/stepup_composer_prompt.md` | LLM system prompt |

---

## Step-Up Message Composition

The `stepup_composer` delegate receives the `AgeBandContext` and returns a `StepUpMessage`:

```python
class StepUpMessage(BaseModel):
    message_text: str
    action: Literal["confirm", "restrict", "handoff"]
```

| Action | Meaning |
|---|---|
| `confirm` | Ask the user to confirm their age to continue |
| `restrict` | Immediately restrict to safe defaults, don't ask |
| `handoff` | Hand off to a human agent or guardian |

The LLM is instructed to be age-appropriate, non-alarming, and brief. It must not reveal that the system inferred the user's age.

---

## Persistence Rules

```python
def persist_confirmed(session_id: str, band: str, confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("Inferred bands must never be persisted.")
    _confirmed[session_id] = band
```

- **Only called** when the user has gone through the step-up flow and explicitly confirmed their age
- **Storage:** module-level in-memory dict in the lean build (swap for a database in production)
- **Guardrail:** the orchestration guardrail (`guardrails.py`) also enforces `confirmed=True` before allowing `persist_confirmed` to be called at all

---

## When step-up fires

The policy table (M5) triggers step-up for:
- `child + high confidence` → `Decision(action="step_up", posture_level="blocked")`
- `teen + high confidence` → `Decision(action="step_up", posture_level="restricted")`

The planner routes to `delegate_stepup` after emitting the posture, then the host delivers the step-up message to the user.

---

## Interface

```python
class IStepupVerification(Protocol):
    async def compose(self, ctx: AgeBandContext) -> StepUpMessage: ...
    def persist_confirmed(self, session_id: str, band: str) -> None: ...
```

---

## Tests

```
tests/unit/stepup_verification/test_persistence.py  — confirmed-only guard, get, clear
tests/unit/stepup_verification/test_service.py      — LLM mocked, compose flow
```
