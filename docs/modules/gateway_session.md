# Module: `gateway_session` — Turn Intake & Session Lifecycle (M1)

**Package:** `src/gateway_session/`  
**Phase:** B (parallel)  
**LLM calls:** None — pure deterministic Python  
**Protocol:** `IGateway`

---

## Purpose

Gateway Session is the **entry point** for every user turn. It filters incoming events to user turns only, creates or retrieves per-session state, increments the turn counter, and returns an `AgeBandContext` ready for the planner loop.

---

## Files

| File | Contents |
|---|---|
| `service.py` | `GatewaySessionService` — implements `IGateway` |
| `session_store.py` | In-memory `SessionStore` singleton |
| `filter.py` | Turn event filter (user turns only) |

---

## Session Lifecycle

```
TurnEvent arrives
    ↓
filter: is this a user turn? (not a system/assistant turn)
    ↓ yes
session_store.get(session_id)
    ↓ not found → session_store.create(session_id)  ← band=unknown, confidence=0.0
    ↓ found    → use existing context
ctx.turn_count += 1
return AgeBandContext
```

New sessions start with:
- `current_band = "unknown"`
- `confidence = 0.0`
- `settled = False`
- `turn_count = 0`

---

## Session Store API

```python
class SessionStore:
    def get(self, session_id: str) -> AgeBandContext | None
    def create(self, session_id: str) -> AgeBandContext
    def update(self, session_id: str, ctx: AgeBandContext) -> None
    def clear(self, session_id: str) -> None  # test teardown only
```

The store is a **module-level singleton** (`_session_store`). All services in the same process share one store — no cross-process sharing. For production scale-out, this should be backed by a distributed cache (Redis, etc.).

---

## Ephemerality

Session state is held entirely in memory. When the process restarts, all `unknown`/`inferred` session state is lost. This is intentional — AgeBand holds no persistent age profiles. Only explicitly confirmed ages (handled by M7) may outlive a session.

---

## Interface

```python
class IGateway(Protocol):
    async def ingest(self, turn: TurnEvent) -> AgeBandContext: ...
```

**Input:** `TurnEvent`  
**Output:** `AgeBandContext` (existing or newly created, with incremented `turn_count`)

---

## Tests

```
tests/unit/gateway_session/test_service.py       — ingest, new vs existing session
tests/unit/gateway_session/test_session_store.py — CRUD, isolation
tests/unit/gateway_session/test_filter.py        — user-turn filter logic
```
