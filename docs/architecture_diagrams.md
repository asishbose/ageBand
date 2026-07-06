# AgeBand — Architecture Diagrams

Auto-generated from a read of `src/`. Four views:

1. [Component architecture](#1-component-architecture) — modules, LLM vs deterministic split
2. [Call flow](#2-call-flow-run_turn-sequence) — `run_turn` planner loop (sequence)
3. [Planner routing state machine](#3-planner-routing--guardrail-state-machine) — ordered pipeline + guardrails
4. [Data models](#4-data-models-class-diagram) — Pydantic contracts

---

## 1. Component architecture

```mermaid
flowchart TB
    Host["Host chat product<br/>(owns reply path)"]

    subgraph API["orchestration/api.py — FastAPI"]
        EP["POST /v1/turn<br/>GET /health"]
    end

    subgraph ORCH["OrchestrationService (M9/M10) — runner.py"]
        LOOP["run_turn: planner loop<br/>(max 8 iterations)"]
        GR["guardrails.py<br/>preconditions + iteration cap"]
    end

    subgraph DET["Deterministic core — pure Python, NO LLM"]
        M1["GatewaySessionService (M1)<br/>ingest → AgeBandContext"]
        M15["GateService (M1.5)<br/>analyze vs reuse_posture"]
        M3["EvidenceFabricService (M3)<br/>accumulate · corroborate · decay"]
        CONF["compute_confidence (M4b)<br/>DETERMINISTIC score"]
        M5["PolicyDecisionService (M5)<br/>band × confidence → Decision"]
        M6["EnforcementService (M6)<br/>Decision → safety_posture"]
        M7p["persistence (M7)<br/>confirmed-only, fail closed"]
        M8["AuditFairnessService (M8)<br/>ephemeral trace"]
    end

    subgraph LLM["LLM delegates — tinyagent YAML agents"]
        M2["SignalExtractorService (M2)<br/>turn → SignalSet"]
        M4["AgeBandInferenceService (M4)<br/>evidence → AgeBandEstimate"]
        M7c["stepup_composer (M7)<br/>→ StepUpMessage"]
    end

    subgraph STORE["Ephemeral in-process stores (no PII persistence)"]
        SS["_session_store"]
        ES["evidence _store"]
        CS["_confirmed dict"]
    end

    VLLM["vLLM / OpenAI-compatible<br/>endpoint on AMD ROCm"]

    Host -->|TurnEvent| EP --> LOOP
    LOOP --> GR
    LOOP --> M1 --> SS
    LOOP --> M15
    LOOP -.delegate.-> M2
    LOOP --> M3 --> ES
    LOOP -.delegate.-> M4
    LOOP --> CONF
    LOOP --> M5
    LOOP --> M6
    LOOP -.delegate.-> M7c
    LOOP --> M7p --> CS
    LOOP --> M8
    M2 --> VLLM
    M4 --> VLLM
    M7c --> VLLM
    M6 -->|safety_posture| Host

    classDef det fill:#e3f2fd,stroke:#1565c0,color:#0d47a1;
    classDef llm fill:#fff3e0,stroke:#e65100,color:#e65100;
    classDef store fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c;
    class M1,M15,M3,CONF,M5,M6,M7p,M8 det;
    class M2,M4,M7c llm;
    class SS,ES,CS store;
```

> **Key invariant shown:** the LLM only *estimates* (M2, M4, M7-compose). Every *decision* — confidence, policy, posture, persistence — is deterministic Python. `safety_posture` flows back to the host; AgeBand never touches the reply path.
>
> **Note on the lean build:** in `runner.py` the delegate handlers (`_handle_extract`, `_handle_estimate`, `_handle_stepup`) use an injected `_mock_delegates` seam or safe defaults — the standalone `SignalExtractorService` / `AgeBandInferenceService` are the production LLM path they stand in for.

---

## 2. Call flow: `run_turn` (sequence)

```mermaid
sequenceDiagram
    autonumber
    participant Host
    participant API as api.py
    participant O as OrchestrationService
    participant GW as Gateway (M1)
    participant G as Gate (M1.5)
    participant SX as SignalExtractor (M2, LLM)
    participant EF as EvidenceFabric (M3)
    participant EST as Estimator (M4, LLM)
    participant CF as confidence (det.)
    participant PD as Policy (M5)
    participant EN as Enforcement (M6)
    participant SU as StepUp (M7, LLM)
    participant AU as Audit (M8)

    Host->>API: POST /v1/turn (TurnEvent)
    API->>O: run_turn(turn)
    O->>GW: ingest(turn)
    GW-->>O: AgeBandContext

    loop planner loop (≤ MAX_ITERATIONS=8)
        Note over O: _route() scans _ROUTE_SEQUENCE for first incomplete flag
        O->>G: gate_check(ctx)
        alt gate = reuse_posture
            G-->>O: reuse (settled / high-confidence / thin data)
            Note over O: route → finish (keep prior posture)
        else gate = analyze
            O->>SX: delegate_extract(turn)
            SX-->>O: SignalSet (cues)
            O->>EF: update_evidence(session, signals)
            EF-->>O: EvidenceSummary (corroboration, turn_count)
            O->>EST: delegate_estimate(evidence)
            EST-->>O: AgeBandEstimate (band, cited_cues, evasion, contradictions)
            O->>CF: compute_confidence(evidence, estimate)
            CF-->>O: confidence: float  (never from LLM)
            O->>PD: policy_decide(estimate, confidence)
            PD-->>O: Decision (action, posture_level, flags)
            O->>EN: emit_posture(decision)
            EN-->>O: safety_posture
            O->>AU: record("posture_emitted", level)
            alt Decision.action == step_up
                O->>SU: delegate_stepup()
                SU-->>O: StepUpMessage (confirm / restrict / handoff)
            end
        end
    end

    O-->>API: safety_posture
    API-->>Host: {"posture": {...}}

    Note over O,AU: any GuardrailViolation, handler exception,<br/>or iteration cap → SAFE_DEFAULT_POSTURE (fail closed)
```

---

## 3. Planner routing & guardrail state machine

Each turn runs an ordered pipeline. `_route()` picks the next action from the first
unset `PlannerState` flag; `enforce_preconditions()` blocks any out-of-order action.

```mermaid
stateDiagram-v2
    [*] --> gate_checked: gate_check
    gate_checked --> finish: gate=reuse_posture
    gate_checked --> extract_done: delegate_extract<br/>(needs gate_checked)
    extract_done --> evidence_read: update_evidence<br/>(needs extract_done)
    evidence_read --> estimate_done: delegate_estimate<br/>(needs evidence_read)
    estimate_done --> confidence_computed: compute_confidence<br/>(needs estimate_done)
    confidence_computed --> policy_decided: policy_decide<br/>(needs confidence_computed)
    policy_decided --> posture_emitted: emit_posture<br/>(needs policy_decided)
    posture_emitted --> step_up_requested: delegate_stepup<br/>(if Decision=step_up)
    posture_emitted --> finish: else
    step_up_requested --> finish
    finish --> [*]

    note right of confidence_computed
        Confidence is DETERMINISTIC.
        Planner may never supply it —
        require_confidence_before_policy
        rejects policy without it.
    end note

    state "SAFE_DEFAULT_POSTURE (caution)" as SAFE
    SAFE --> [*]
    note left of SAFE
        Fail-closed exits:
        · GuardrailViolation (out-of-order)
        · handler exception
        · iteration ≥ 8 cap
        · persist without confirmed=True
    end note
```

---

## 4. Data models (class diagram)

Pydantic v2 models from `contracts/models.py` (all `extra="forbid"`).

```mermaid
classDiagram
    class TurnEvent {
        +str session_id
        +str turn_text
        +int turn_number
        +datetime timestamp
    }
    class Cue {
        +Literal type: vocab|topic|disclosure|style|reading_level
        +str value
        +float weight  0..1
    }
    class SignalSet {
        +list~Cue~ cues
    }
    class EvidenceSummary {
        +str session_id
        +list~Cue~ cues
        +float corroboration_score  0..1
        +int turn_count
    }
    class AgeBandEstimate {
        +Literal band: child|teen|adult|unknown
        +list~str~ cited_cues
        +bool evasion_flag
        +list~str~ contradictions
        %% NO confidence field — invariant
    }
    class GateResult {
        +Literal action: analyze|reuse_posture
        +str reason
    }
    class Decision {
        +Literal action: apply|step_up|none
        +Literal posture_level: standard|caution|restricted|blocked
        +dict~str,bool~ flags
        +str reason
    }
    class safety_posture {
        +Literal level: standard|caution|restricted|blocked
        +dict~str,bool~ flags
    }
    class StepUpMessage {
        +str message_text
        +Literal action: confirm|restrict|handoff
    }
    class PlannerAction {
        +Literal action_type
        +dict params
    }
    class AgeBandContext {
        +str session_id
        +Literal current_band
        +float confidence  0..1
        +bool settled
        +int turn_count
        +EvidenceSummary evidence_summary
        +safety_posture posture
    }

    SignalSet "1" o-- "*" Cue
    EvidenceSummary "1" o-- "*" Cue
    AgeBandContext "1" o-- "0..1" EvidenceSummary
    AgeBandContext "1" o-- "0..1" safety_posture

    TurnEvent ..> SignalSet : M2 extract
    SignalSet ..> EvidenceSummary : M3 update
    EvidenceSummary ..> AgeBandEstimate : M4 estimate
    AgeBandEstimate ..> Decision : M5 decide(+confidence)
    Decision ..> safety_posture : M6 emit
    Decision ..> StepUpMessage : M7 compose (if step_up)
```

### Confidence derivation (deterministic, `ageband_inference/confidence.py`)

```mermaid
flowchart LR
    A["EvidenceSummary<br/>.corroboration_score"] --> B["base = corroboration × CORROBORATION_WEIGHT"]
    C["AgeBandEstimate<br/>.cited_cues"] --> D["cue_bonus = min(n, MAX)/MAX × CITED_CUES_WEIGHT"]
    B --> E["raw = base + cue_bonus"]
    D --> E
    F["evasion_flag"] --> G["− EVASION_PENALTY"]
    H["contradictions (≤3)"] --> I["− n × CONTRADICTION_PENALTY"]
    E --> J
    G --> J
    I --> J["clamp(raw − penalties, 0..1)"]
    J --> K["confidence: float"]
    style K fill:#e3f2fd,stroke:#1565c0
```
