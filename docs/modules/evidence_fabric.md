# Module: `evidence_fabric` — Ephemeral Session Evidence Store (M3)

**Package:** `src/evidence_fabric/`  
**Phase:** B (parallel)  
**LLM calls:** None — pure deterministic Python  
**Protocol:** `IEvidenceFabric`

---

## Purpose

Evidence Fabric is the **session memory** for age-relevant cues. It accumulates `Cue` objects across turns, computes a corroboration score, applies weight decay over time, and exposes a read-only `EvidenceSummary` to downstream modules. Evidence is **ephemeral** — it exists only for the life of the session and is never written to persistent storage.

---

## Files

| File | Contents |
|---|---|
| `store.py` | In-memory per-session `EvidenceStore` |
| `corroboration.py` | Deterministic corroboration score formula |
| `decay.py` | Weight decay — reduces cue salience over turns |
| `service.py` | `EvidenceFabricService` — wires store + corroboration + decay |
| `tools.py` | `@function_tool` wrappers (`read_evidence`, `update_evidence`, `decay_evidence`) |

---

## Corroboration Score

```python
corroboration_score = min(sum(cue.weight for cue in cues) / 5.0, 1.0)
```

A normalised [0.0, 1.0] score representing how much age-relevant evidence has accumulated. The divisor `5.0` means 5 cues of weight 1.0 give full corroboration.

This score is the primary input to the deterministic confidence formula in `ageband_inference`.

---

## Evidence Decay

Each call to `decay(session_id)` reduces all cue weights by `DECAY_RATE` (default `0.1`) and discards cues whose weight drops to zero or below. Corroboration is recomputed from surviving cues.

```
# After one decay cycle with rate 0.1:
Cue(weight=0.95) → Cue(weight=0.85)   ✓ survives
Cue(weight=0.05) → weight=−0.05       ✗ discarded
```

Configuration:

| Env var | Default | Description |
|---|---|---|
| `EVIDENCE_DECAY_RATE` | `0.1` | Weight reduction per decay call |

---

## Operations

### `update(session_id, signals: SignalSet) → EvidenceSummary`
Appends all cues from the `SignalSet` to the session's cue list. Recomputes corroboration. Increments `turn_count`.

### `read(session_id) → EvidenceSummary`
Returns the current accumulated evidence. Creates an empty `EvidenceSummary` if the session has no evidence yet.

### `decay(session_id) → None`
Applies weight decay in-place. Intended to be called at turn boundaries to prevent stale evidence from dominating future turns.

---

## Immutability

All returned `EvidenceSummary` objects are new instances — the internal store is not exposed directly. The `apply_decay` function in `decay.py` returns a new `EvidenceSummary` rather than mutating the input.

---

## Ephemerality guarantee

Evidence is stored in a module-level in-memory dict keyed by `session_id`. It is never written to a database, file, or external service. When the process restarts, all evidence is lost. Only explicitly confirmed age bands (via M7 `stepup_verification`) may persist beyond a session.

---

## Interface

```python
class IEvidenceFabric(Protocol):
    def read(self, session_id: str) -> EvidenceSummary: ...
    def update(self, session_id: str, signals: SignalSet) -> EvidenceSummary: ...
    def decay(self, session_id: str) -> None: ...
```

---

## Tests

```
tests/unit/evidence_fabric/test_store.py          — CRUD, isolation
tests/unit/evidence_fabric/test_corroboration.py  — formula, edge cases, saturation
tests/unit/evidence_fabric/test_decay.py          — weight reduction, discard, rebuild
tests/unit/evidence_fabric/test_service.py        — end-to-end update+read+decay
```
