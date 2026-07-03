# Module: `enforcement` — Safety Posture Emitter (M6)

**Package:** `src/enforcement/`  
**Phase:** B (parallel)  
**LLM calls:** None — pure deterministic Python  
**Protocol:** `IEnforcement`

---

## Purpose

Enforcement translates a `Decision` from the policy engine into a `safety_posture` object that the host product reads and acts on. AgeBand emits the posture; the **host product is the enforcer** — AgeBand never touches the AI reply path.

---

## Files

| File | Contents |
|---|---|
| `posture_map.py` | Canonical `POSTURE_DEFINITIONS` dict + `build_posture()` |
| `service.py` | `EnforcementService` — implements `IEnforcement` |
| `tool.py` | `@function_tool` wrapper (`emit_posture`) |

---

## Posture Definitions

Each posture level has a canonical flag set. Decision-specific flags are merged on top:

| Level | `mature_content` | `feature_full` | `tone_strict` |
|---|---|---|---|
| `standard` | ✅ allowed | ✅ all features | ❌ relaxed |
| `caution` | ❌ blocked | ✅ all features | ✅ strict |
| `restricted` | ❌ blocked | ❌ limited | ✅ strict |
| `blocked` | ❌ blocked | ❌ limited | ✅ strict |

`blocked` vs `restricted`: both have the same canonical flags, but `blocked` signals that the `step_up` flow is mandatory — the host should not serve further content until the user confirms. The `blocked` level is a stronger signal to the host.

---

## Build Logic

```python
def build_posture(decision: Decision) -> safety_posture:
    base = POSTURE_DEFINITIONS[decision.posture_level]
    merged_flags = {**base.flags, **decision.flags}   # decision flags override canonical
    return safety_posture(level=base.level, flags=merged_flags)
```

Raises `ValueError` for an unrecognised `posture_level` (fail closed).

---

## What the host must honour

The `safety_posture` flags are **advisory signals**. The host product decides how to act on them:

- `mature_content: False` → do not generate or display adult content
- `feature_full: False` → disable non-essential features (e.g. image generation, external browsing)
- `tone_strict: True` → respond in a conservative, child-safe register

AgeBand does not enforce these directly — it only emits the posture and trusts the host.

---

## Interface

```python
class IEnforcement(Protocol):
    def emit(self, decision: Decision) -> safety_posture: ...
```

**Input:** `Decision` from M5  
**Output:** `safety_posture` ready for the host

---

## Tests

```
tests/unit/enforcement/test_posture_map.py   — canonical definitions, flag merging, fail-closed
```
