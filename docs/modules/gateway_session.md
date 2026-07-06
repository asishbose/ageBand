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
ctx.last_turn_text = turn.turn_text   ← stashed for gate tripwire (transient, in-memory only)
return AgeBandContext
```

New sessions start with:
- `current_band = "unknown"`
- `confidence = 0.0`
- `settled = False`
- `turn_count = 0`
- `last_turn_text = ""`  (populated on every ingest)

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

## Cross-Turn State Write-Back

`GatewaySessionService` now exposes a `update_context` method called by the orchestration runner at the end of every turn:

```python
def update_context(self, session_id: str, ctx: AgeBandContext) -> None:
    """Persist end-of-turn context (confidence, posture, band, settled)."""
```

This is what enables the **confidence-climbs-and-settles arc**: the gate on turn N+1 sees the `confidence`, `posture`, `current_band`, and `settled` values computed on turn N. Without this write-back, every turn would restart from scratch.

The context written here is still ephemeral in-memory only — nothing is persisted to disk.

## Always-On Tripwire (via `last_turn_text`)

`AgeBandContext.last_turn_text` is stashed by `ingest()` on every turn (for both user and non-user turns). This lets the gate's always-on tripwire (M1.5) run a deterministic keyword scan on the current turn without a separate read — even for settled sessions that would otherwise short-circuit. The field is:

- **Transient** — never written to the session store's persistent state, never logged
- **Used only by the gate** (`gate_service._tripwire_fires`) to detect contradictions on settled sessions
- Cleared automatically when a new `AgeBandContext` is created (default `""`)

---

## Ephemerality

Session state is held entirely in memory. When the process restarts, all `unknown`/`inferred` session state is lost. This is intentional — AgeBand holds no persistent age profiles. Only explicitly confirmed ages (handled by M7) may outlive a session.

---

## Interface

```python
class IGateway(Protocol):
    async def ingest(self, turn: TurnEvent) -> AgeBandContext: ...
    def update_context(self, session_id: str, ctx: AgeBandContext) -> None: ...
```

**`ingest` input:** `TurnEvent`  
**`ingest` output:** `AgeBandContext` (existing or newly created, with incremented `turn_count` and `last_turn_text` stashed)  
**`update_context`:** called by the runner at end-of-turn to commit confidence/posture/band/settled back to the store

---

## Tests

```
tests/unit/gateway_session/test_service.py         — ingest, new vs existing session, last_turn_text stash
tests/unit/gateway_session/test_update_context.py  — cross-turn write-back, state persistence
tests/unit/gateway_session/test_session_store.py   — CRUD, isolation
tests/unit/gateway_session/test_filter.py          — user-turn filter logic
```
