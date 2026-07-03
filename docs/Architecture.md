# AgeBand — Architecture

> *A passive age-band signal from the conversation that gets more protective the more it suspects a child — and asks before it assumes. On-prem, because this is far too sensitive to run anywhere else.*

---

## Table of Contents

1. [Problem & Design Philosophy](#1-problem--design-philosophy)
2. [Load-Bearing Invariants](#2-load-bearing-invariants)
3. [System Boundaries](#3-system-boundaries)
4. [Module Map](#4-module-map)
5. [Data Model](#5-data-model)
6. [Pipeline Mechanics](#6-pipeline-mechanics)
7. [Confidence Mathematics](#7-confidence-mathematics)
8. [Policy Engine](#8-policy-engine)
9. [Planner-Supervisor Orchestration](#9-planner-supervisor-orchestration)
10. [Guardrail Architecture](#10-guardrail-architecture)
11. [Concurrency & Latency Model](#11-concurrency--latency-model)
12. [Session Lifecycle](#12-session-lifecycle)
13. [Fairness Design](#13-fairness-design)
14. [Security & Adversarial Resistance](#14-security--adversarial-resistance)
15. [On-Premises AMD Deployment](#15-on-premises-amd-deployment)
16. [Testing Architecture](#16-testing-architecture)
17. [Quality Gates](#17-quality-gates)
18. [Architectural Decisions (ADRs)](#18-architectural-decisions-adrs)
19. [Known Limits](#19-known-limits)
20. [Detailed Module Reference](#20-detailed-module-reference)

---

## 1. Problem & Design Philosophy

### The problem

Every AI chat product is under pressure to protect minors. The tool they have — a birthdate typed at signup — is ignored by any child motivated to bypass it. After that single checkpoint, the product treats a 12-year-old and a 40-year-old identically.

The signal being ignored is right there: **how people write and what they talk about.** A trust-and-safety expert reads a transcript and forms a strong impression in seconds. AgeBand automates that judgement — passively, always-on, at scale.

### What AgeBand deliberately does not do

These non-goals are as architecturally important as the goals:

| Non-goal | Why it matters |
|---|---|
| Does not claim a precise age | Text is noisy; "likely teen" is honest, "age=14" is not |
| Does not hard-block on a guess | A low-confidence signal tightens quietly; a strong signal asks |
| Does not build a profile | Evidence is session-scoped and ephemeral; only confirmed ages may persist |
| Does not touch the reply path | AgeBand emits a posture; the host product enforces it |
| Does not send data to third-party APIs | All inference runs on-prem on AMD hardware |

### Design philosophy

**Bands, not ages. Graduated, not binary. Ask, don't assume. Signal, not surveillance.**

The responsible design — bands instead of precise ages, graduated responses, ask-first at the boundary, ephemeral evidence — is not polish around a strong core. It is precisely the right engineering response to a genuinely uncertain signal. The caution is the point.

---

## 2. Load-Bearing Invariants

These invariants are non-negotiable. Every design decision and every line of safety-critical code is traceable to one of them. They are enforced by deterministic code, not by prompts.

| # | Invariant | Enforcer |
|---|---|---|
| I1 | **Model ESTIMATES; deterministic policy DECIDES.** The LLM proposes a band + cues. A deterministic table maps band × confidence → `safety_posture`. No LLM decides safety outcomes. | `policy_decision/table.py`, `guardrails.py` |
| I2 | **Confidence is deterministic.** Computed from countable evidence (cue weights, corroboration, cited cues). Never taken from LLM output. LLM confidence scores are uncalibrated; we don't use them. | `ageband_inference/confidence.py`, `validate_ageband_estimate()` |
| I3 | **Async by default; sync on high-severity.** AgeBand runs beside the reply, not inside it, for normal turns. A strong child signal crossing the step-up threshold blocks that one reply until the new posture is applied. | `orchestration/runner.py` |
| I4 | **Bands, not precise ages.** The system infers broad bands (child/teen/adult/unknown); precise ages are never estimated or stored. | `contracts/models.py` — `band` field |
| I5 | **Ephemeral evidence.** Only an explicitly confirmed age may persist. An inferred band is always session-scoped and never written to durable storage. | `stepup_verification/persistence.py`, `guardrails.py` |
| I6 | **AgeBand emits a posture; the host enforces.** AgeBand has no access to the reply path and never modifies model responses. | System boundary design |
| I7 | **YAML per LLM subagent; Python to wire.** The estimate lives in a tinyagent YAML agent. Confidence, gate logic, policy, posture emission, and persistence all live in deterministic Python. Policy/confidence/gate logic must never appear in a YAML prompt. | Module structure |

---

## 3. System Boundaries

```
┌───────────────────────────────────────────────────────────────────┐
│                  Operator's Environment (on-prem)                 │
│                                                                   │
│  ┌───────────────┐  TurnEvent   ┌─────────────────────────────┐   │
│  │  Host Product │ ──────────►  │    AgeBand Agent Service    │   │
│  │  (AI chat)    │              │    POST /v1/turn            │   │
│  │               │ ◄──────────  │                             │   │
│  │               │ safety_      │    planner-supervisor       │   │
│  │  [honours     │ posture      │    + guardrails             │   │
│  │   posture in  │              │    + deterministic modules  │   │
│  │   its reply   │              └──────────┬──────────────────┘   │
│  │   pipeline]   │                         │ OpenAI-compatible    │
│  └───────────────┘                         ▼ HTTP                 │
│                                  ┌─────────────────────┐          │
│                                  │  vLLM on AMD ROCm   │          │
│                                  │  (model server)     │          │
│                                  └─────────────────────┘          │
└───────────────────────────────────────────────────────────────────┘
```

**What crosses the boundary:**
- **In:** `TurnEvent` — session ID + turn text + turn number
- **Out:** `safety_posture` — level + flags

**What never crosses the boundary:**
- Raw turn text does not leave the operator's environment
- No age inferences are sent to third-party services
- The `safety_posture` returned to the host contains no user-identifying information

---

## 4. Module Map

AgeBand is composed of 10 modules plus a shared contracts package. Each module has a single responsibility, depends only on `contracts/`, and exposes a Python `Protocol` interface.

```
contracts/              ← Frozen seam: Pydantic models + Protocol interfaces
    │
    ├── gateway_session/    M1   — Turn intake, session lifecycle
    │       │
    │       ├── gate/           M1.5 — Deterministic tripwire
    │       │       │
    │       │       └─── signal_extraction/   M2 — LLM: extract age cues
    │       │                   │
    │       │                   └─── evidence_fabric/   M3 — Accumulate, decay
    │       │                               │
    │       │                               └─── ageband_inference/  M4 — LLM: estimate band
    │       │                                           │                    Python: confidence
    │       │                                           └── policy_decision/ M5 — Deterministic table
    │       │                                                   │
    │       │                                                   └── enforcement/ M6 — Emit posture
    │       │                                                           │
    │       │                                      ┌─────────────────── │
    │       │                                      ▼                    │
    │       │                                stepup_verification/ M7 ←──┘ (if step_up)
    │       │
    │       └── audit_fairness/     M8 — Ephemeral decision trace
    │
    └── orchestration/              M9/M10 — Planner loop + guardrails + HTTP API
```

### Module responsibilities at a glance

| Module | Code | LLM? | Primary output |
|---|---|---|---|
| `contracts` | `src/contracts/` | — | Shared models + protocols |
| `gateway_session` | `src/gateway_session/` | No | `AgeBandContext` |
| `gate` | `src/gate/` | No | `GateResult` |
| `signal_extraction` | `src/signal_extraction/` | Yes | `SignalSet` |
| `evidence_fabric` | `src/evidence_fabric/` | No | `EvidenceSummary` |
| `ageband_inference` | `src/ageband_inference/` | Yes (estimate) / No (confidence) | `AgeBandEstimate` + `float` |
| `policy_decision` | `src/policy_decision/` | No | `Decision` |
| `enforcement` | `src/enforcement/` | No | `safety_posture` |
| `stepup_verification` | `src/stepup_verification/` | Yes (compose) / No (persist) | `StepUpMessage` + confirmed write |
| `audit_fairness` | `src/audit_fairness/` | No | ephemeral trace record |
| `orchestration` | `src/orchestration/` | Yes (planner) | wires all the above |
| `ui` | `src/ui/` | No | React SPA |

---

## 5. Data Model

All types are defined in `src/contracts/models.py` with `ConfigDict(extra="forbid")` — unexpected fields raise `ValidationError` immediately.

### Core type flow

```
TurnEvent
    │
    ▼
AgeBandContext           ← lives per session, updated each turn
    │
    ▼
SignalSet                ← extracted per turn
    │
    ▼
EvidenceSummary          ← accumulated across turns (ephemeral)
    │
    ▼
AgeBandEstimate          ← LLM proposes (NO confidence field)
    + float confidence   ← Python computes (deterministic)
    │
    ▼
Decision                 ← policy table output
    │
    ▼
safety_posture           ← emitted to host
```

### Key model constraints

**`AgeBandEstimate` has no `confidence` field.** This is enforced three ways:
1. The field simply does not exist in the Pydantic model
2. `extra="forbid"` raises `ValidationError` if the LLM tries to add it
3. `validate_ageband_estimate()` explicitly scans for confidence-like keys before construction

**`safety_posture`** uses a lowercase class name — canonical per the project glossary, enforced by `noqa: N801`.

**`PlannerAction.action_type`** is a `Literal` — unknown action types are rejected at Pydantic validation time, before any guardrail check.

### Type reference

| Type | Source | Used by |
|---|---|---|
| `Cue` | `contracts/models.py` | signal_extraction → evidence_fabric |
| `TurnEvent` | `contracts/models.py` | gateway_session (entry point) |
| `SignalSet` | `contracts/models.py` | signal_extraction → evidence_fabric |
| `AgeBandEstimate` | `contracts/models.py` | ageband_inference → policy_decision |
| `GateResult` | `contracts/models.py` | gate → orchestration |
| `EvidenceSummary` | `contracts/models.py` | evidence_fabric → ageband_inference |
| `Decision` | `contracts/models.py` | policy_decision → enforcement |
| `safety_posture` | `contracts/models.py` | enforcement → host product |
| `PlannerAction` | `contracts/models.py` | orchestration (planner loop) |
| `StepUpMessage` | `contracts/models.py` | stepup_verification → host product |
| `AgeBandContext` | `contracts/models.py` | gateway_session → orchestration (session state) |

---

## 6. Pipeline Mechanics

### Normal turn (analyze path)

```
1.  gateway_session.ingest(TurnEvent)
       → creates/retrieves session; increments turn_count
       → returns AgeBandContext

2.  gate.check(AgeBandContext)
       → GateResult: "analyze" or "reuse_posture"

   ── if "reuse_posture" ──────────────────────────────────────────────
   │  return ctx.posture (or SAFE_DEFAULT_POSTURE)
   ────────────────────────────────────────────────────────────────────

   ── if "analyze" ────────────────────────────────────────────────────

3.  signal_extractor (LLM delegate)
       input:  turn_text
       output: SignalSet { cues: [Cue(type, value, weight), ...] }

4.  evidence_fabric.update(session_id, SignalSet)
       → appends cues; recomputes corroboration_score; increments turn_count
       → returns EvidenceSummary

5.  ageband_estimator (LLM delegate)
       input:  EvidenceSummary
       output: AgeBandEstimate { band, cited_cues, evasion_flag, contradictions }
               (NO confidence field — validated before use)

6.  compute_confidence(EvidenceSummary, AgeBandEstimate) [deterministic Python]
       → float in [0.0, 1.0]

7.  policy_decision.decide(AgeBandEstimate, confidence) [deterministic table]
       → Decision { action, posture_level, flags, reason }

8.  enforcement.emit(Decision) [deterministic]
       → safety_posture { level, flags }

   ── if Decision.action == "step_up" ─────────────────────────────────
   │  9a. stepup_composer (LLM delegate)
   │         → StepUpMessage { message_text, action: confirm|restrict|handoff }
   │  9b. host delivers step-up message to user
   │  9c. if user confirms: persist_confirmed(session_id, band, confirmed=True)
   ────────────────────────────────────────────────────────────────────

9.  audit_fairness.record("posture_emitted", {"level": ...})

10. return safety_posture to host
```

### Short-circuit path (gate → reuse_posture)

For settled sessions (high confidence, `settled=True`) or when `turn_count < MIN_TURNS` and a posture already exists:

```
gate.check() → "reuse_posture"
    → return existing ctx.posture
    (no LLM calls, no evidence update)
```

This is what makes "always-on" affordable: most turns of a settled adult session cost a single in-memory read.

### First-turn behavior

On turn 1 of a brand new session, `posture=None`. The gate **always** returns `analyze` — the insufficient-data short-circuit only applies when there is already a posture to reuse. Evidence collection begins immediately on turn 1.

---

## 7. Confidence Mathematics

Confidence is the single number that bridges LLM estimation and deterministic policy. It is **never taken from the LLM**.

### Formula

```
base      = corroboration_score × CORROBORATION_WEIGHT      (default weight: 0.60)

cue_bonus = min(len(cited_cues), MAX_CITED_CUES_BONUS)
            / MAX_CITED_CUES_BONUS × CITED_CUES_WEIGHT      (default weight: 0.40)

raw = base + cue_bonus

penalties:
  if evasion_flag:        raw -= EVASION_PENALTY            (default: 0.15)
  for each contradiction: raw -= CONTRADICTION_PENALTY      (default: 0.10, max 3 counted)

confidence = max(0.0, min(raw, 1.0))

special case: corroboration=0.0 AND cited_cues=[] → confidence = 0.0
```

### Corroboration score

```
corroboration_score = min(sum(cue.weight for cue in cues) / 5.0, 1.0)
```

Five cues of weight 1.0 give full corroboration. The score normalises the volume and strength of accumulated evidence.

### Worked examples

| Scenario | Cues | Corroboration | Base | Cue bonus | Penalties | **Confidence** | Bucket |
|---|---|---|---|---|---|---|---|
| Empty first turn | 0 | 0.0 | 0.0 | 0.0 | 0 | **0.0** | low |
| Teen, 2 weak cues | 2 × 0.5 | 0.2 | 0.12 | 0.16 | 0 | **0.28** | low |
| Teen, 3 medium cues | 3 × 0.7 | 0.42 | 0.25 | 0.24 | 0 | **0.49** | medium |
| Child disclosure | 5 × 0.95 | 0.95 | 0.57 | 0.40 | 0 | **0.97** | high |
| Adversarial evasion | 2 × 0.95 | 0.38 | 0.23 | 0.16 | −0.15 (evasion) | **0.24** | low |
| Contradicted claim | 3 × 0.8, 2 contradictions | 0.48 | 0.29 | 0.24 | −0.20 | **0.33** | low |

### Bucket thresholds

| Range | Bucket |
|---|---|
| 0.00 – 0.39 | `low` |
| 0.40 – 0.69 | `medium` |
| 0.70 – 1.00 | `high` |

Thresholds are illustrative; tune empirically per product and jurisdiction.

---

## 8. Policy Engine

The policy engine (`src/policy_decision/table.py`) is a deterministic lookup table. No LLM, no probabilistic reasoning.

### Full policy table

| Band | Confidence | Action | Posture Level |
|---|---|---|---|
| `unknown` | low | `none` | `standard` |
| `unknown` | medium | `none` | `standard` |
| `unknown` | high | `none` | `caution` |
| `adult` | low | `none` | `standard` |
| `adult` | medium | `none` | `standard` |
| `adult` | high | `none` | `standard` |
| `teen` | low | `apply` | `caution` |
| `teen` | medium | `apply` | `restricted` |
| `teen` | high | `step_up` | `restricted` |
| `child` | low | `apply` | `caution` |
| `child` | medium | `apply` | `restricted` |
| `child` | high | `step_up` | `blocked` |

**Unrecognised band** → `Decision(action="none", posture_level="standard")` — fail open at the policy level is intentional here. An unknown band with no evidence must not restrict users.

### Posture flags

| Level | `mature_content` | `feature_full` | `tone_strict` |
|---|---|---|---|
| `standard` | ✅ allowed | ✅ all features | ❌ relaxed |
| `caution` | ❌ blocked | ✅ all features | ✅ strict |
| `restricted` | ❌ blocked | ❌ limited | ✅ strict |
| `blocked` | ❌ blocked | ❌ limited | ✅ strict |

Decision-level flags are merged on top of the canonical definition, allowing per-decision flag overrides.

### Inverse use case

The same pipeline — only the policy table — supports a **children's product detecting adults**: a likely-adult signal in a child-safe space triggers protection instead of a likely-minor signal in an adult space.

---

## 9. Planner-Supervisor Orchestration

### Why a planner, not a fixed pipeline

A hardcoded sequence cannot adapt to:
- Sessions where the gate short-circuits (reuse path)
- Turns where step-up is needed mid-pipeline
- Future routing variants (e.g. "skip extraction if evidence is already rich enough")

The planner-supervisor uses a **plan → act → observe → re-plan** loop to choose the next action each turn. It chooses the **route**, never the safety **outcome**.

### Planner constraints (enforced, not trusted)

The planner:
- **Can:** request any valid `PlannerAction`
- **Cannot:** emit a `safety_posture` directly
- **Cannot:** skip or reorder the safety guards
- **Cannot:** take confidence from the LLM
- **Cannot:** persist an inferred band
- **Cannot:** loop more than `MAX_ITERATIONS` (default 8) times

These constraints are enforced by the guardrails layer — the planner cannot bypass them even if it tries.

### Routing sequence

The deterministic routing table (used in lean/test build; replaced by LLM planner in production):

```python
_ROUTE_SEQUENCE = [
    ("gate_checked",        "gate_check"),
    ("extract_done",        "_gate_or_finish"),  # checks gate result, may short-circuit
    ("evidence_read",       "update_evidence"),
    ("estimate_done",       "delegate_estimate"),
    ("confidence_computed", "compute_confidence"),
    ("policy_decided",      "policy_decide"),
    ("posture_emitted",     "emit_posture"),
    ("step_up_requested",   "_stepup_if_needed"),
]
```

### tinyagent integration

In the full tinyagent build (`planner_supervisor.yaml`):

- The planner-supervisor is an LLM agent configured with `tool_choice: required`
- It registers all deterministic tools as `@function_tool`s
- It registers three delegate subagents: `signal_extractor`, `ageband_estimator`, `stepup_composer`
- `max_iterations: 8` is set at the tinyagent level in addition to the Python guardrail cap

The lean build replaces the LLM planner with a deterministic `_route()` function in `runner.py`. All guardrails, tools, and module logic are identical in both builds.

---

## 10. Guardrail Architecture

`src/orchestration/guardrails.py` is the **safety net**. tinyagent will execute whatever the planner requests — the guardrails intercept and reject invalid requests before any action runs.

### PlannerState

A per-turn dataclass tracking which actions have completed:

```python
@dataclass
class PlannerState:
    gate_checked:        bool = False
    extract_done:        bool = False
    evidence_read:       bool = False
    estimate_done:       bool = False
    confidence_computed: bool = False
    policy_decided:      bool = False
    posture_emitted:     bool = False
    step_up_requested:   bool = False
    iteration:           int  = 0
```

Reset at the start of every turn. No state is shared between turns.

### Precondition enforcement

`enforce_preconditions(action_type, params, state)` is called before every action:

```
planner requests action
       ↓
enforce_preconditions()   ← deterministic; raises GuardrailViolationError if invalid
       │
       ├─ violation → SAFE_DEFAULT_POSTURE (caution) returned immediately
       │
       └─ passes
              ↓
       execute action
              │
              ├─ exception → SAFE_DEFAULT_POSTURE returned
              └─ success
                     ↓
              record_action_completed()   ← sets flag in PlannerState
```

### The 7 invariants checked

| Action | Precondition | Error message |
|---|---|---|
| `delegate_extract` | `gate_checked == True` | "gate_check must run first every turn" |
| `update_evidence` | `extract_done == True` | "Signals must be extracted before evidence is updated" |
| `delegate_estimate` | `evidence_read == True` | "Evidence must be read before estimation" |
| `compute_confidence` | `estimate_done == True` | "An AgeBandEstimate must exist before confidence is computed" |
| `policy_decide` | `confidence_computed == True` | "Confidence must be computed deterministically before policy runs" |
| `emit_posture` | `policy_decided == True` | "Policy must be decided before a posture is emitted" |
| `persist_confirmed` | `params["confirmed"] == True` | "Inferred bands must never be persisted" |

### Iteration cap — fail closed

The outer loop in `run_turn()` tracks iteration count. If `MAX_ITERATIONS` (default 8) is reached without emitting a posture, `SAFE_DEFAULT_POSTURE` is returned immediately:

```python
SAFE_DEFAULT_POSTURE = safety_posture(
    level="caution",
    flags={"mature_content": False, "feature_full": True, "tone_strict": True}
)
```

"Caution" is the safe default: users are not locked out, but mature content and strict tone are applied. This is protective without being punishing for an ambiguous user.

### Why iteration counting is NOT in `enforce_preconditions`

A full clean pipeline executes exactly 8 tools (gate → extract → update → read → estimate → confidence → policy → posture). If the cap were checked per `enforce_preconditions` call, a valid pipeline would trip it on the last step. The cap is checked in the outer `for` loop in `run_turn()` — counting planner iterations, not tool calls.

---

## 11. Concurrency & Latency Model

### Async by default

`OrchestrationService.run_turn()` is `async`. All I/O-bound steps (LLM delegate calls) are awaited; the deterministic steps are pure Python and run synchronously within the async context.

The host product should call `POST /v1/turn` **after** the user sends a message, in parallel with generating the reply. For normal turns (adult, settled session), the gate short-circuits and the call returns in milliseconds.

### Sync on high-severity

When the policy engine returns `action="step_up"` (child/teen + high confidence), the host product **must block** its reply until the step-up message is delivered to the user and the session state is updated. This is the one-turn synchronisation point that prevents exposing a child on the exact turn they reveal themselves.

This is architecturally enforced by the returned `posture.level == "blocked"` — the host integration guide specifies that `blocked` must not be served past.

### Latency budget (rough)

| Path | Latency |
|---|---|
| Gate short-circuit (settled session) | ~1 ms (in-memory read) |
| Gate → full analyze (no LLM calls, test build) | ~5 ms |
| Full pipeline (2 LLM calls: extract + estimate) | 200 ms – 2 s (model-dependent) |
| Step-up path (3 LLM calls: extract + estimate + compose) | 300 ms – 3 s |

In production, the host fires `POST /v1/turn` concurrently with its own LLM call, so the AgeBand latency adds zero perceived latency for standard turns.

---

## 12. Session Lifecycle

```
New session created
   band = "unknown" | confidence = 0.0 | settled = False | posture = None

Turn N arrives
   turn_count += 1
   gate: analyze or reuse?
   
   if analyze:
       signals extracted → evidence updated
       band estimated → confidence computed
       policy applied → posture emitted
       ctx updated: band, confidence, posture
   
   if confidence >= GATE_CONFIDENCE_THRESHOLD (0.85):
       settled = True    ← future turns will short-circuit at the gate

Step-up triggered (child/teen + high confidence):
   posture = "blocked" or "restricted"
   step-up message delivered to user
   
   if user confirms age:
       persist_confirmed(session_id, band, confirmed=True)
       settled = True
   
   if user declines / times out:
       session stays restricted
       (inferred band is NOT persisted)

Session ends / process restarts:
   all inferred state is lost
   confirmed bands: lost in lean build (module-level dict)
                    survives in production (backed by Redis / DB)
```

### Ephemerality guarantee

Evidence and inferred bands are **never** written to durable storage. The `_confirmed` dict in `stepup_verification/persistence.py` is module-level — it acts as a per-process in-memory store. In a production deployment with multiple replicas, this should be replaced by a distributed store (Redis, etc.), keyed by session ID.

---

## 13. Fairness Design

AgeBand is explicitly designed to avoid harming users who are misclassified.

### The fairness problem

Lexical signals (vocabulary, reading level) are the weakest age indicators, but they are also the signals most correlated with demographics: non-native speakers, neurodivergent users, and people who write simply look like children on exactly those signals.

### Mitigations

1. **Low lexical signal weight.** Topic and disclosure cues outweigh vocabulary/reading-level cues. One simple sentence does not shift the band.

2. **Ask, don't restrict.** For ambiguous/unknown sessions, the policy emits `standard` (low/medium confidence) or `caution` (high confidence on unknown band). Users are never hard-blocked on a low-confidence guess.

3. **Cold-start as `standard`.** New sessions start with `band=unknown, confidence=0.0`. The first turn never restricts a user more than caution.

4. **Graduated posture.** Even `caution` (teen/child low confidence) preserves all features — only mature content is blocked and tone is made strict. Full feature restriction requires medium+ confidence.

5. **Fairness money-shot scenario:** An adult who writes simply gets `unknown + low confidence → standard posture`. The system asks rather than restricts. See `tests/e2e/test_ambiguous_adult.py`.

6. **False positive label loop.** Every step-up that resolves to "actually an adult" is a labeled false positive. In a production deployment, this feeds threshold tuning.

---

## 14. Security & Adversarial Resistance

### Threat: child claiming to be an adult

The system's primary adversarial scenario. A motivated child avoids childlike language, claims adult status, and dodges age-revealing topics.

**Mitigations:**

1. **Evasion detection.** The `ageband_estimator` LLM is prompted to detect evasion patterns: abrupt style shifts, over-insistence on adult status, dodged topics. When detected, `evasion_flag=True` is set in the `AgeBandEstimate`.

2. **Evasion penalty.** `evasion_flag=True` subtracts `EVASION_PENALTY` (default 0.15) from the deterministic confidence score. Evasion keeps confidence low — the session cannot settle as "adult" under active evasion.

3. **Contradiction penalty.** Inconsistencies in the evidence subtract `CONTRADICTION_PENALTY` (default 0.10) each, up to 3. A user who alternates between adult and childlike signals loses confidence on both.

4. **Step-up as backstop.** Inference alone is **not** a security boundary. When signals are contradictory, confidence stays low → policy routes to step-up → explicit verification is required. The system's assurance rests on the step-up path, not on the accuracy of passive inference.

5. **Adversarial test:** `tests/e2e/test_adversarial.py` asserts that an adversarial child (evasion_flag=True, contradictions present) does not receive a `standard` posture.

### Threat: adversarial planner inputs

The LLM planner could try to:
- Emit a posture directly (bypassing policy)
- Skip the gate check
- Call `persist_confirmed` with `confirmed=False`
- Loop indefinitely

All blocked by `guardrails.py` before any action executes.

### Threat: LLM confidence hallucination

The LLM could output a confidence value despite the prompt prohibition.

**Mitigations:**
- `AgeBandEstimate` has no `confidence` field — Pydantic raises `ValidationError` on unexpected fields
- `validate_ageband_estimate()` explicitly scans for confidence-like keys (`confidence`, `conf`, `certainty`, `probability`) and raises if found
- Confidence is always computed by `compute_confidence()` in Python

### Threat: policy table modification

If an attacker could modify the policy table at runtime, safety behavior could be inverted.

**Mitigation:** `POLICY_TABLE` is a module-level constant in `table.py`. It is not read from configuration or from any external source. Changes require a code deployment.

---

## 15. On-Premises AMD Deployment

### Why on-prem is non-negotiable

Inferring whether a user is a minor from their private messages is among the most sensitive attributes that can be computed from the most sensitive data a product holds. Sending this inference to a third-party API is legally and ethically untenable in most jurisdictions. **The on-prem AMD requirement is the entire deployability story, not a compute story.**

### AMD ROCm / vLLM serving

AgeBand is designed to run against a vLLM instance on AMD ROCm GPUs:

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 --port 8000 \
  --device rocm
```

The agent service uses the OpenAI-compatible endpoint via `LOCAL_API_BASE` and `LOCAL_MODEL` environment variables. No cloud APIs are called.

### Startup verification

`src/orchestration/amd_check.py` verifies at startup that:
1. The vLLM endpoint is reachable (`GET /v1/models`)
2. The configured model is loaded and available

```python
verify_amd_endpoint(base_url="http://vllm-service:8000/v1", model="Qwen/Qwen2.5-7B-Instruct")
```

Set `SKIP_AMD_CHECK=true` for local development without a GPU.

### Model choice

A single open-weight model (Qwen/Llama-class) is used for all three LLM calls (signal_extraction, ageband_estimation, stepup_composition). The two-model split (small extractor, large estimator) is an optimization — the lean build starts with one model and splits only when profiling justifies the added serving complexity.

---

## 16. Testing Architecture

Tests are organised in three tiers, each with a distinct scope:

### Unit tests (`tests/unit/`)

- One test file per module
- All LLM calls mocked (no real model required)
- Deterministic modules tested with full input/output coverage
- Marker: `@pytest.mark.unit` (default — no marker needed)

Key test files:
```
tests/unit/contracts/         — model invariants, protocol checks
tests/unit/gate/              — decision logic, env-var overrides
tests/unit/evidence_fabric/   — formula correctness, decay, isolation
tests/unit/ageband_inference/ — confidence formula, penalty cases
tests/unit/policy_decision/   — all 12 (band, bucket) combinations
tests/unit/orchestration/     — all 7 guardrail invariants, AMD check
```

### Integration tests (`tests/integration/`)

- Module interactions tested (orchestration → all modules)
- LLM delegates still mocked
- Focus on pipeline flow, gate short-circuit, guardrail enforcement

Key scenarios:
```
test_happy_path.py          — adult, teen, unknown band
test_gate_short_circuit.py  — settled session skips pipeline
test_stepup_flow.py         — child+high confidence → restricted/blocked
test_guardrail_integration.py — out-of-order action rejection
```

### E2E scenario tests (`tests/e2e/`)

- Four canonical scenarios from the product spec
- All deterministic paths run for real; LLM delegates mocked
- Assert on final posture level with business-logic reasoning

| Scenario | File | Asserts |
|---|---|---|
| Clear adult | `test_clear_adult.py` | `posture.level == "standard"` always |
| Young teen | `test_young_teen.py` | `posture.level in {"caution", "restricted"}` |
| Ambiguous adult (fairness) | `test_ambiguous_adult.py` | `posture.level == "standard"` — no over-restriction |
| Adversarial child | `test_adversarial.py` | `posture.level != "standard"`, confidence < 0.7 |

### Test count

**292 tests, 0 failures.**

---

## 17. Quality Gates

All gates are enforced in CI and must pass before merge:

| Gate | Tool | Target |
|---|---|---|
| Unit + integration + e2e tests | `pytest` | 100% pass |
| Coverage | `pytest-cov` | ≥ 85% on changed code |
| Type checking | `mypy --strict` | Zero errors |
| Linting | `ruff` | Zero errors |
| Formatting | `black` | No diffs |
| Cyclomatic complexity | `radon cc` | Grade A (CC ≤ 5); grade B (CC ≤ 10) with justification |
| Maintainability index | `radon mi` | MI ≥ 75 |

Run all gates:

```bash
pytest tests/ --cov=src --cov-fail-under=85
mypy src/ --strict --ignore-missing-imports
ruff check src/
black --check src/
radon cc src/ -n B    # show anything worse than B
radon mi src/ -n B    # show anything with MI < some threshold
```

---

## 18. Architectural Decisions (ADRs)

### ADR-001 — Model estimates; deterministic policy decides

**Decision:** The LLM proposes a band + cues. A hardcoded Python lookup table maps band × confidence → `safety_posture`. The LLM never decides a safety outcome.

**Rationale:** LLMs are flexible but unreliable for hard rules. Deterministic code fails predictably, is auditable, and can be changed without retraining. Safety-critical decisions must be explainable and testable.

**Consequence:** The policy table is code, not configuration. Changes require a deployment.

---

### ADR-002 — Confidence is deterministic, never from LLM

**Decision:** Confidence is computed from countable facts (cue weights, corroboration score, cited cue count, evasion/contradiction penalties). The LLM may not output a confidence value.

**Rationale:** LLM self-reported confidence scores are famously uncalibrated. A model saying "0.95 confidence it's a child" is meaningless for a safety-critical threshold. Grounded, countable evidence is the only honest basis for a confidence number that drives real decisions.

**Consequence:** The confidence formula is transparent and tunable. The `AgeBandEstimate` model structurally prevents the LLM from providing confidence.

---

### ADR-003 — Ephemeral evidence; confirmed-only persistence

**Decision:** All inferred evidence is session-scoped and lost when the session ends or the process restarts. Only an age the user has explicitly confirmed may be written to durable storage.

**Rationale:** A silently stored "this account is probably a child" flag is itself a sensitive profile — the very thing AgeBand promises not to build. Ephemerality is the privacy guarantee.

**Consequence:** Restarted sessions start fresh. The step-up flow is the only path to a persistent record. Production deployments must back `persist_confirmed` with a durable store (Redis/DB).

---

### ADR-004 — Planner-supervisor with deterministic guardrails

**Decision:** Orchestration uses a planner-supervisor loop (LLM chooses the route) wrapped by deterministic Python precondition checks that fail closed.

**Rationale:** A fixed pipeline cannot adapt to the varied routing cases (reuse, step-up, etc.). But an unchecked LLM planner is a safety risk. The combination — agentic routing, deterministic safety — gives flexibility where it helps and reliability where it counts.

**Consequence:** The guardrails layer must be tested exhaustively. The planner cannot be trusted; it must be constrained.

---

### ADR-005 — tinyagent over custom LangGraph/LangChain

**Decision:** The agent runtime is Nokia's tinyagent (Agents SDK), not a custom LangGraph/LangChain graph.

**Rationale:** tinyagent provides YAML-driven multi-agent configuration, delegate/supervisor wiring, session persistence, and an OpenAI-compatible HTTP endpoint out of the box. The deterministic safety plumbing (gate, confidence, policy, guardrails) is custom Python regardless of framework choice.

**Consequence:** The YAML configuration is tinyagent-specific. The Python modules are framework-agnostic and could be wrapped by any other runtime.

---

### ADR-006 — One open-weight model for all LLM calls

**Decision:** The lean build uses one open-weight LLM (Qwen/Llama-class) for signal extraction, band estimation, and step-up composition.

**Rationale:** Two resident models (small extractor + large estimator) add serving complexity that is only justified by profiling data. Start lean; split only when the numbers say so.

**Consequence:** Signal extraction runs at the same inference cost as band estimation. The step-up path requires three LLM calls total (extract + estimate + compose).

---

### ADR-007 — React UI, not a server-rendered page

**Decision:** The demo/monitoring UI is a React SPA served by nginx, with an API proxy to the agent service.

**Rationale:** The UI needs live updating of session state (band, confidence, evidence, posture, planner trace) as turns arrive. A React component tree with local state is the natural fit. It also decouples UI deployment from agent deployment.

**Consequence:** Two containers to build and deploy (agent + UI). nginx handles both SPA routing and API proxying.

---

## 19. Known Limits

These are stated honestly — naming them is architectural honesty, not a weakness.

**1. Passive inference is not a security boundary.**
A determined, motivated child will lie. AgeBand treats evasion as a weak signal and routes to step-up rather than claiming to catch motivated liars. The assurance backstop is the step-up/verification path, not the inference accuracy.

**2. New sessions start fresh.**
Keying evidence to an ephemeral `session_id` is trivially defeated by starting a new session. Cross-session linking would rebuild the profile we promised not to keep. The distinction — confirmed facts can persist; inferred facts cannot — is the right side of the privacy line.

**3. Lexical signals are the weakest and most demographically biased.**
A non-native speaker and a native child can look identical on vocabulary and reading-level signals. Lexical cues are explicitly down-weighted below disclosure and topic signals, and the ask-don't-restrict bias absorbs the rest.

**4. Confidence thresholds are illustrative, not fixed.**
The numbers (low < 0.40, high ≥ 0.70, reuse threshold 0.85) are starting points. They are tuned empirically per product, user base, and jurisdiction.

**5. The session-scoped in-memory store does not survive restarts or scale horizontally.**
The lean build uses a module-level `dict`. A production deployment with multiple replicas requires a shared session store (Redis, etc.).

**6. One-turn lag on first strong signal.**
Because AgeBand runs beside the reply (async), the reply on the turn a child first reveals themselves may already be in flight under the old posture. The sync step-up path handles the high-severity case; for gradual tightening the one-turn lag is accepted.

---

## 20. Detailed Module Reference

Each module has its own README with complete API, configuration, formulas, and test coverage:

| Module | Detail doc |
|---|---|
| Shared contracts (models, protocols, validators) | [docs/modules/contracts.md](modules/contracts.md) |
| Gate — deterministic tripwire | [docs/modules/gate.md](modules/gate.md) |
| Signal extraction — LLM cue extractor | [docs/modules/signal_extraction.md](modules/signal_extraction.md) |
| Evidence Fabric — ephemeral evidence store | [docs/modules/evidence_fabric.md](modules/evidence_fabric.md) |
| AgeBand Inference — estimate + confidence | [docs/modules/ageband_inference.md](modules/ageband_inference.md) |
| Policy Decision — deterministic table | [docs/modules/policy_decision.md](modules/policy_decision.md) |
| Enforcement — posture emitter | [docs/modules/enforcement.md](modules/enforcement.md) |
| Step-Up Verification — confirm + persist | [docs/modules/stepup_verification.md](modules/stepup_verification.md) |
| Gateway Session — turn intake + lifecycle | [docs/modules/gateway_session.md](modules/gateway_session.md) |
| Audit Fairness — ephemeral trace | [docs/modules/audit_fairness.md](modules/audit_fairness.md) |
| Orchestration — planner + guardrails + API | [docs/modules/orchestration.md](modules/orchestration.md) |

Integration data flow, cross-module contracts, deployment topology, and environment variables:

→ [docs/integration_architecture.md](integration_architecture.md)
