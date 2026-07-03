# Module: `audit_fairness` — Ephemeral Audit Trace (M8)

**Package:** `src/audit_fairness/`  
**Phase:** B (parallel)  
**LLM calls:** None  
**Protocol:** `IAudit`

---

## Purpose

Audit Fairness is a **minimal seam** for recording decision events within a session. In the lean build it acts as an in-memory trace — sufficient for debugging, session review, and fairness monitoring. The interface is designed to be swapped for a production observability backend (OpenTelemetry, a structured log sink, etc.) without changing any other module.

---

## Files

| File | Contents |
|---|---|
| `service.py` | `AuditFairnessService` — implements `IAudit` |
| `trace.py` | In-memory per-session event trace |

---

## What is recorded

The orchestration runner calls `audit.record()` at these points:

| Event | Payload |
|---|---|
| `posture_emitted` | `{"level": "caution"}` |
| `cap_reached` | `{"iteration": N}` |
| `guardrail_rejection` | `{"action": "...", "reason": "..."}` |

Additional events can be added by any module using `audit.record(session_id, event_name, payload)`.

---

## Design

- **Ephemeral:** traces are in-memory; lost on restart
- **No PII in traces:** payloads should never contain turn text, user identifiers beyond `session_id`, or inferred age
- **Swap-out ready:** `IAudit` is a single-method protocol — replacing with an OpenTelemetry exporter requires only a new `record()` implementation

---

## Interface

```python
class IAudit(Protocol):
    def record(
        self, session_id: str, action: str, payload: dict[str, object]
    ) -> None: ...
```

---

## Tests

```
tests/unit/audit_fairness/test_service.py   — record, retrieve trace, isolation
tests/unit/audit_fairness/test_trace.py     — event storage, multi-session
```
