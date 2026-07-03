# AgeBand — Integration Architecture

This document describes how AgeBand's modules interact at runtime: the data flow through the system, the planner-supervisor orchestration model, the safety invariant enforcement chain, and the integration contracts a host product must honour.

---

## System Overview

AgeBand is a **passive, per-session age-band inference sidecar**. It sits alongside an AI chat product, observes user turns, and emits a `safety_posture` that the host product can apply to its reply generation. AgeBand never reads, modifies, or generates chat replies.

```
Host Product
  ├── [user sends a turn]
  │     │
  │     ▼
  │   AgeBand Agent (POST /v1/turn)
  │     │
  │     ▼
  │   safety_posture { level, flags }
  │     │
  └── [host applies posture to its reply pipeline]
```

---

## Module Map

```
┌─────────────────────────────────────────────────────────────────┐
│                       contracts/                                │
│  (Pydantic models + Protocols — frozen seam, shared by all)    │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼ TurnEvent
┌────────────────────┐
│  gateway_session   │  M1  — Session lifecycle, turn filtering
│   (IGateway)       │        → AgeBandContext
└────────┬───────────┘
         │ AgeBandContext
         ▼
┌────────────────────┐
│      gate          │  M1.5 — Deterministic tripwire
│   (IGate)          │         → GateResult: analyze | reuse_posture
└────────┬───────────┘
         │ analyze path only
         ▼
┌────────────────────┐
│ signal_extraction  │  M2  — LLM: extract age cues
│ (ISignalExtractor) │        → SignalSet
└────────┬───────────┘
         │ SignalSet
         ▼
┌────────────────────┐
│  evidence_fabric   │  M3  — Accumulate, corroborate, decay
│ (IEvidenceFabric)  │        → EvidenceSummary
└────────┬───────────┘
         │ EvidenceSummary
         ▼
┌────────────────────┐
│ ageband_inference  │  M4  — LLM: propose band + cues + evasion
│(IAgeBandInference) │        Python: compute_confidence(evidence, estimate)
│                    │        → AgeBandEstimate + float confidence
└────────┬───────────┘
         │ (estimate, confidence)
         ▼
┌────────────────────┐
│  policy_decision   │  M5  — Deterministic table: band×bucket → Decision
│ (IPolicyDecision)  │        → Decision { action, posture_level, flags }
└────────┬───────────┘
         │ Decision
         ▼
┌────────────────────┐     Decision.action == "step_up"
│   enforcement      │  M6  ─────────────────────────────►┌──────────────────────┐
│  (IEnforcement)    │     emit posture                   │ stepup_verification  │ M7
│                    │     → safety_posture               │ (IStepupVerification)│
└────────┬───────────┘                                    │ compose + persist    │
         │ safety_posture                                 └──────────┬───────────┘
         │◄──────────────────────────────────────────────────────────┘
         │                                                  StepUpMessage + blocked posture
         ▼
┌────────────────────┐
│  audit_fairness    │  M8  — Ephemeral decision trace (record events)
│    (IAudit)        │
└────────────────────┘
         │
         ▼
   safety_posture returned to host
```

All of the above is coordinated by:

```
┌────────────────────────────────────────────────────────────────┐
│               orchestration (M9/M10)                           │
│  planner_supervisor + guardrails + runner + API                │
│  → wires all modules, enforces invariants, exposes HTTP        │
└────────────────────────────────────────────────────────────────┘
```

---

## Planner-Supervisor Orchestration

The planner-supervisor runs a **plan → act → observe → re-plan** loop per turn. It chooses the route — it cannot choose the safety outcome.

### Required action sequence

```
gate_check
  └─► reuse_posture?  →  finish (return existing posture)
  └─► analyze?
        delegate_extract           (LLM → SignalSet)
        update_evidence            (Python → EvidenceSummary)
        read_evidence              (Python → EvidenceSummary)
        delegate_estimate          (LLM → AgeBandEstimate)
        compute_confidence         (Python → float)
        policy_decide              (Python → Decision)
        emit_posture               (Python → safety_posture)
          └─► action == "step_up"?
                delegate_stepup    (LLM → StepUpMessage)
          └─► finish
```

### Deterministic vs LLM steps

| Step | Type | Why |
|---|---|---|
| `gate_check` | Deterministic | Pure session state — no ambiguity |
| `delegate_extract` | LLM | Natural language understanding required |
| `update_evidence` | Deterministic | Arithmetic merge of cue lists |
| `read_evidence` | Deterministic | Store read |
| `delegate_estimate` | LLM | Band proposal from evidence (structured output) |
| `compute_confidence` | Deterministic | Formula from weights and counts |
| `policy_decide` | Deterministic | Lookup table — no interpretation |
| `emit_posture` | Deterministic | Canonical flag mapping |
| `delegate_stepup` | LLM | Natural language message composition |
| `persist_confirmed` | Deterministic | Storage write with confirmed guard |

---

## Guardrail Enforcement Chain

Every action goes through `enforce_preconditions()` before execution. The enforcer is deterministic Python — the LLM cannot bypass it.

```
planner requests action
          ↓
enforce_preconditions(action_type, params, PlannerState)
  ├── GuardrailViolationError → SAFE_DEFAULT_POSTURE  (fail closed)
  └── passes
          ↓
execute action (tool or delegate)
  ├── Exception → SAFE_DEFAULT_POSTURE  (fail closed)
  └── success
          ↓
record_action_completed(action_type, PlannerState)
          ↓
next planner step
```

**Iteration cap:** If the loop runs `MAX_ITERATIONS` (default 8) times without emitting a posture, `SAFE_DEFAULT_POSTURE` is returned. This guards against infinite re-planning.

---

## Data Flow Through a Turn

A complete trace for a first turn with teen signals:

```
POST /v1/turn  {"session_id": "s1", "turn_text": "ugh my maths teacher is the worst", "turn_number": 1}

gateway_session.ingest()
  → creates session s1: band=unknown, confidence=0.0, turn_count=1

gate.check()
  → turn_count=1 < MIN_TURNS=2, but posture=None → analyze  (NOT reuse_posture)

signal_extraction (LLM)
  → SignalSet { cues: [
      Cue(type="topic",   value="school + teacher", weight=0.7),
      Cue(type="style",   value="casual complain, abbreviated", weight=0.5)
    ]}

evidence_fabric.update()
  → EvidenceSummary { corroboration_score=0.24, cues=[...], turn_count=1 }

ageband_inference (LLM)
  → AgeBandEstimate { band="teen", cited_cues=["school + teacher", "casual abbreviation"],
                       evasion_flag=False, contradictions=[] }

compute_confidence()
  → base = 0.24 × 0.6 = 0.144
     cue_bonus = 2/5 × 0.4 = 0.16
     raw = 0.304  →  confidence = 0.304  →  bucket = "low"

policy_decide()
  → Decision { action="apply", posture_level="caution", reason="teen_low" }

emit_posture()
  → safety_posture { level="caution",
                      flags={mature_content:False, feature_full:True, tone_strict:True} }

audit.record("s1", "posture_emitted", {"level": "caution"})

HTTP 200  {"posture": {"level": "caution", "flags": {...}}}
```

---

## Cross-Module Contracts

Modules must **only** interact through the interfaces defined in `contracts/protocols.py`. Direct imports of concrete classes from other modules are prohibited.

| Consumer | Consumes | Via |
|---|---|---|
| `orchestration` | All modules | Their `I*` protocol |
| `evidence_fabric` | `contracts.models` | `Cue`, `SignalSet`, `EvidenceSummary` |
| `ageband_inference` | `evidence_fabric` (via orchestration) | `EvidenceSummary` |
| `policy_decision` | `ageband_inference` (via orchestration) | `AgeBandEstimate`, `float` |
| `enforcement` | `policy_decision` (via orchestration) | `Decision` |
| `stepup_verification` | `orchestration` | `AgeBandContext` |
| `audit_fairness` | `orchestration` | string events only |

---

## Fail-Closed Invariants

| Scenario | What happens |
|---|---|
| LLM returns confidence in `AgeBandEstimate` | `validate_ageband_estimate()` raises `ValidationError` |
| Planner tries to skip `gate_check` | `GuardrailViolationError` → `SAFE_DEFAULT_POSTURE` |
| Planner tries to emit posture before policy | `GuardrailViolationError` → `SAFE_DEFAULT_POSTURE` |
| `persist_confirmed` called with `confirmed=False` | `PermissionError` (+ `GuardrailViolationError` from guardrails) |
| Iteration cap hit | `SAFE_DEFAULT_POSTURE` (caution) |
| Any exception in action handler | `SAFE_DEFAULT_POSTURE` (caution) |
| Unknown `action_type` from planner | `validate_planner_action()` raises; rejected before execution |
| Unrecognised posture level in `build_posture` | `ValueError` |
| Unknown band in policy table | `Decision(action="none", posture_level="standard")` — safe default |

---

## Session Lifecycle

```
New session
  created by gateway_session with: band=unknown, confidence=0.0, settled=False

Each turn:
  turn_count += 1
  gate decides: analyze vs reuse_posture
  if analyze: full pipeline runs; posture updated on AgeBandContext

Settled:
  when confidence >= GATE_CONFIDENCE_THRESHOLD (0.85) AND settled=True
  → gate returns reuse_posture every turn (no further LLM calls)

Step-up triggered (child/teen + high confidence):
  → stepup_composer writes a confirmation message
  → posture = "blocked" or "restricted"
  → session waits for user confirmation

User confirms age (explicitly):
  → stepup_verification.persist_confirmed(session_id, band, confirmed=True)
  → band stored against session_id (the only write to persistence in the system)

Session ends / process restarts:
  → all inferred state lost (ephemeral)
  → confirmed bands lost in lean build (module-level dict)
  → in production: confirmed bands live in a persistent store (Redis / DB)
```

---

## Integration with the Host Product

The host product calls `POST /v1/turn` after each user message and before generating its reply. The returned `safety_posture` is advisory — the host decides how to apply it.

### Minimum recommended integration

```python
# Pseudocode — host product integration

posture = ageband_client.process_turn(session_id, user_turn)

if posture.level == "blocked":
    # Do not generate a reply; send the step-up message to the user
    return stepup_message

if posture.flags.get("mature_content") is False:
    # Disable adult-content generation mode
    llm_params["safe_mode"] = True

if posture.flags.get("feature_full") is False:
    # Disable non-essential features
    features = RESTRICTED_FEATURE_SET

if posture.flags.get("tone_strict") is True:
    # Use a conservative, child-safe system prompt
    system_prompt = CHILD_SAFE_SYSTEM_PROMPT

reply = generate_reply(user_turn, llm_params, system_prompt)
```

### Posture levels — recommended host behaviour

| Level | Recommended action |
|---|---|
| `standard` | Full feature set, normal tone |
| `caution` | Block mature content, strict tone; all features available |
| `restricted` | Block mature content + reduce feature set, strict tone |
| `blocked` | Do not generate content; present step-up verification message |

---

## tinyagent / LLM Wiring

In the full tinyagent build:

- The **planner-supervisor** is an LLM agent (`planner_supervisor.yaml`) that runs the plan-act loop
- Each `delegate_*` action causes the planner to hand off to a sub-agent (`signal_extractor`, `ageband_estimator`, `stepup_composer`)
- Deterministic tools (`gate_check`, `compute_confidence`, etc.) are Python `@function_tool`s registered with tinyagent
- The planner outputs a `PlannerAction` JSON blob per step; the guardrails validate it before execution

In the lean/test build:

- `OrchestrationService._route()` replaces the LLM planner with a deterministic sequence
- Mock delegates are injected via `mock_delegates` constructor argument
- All guardrails, tools, and module logic run identically

---

## Deployment Topology

```
                         ┌─────────────────────────────────────┐
                         │          Host Product               │
                         │   (AI chat — generates replies)     │
                         └──────────┬──────────────────────────┘
                                    │ POST /v1/turn
                                    ▼
┌──────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                              │
│  ┌─────────────────────┐    ┌────────────────────────────┐  │
│  │   ageband-agent     │    │        ageband-ui          │  │
│  │   (FastAPI/uvicorn) │    │   (React SPA + nginx)      │  │
│  │   :8080             │    │   :80 → /v1/ → agent:8080  │  │
│  └──────────┬──────────┘    └────────────────────────────┘  │
│             │                                                │
│             │ OpenAI-compatible HTTP                         │
│             ▼                                                │
│  ┌─────────────────────┐                                     │
│  │   vLLM on AMD ROCm  │                                     │
│  │   (model server)    │                                     │
│  │   :8000             │                                     │
│  └─────────────────────┘                                     │
└──────────────────────────────────────────────────────────────┘
```

---

## Environment Variable Reference

| Variable | Module | Default | Description |
|---|---|---|---|
| `LOCAL_API_BASE` | orchestration | `http://localhost:8000/v1` | vLLM endpoint |
| `LOCAL_MODEL` | orchestration | `Qwen/Qwen2.5-7B-Instruct` | Model name |
| `LOCAL_API_KEY` | orchestration | `EMPTY` | vLLM API key |
| `PLANNER_MAX_ITERATIONS` | orchestration | `8` | Iteration cap |
| `SKIP_AMD_CHECK` | orchestration | `false` | Skip startup endpoint verification |
| `GATE_CONFIDENCE_THRESHOLD` | gate | `0.85` | Reuse threshold |
| `GATE_MIN_TURNS` | gate | `2` | Min turns for insufficient-data gate |
| `EVIDENCE_DECAY_RATE` | evidence_fabric | `0.1` | Per-call cue weight reduction |
| `INFERENCE_CORROBORATION_WEIGHT` | ageband_inference | `0.6` | Confidence formula weight |
| `INFERENCE_CITED_CUES_WEIGHT` | ageband_inference | `0.4` | Confidence formula weight |
| `INFERENCE_MAX_CITED_CUES_BONUS` | ageband_inference | `5` | Cue bonus saturation point |
| `INFERENCE_EVASION_PENALTY` | ageband_inference | `0.15` | Confidence penalty for evasion |
| `INFERENCE_CONTRADICTION_PENALTY` | ageband_inference | `0.10` | Per-contradiction penalty |

---

## Module Index

| Module | Path | Doc |
|---|---|---|
| contracts | `src/contracts/` | [contracts.md](modules/contracts.md) |
| gate | `src/gate/` | [gate.md](modules/gate.md) |
| signal_extraction | `src/signal_extraction/` | [signal_extraction.md](modules/signal_extraction.md) |
| evidence_fabric | `src/evidence_fabric/` | [evidence_fabric.md](modules/evidence_fabric.md) |
| ageband_inference | `src/ageband_inference/` | [ageband_inference.md](modules/ageband_inference.md) |
| policy_decision | `src/policy_decision/` | [policy_decision.md](modules/policy_decision.md) |
| enforcement | `src/enforcement/` | [enforcement.md](modules/enforcement.md) |
| stepup_verification | `src/stepup_verification/` | [stepup_verification.md](modules/stepup_verification.md) |
| gateway_session | `src/gateway_session/` | [gateway_session.md](modules/gateway_session.md) |
| audit_fairness | `src/audit_fairness/` | [audit_fairness.md](modules/audit_fairness.md) |
| orchestration | `src/orchestration/` | [orchestration.md](modules/orchestration.md) |
| ui | `src/ui/` | (React SPA — see `src/ui/README.md` or root `README.md`) |
