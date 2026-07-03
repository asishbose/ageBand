# AgeBand

**Passive age-band inference for AI chat products.**

AgeBand reads how a user writes and what they talk about, maintains a live estimate of their age band (child / teen / adult / unknown), and emits a `safety_posture` that the host product can act on — without AgeBand ever touching the reply path.

---

## Key invariants

| Invariant | Enforcement |
|---|---|
| Model ESTIMATES; deterministic policy DECIDES | LLM proposes band + cues; Python table maps band × confidence → posture |
| Confidence is always deterministic | `src/ageband_inference/confidence.py` — never from LLM output |
| Inferred bands never persist | `stepup_verification/persistence.py` raises `PermissionError` if `confirmed=False` |
| Guardrails fail closed | `src/orchestration/guardrails.py` rejects out-of-order actions; iteration cap → safe caution posture |
| AgeBand emits posture; host enforces | `EnforcementService` emits `safety_posture`; host model is never touched |

---

## Architecture

```
TurnEvent
  → Gateway/Session (M1)       — ingest, session context
  → Gate (M1.5)                — analyze or reuse?
  → Signal Extraction (M2)     — LLM: extract cues → SignalSet
  → Evidence Fabric (M3)       — accumulate, decay, corroborate
  → AgeBand Inference (M4)     — LLM: propose band; Python: compute confidence
  → Policy Decision (M5)       — deterministic table: band × confidence → Decision
  → Enforcement (M6)           — emit safety_posture
  → Step-Up Verification (M7)  — confirmed-only persist; LLM compose message
  → Audit/Fairness (M8)        — ephemeral trace
  Orchestration (M9/M10)       — planner-supervisor loop + tinyagent wiring
```

All deterministic modules (gate, evidence_fabric, confidence, policy, enforcement, gateway_session) are pure Python with no LLM calls. Only signal_extraction, ageband_estimator, and stepup_composer delegate to the LLM.

---

## Quickstart (development)

### Prerequisites

- Python 3.12+
- Node 20+ (for the UI)
- A running [vLLM](https://github.com/vllm-project/vllm) instance on AMD ROCm (or any OpenAI-compatible endpoint)

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure the model endpoint

```bash
export LOCAL_API_BASE=http://localhost:8000/v1
export LOCAL_MODEL=Qwen/Qwen2.5-7B-Instruct
export LOCAL_API_KEY=EMPTY
```

### 3. Start the agent service

```bash
SKIP_AMD_CHECK=true uvicorn src.orchestration.api:app --host 0.0.0.0 --port 8080 --reload
```

### 4. Build and start the UI

```bash
cd src/ui
npm install
npm run dev
```

The UI proxies `/v1/` to `localhost:8080`. Open http://localhost:5173.

### 5. Run tests

```bash
# Unit tests (fast, mocked LLM)
pytest tests/unit/

# Integration tests
pytest tests/integration/

# E2E scenario tests (adversarial, fairness, happy-path)
pytest tests/e2e/

# All tests with coverage
pytest tests/ --cov=src --cov-report=term-missing
```

---

## Project layout

```
src/
  contracts/          # Pydantic models + protocols + validators (FROZEN)
  gate/               # M1.5 — deterministic tripwire
  signal_extraction/  # M2 — LLM signal extraction + Flesch-Kincaid
  evidence_fabric/    # M3 — ephemeral cue store, corroboration, decay
  ageband_inference/  # M4 — LLM estimate + deterministic confidence
  policy_decision/    # M5 — deterministic policy table
  enforcement/        # M6 — safety_posture emission
  stepup_verification/# M7 — confirmed-only persistence + step-up composer
  gateway_session/    # M1 — session lifecycle
  audit_fairness/     # M8 — minimal ephemeral audit trace
  orchestration/      # M9/M10 — planner loop, guardrails, FastAPI app
  ui/                 # React SPA (Vite, TypeScript)
prompts/              # Modular LLM prompt files (one per agent role)
tests/
  unit/               # Pure unit tests (LLM mocked)
  integration/        # Module integration (still mocked LLM)
  e2e/                # Scenario tests: clear adult, young teen, ambiguous, adversarial
helm/ageband/         # Helm chart for Kubernetes deployment
```

---

## Docker

### Build

```bash
# Agent service
docker build -t ageband-agent:1.0.0 .

# UI
docker build -f src/ui/Dockerfile.ui -t ageband-ui:1.0.0 src/ui/
```

### Run (development)

```bash
docker run --rm -p 8080:8080 \
  -e LOCAL_API_BASE=http://host.docker.internal:8000/v1 \
  -e LOCAL_MODEL=Qwen/Qwen2.5-7B-Instruct \
  -e SKIP_AMD_CHECK=true \
  ageband-agent:1.0.0
```

---

## Helm / Kubernetes

```bash
# Install
helm install ageband ./helm/ageband \
  --set agent.env.LOCAL_API_BASE=http://vllm-service:8000/v1 \
  --set agent.env.LOCAL_MODEL=Qwen/Qwen2.5-7B-Instruct

# Upgrade
helm upgrade ageband ./helm/ageband --reuse-values

# Uninstall
helm uninstall ageband
```

Key values to override (`-f my-values.yaml`):

| Key | Default | Description |
|---|---|---|
| `agent.env.LOCAL_API_BASE` | `http://vllm-service:8000/v1` | vLLM / AMD endpoint |
| `agent.env.LOCAL_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | Model name |
| `agent.replicaCount` | `2` | Agent pod replicas |
| `agent.autoscaling.enabled` | `false` | Enable HPA |
| `ui.enabled` | `true` | Deploy the React UI |
| `ingress.enabled` | `false` | Expose via Ingress |

---

## AMD ROCm / vLLM serving

AgeBand is designed to run against a local vLLM instance on AMD ROCm GPUs:

```bash
# Example: start vLLM with ROCm
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 --port 8000 \
  --device rocm
```

Set `LOCAL_API_BASE` and `LOCAL_MODEL` to point at the running instance. On startup, AgeBand verifies the endpoint is reachable and the model is available; set `SKIP_AMD_CHECK=true` for local dev without a GPU.

---

## Safety design

AgeBand is a **safety signal, not surveillance**.

- **Bands, not ages.** The system infers broad bands (child/teen/adult/unknown); precise ages are never estimated.
- **Graduated response.** Posture levels (`standard → caution → restricted → blocked`) allow the host to respond proportionately.
- **Fairness.** Unknown band + low confidence → `standard` posture. The system does not over-restrict ambiguous users. See `tests/e2e/test_ambiguous_adult.py`.
- **Adversarial resistance.** Evasion detection and contradiction penalties reduce confidence when signals are inconsistent. See `tests/e2e/test_adversarial.py`.
- **Ephemeral evidence.** No age data persists unless the user explicitly confirms. Inferred bands are session-only.
- **Host enforces.** AgeBand emits a posture; the host product decides what to do with it. AgeBand never touches the reply.

---

## Quality gates

| Gate | Target |
|---|---|
| `pytest` coverage | ≥ 85% |
| `mypy --strict` | Zero errors |
| `ruff` | Zero errors |
| Radon CC | ≤ A (routers/planners), ≤ B with justification |
| Radon MI | ≥ 75 |

Run all gates:

```bash
pytest tests/ --cov=src --cov-fail-under=85
mypy src/ --strict --ignore-missing-imports
ruff check src/
radon cc src/ -n B
radon mi src/ -n B
```

---

## License

Apache 2.0 — see `LICENSE`.
