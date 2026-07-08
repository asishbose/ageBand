# AgeBand

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

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

The **roster module** (`src/roster/`) is a demo-layer extension on top of the pipeline: it replays a DiscordChatExporter JSON export through the pipeline — one session per author — and renders a risk-ranked per-user table in the UI (`Session | Roster` tabs). It does not add new inference logic; it reuses the existing pipeline unchanged. See `docs/modules/roster.md` and the `/v1/roster` API endpoint.

---

## Inference backends & determinism

The LLM delegates (M2 extraction, M4 estimation) run against any OpenAI-compatible
endpoint, or a **fully deterministic offline path** when none is configured — so
the whole pipeline runs end-to-end with no GPU. Select with `AGEBAND_INFERENCE_MODE`:

| Mode | Behaviour |
|---|---|
| `deterministic` | Keyword extractor + rule estimator (no model). Offline demo default. |
| `llm` | Calls `LOCAL_MODEL` at `LOCAL_API_BASE` (Ollama / vLLM / Fireworks). |
| `auto` (default) | LLM when `LOCAL_MODEL` is set, else deterministic. |

**Cue weights are always assigned by the lexicon** (`signal_extraction/lexicon.py`),
never by the model — the LLM detects cues, Python scores them, and confidence
(`ageband_inference/confidence.py`) is computed deterministically from that. This
makes "confidence is deterministic" true regardless of backend. In the lean build
there is **no LLM confidence nudge** — confidence is 100% deterministic.

Compare backends on the demo transcripts:

```bash
ollama pull llama3.2:3b
python scripts/compare_backends.py llama3.2:3b            # + gemma4:31b, etc.
```

See [`docs/model_comparison.md`](docs/model_comparison.md) for results, the
research grounding behind the lexicon weights, and the competitive landscape.
A key finding: on the adversarial transcript, a 31B model was *fooled* into
"adult" while the deterministic evasion guard held — the careful shell is
load-bearing.

**Multilingual support:** `langdetect` is installed and confirmed working for en / es / fr / hi / ar / zh. Non-English turns are detected and abstained correctly (no false cues injected from the English lexicon). The `eval_multilang.py` harness covers per-language accuracy in the LLM path; run with `make eval-multilang`. Short Latin-script text (< 50 chars) falls back to an ASCII-ratio heuristic — confidence is lower, but no false positives.

**AMD telemetry:** the UI's _Session_ tab shows live GPU utilisation and vLLM throughput metrics when the AMD/vLLM endpoint is available; it degrades gracefully (no badge, no error) when running offline or without a GPU.

For AMD Instinct MI300X throughput numbers (sessions/GPU, p95 latency, tok/s, $/1k turns),
see [`docs/benchmarks_mi300x.md`](docs/benchmarks_mi300x.md).
Numbers are **PENDING** a real MI300X run — the benchmark script is ready:
`python scripts/benchmark_roster.py --concurrency 1 5 10 25 50 --samples 200`.

---

## Quickstart (development)

> **Shortcut:** if you have `make`, `make setup && make run` (agent) plus
> `make run-ui` (UI, separate terminal) covers steps 1–4 below. See the
> [Makefile](#makefile) section for the full target list.

### Prerequisites

- Python 3.12+
- Node 20+ (for the UI)
- A running [vLLM](https://github.com/vllm-project/vllm) instance on AMD ROCm (or any OpenAI-compatible endpoint) — **optional**: the system runs demo-ready with no GPU via the offline fallback (see [Inference backends](#inference-backends--determinism) above)

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure the model endpoint

```bash
export LOCAL_API_BASE=http://localhost:8000/v1
# Suggested defaults: Gemma 3 family on AMD vLLM ROCm or Fireworks AI.
# Any OpenAI-compatible model works — these are defaults, not requirements.
export LOCAL_MODEL=google/gemma-3-4b-it
export LOCAL_API_KEY=EMPTY

# Optional: separate models per delegate (dual-model serving, Phase P0-B).
# Extractor (M2) — small, fast; Estimator (M4) — larger, better reasoning.
export EXTRACTOR_MODEL=google/gemma-3-4b-it
export ESTIMATOR_MODEL=google/gemma-3-27b-it
```

### 3. Start the agent service

**With a model endpoint (AMD/vLLM):**
```bash
SKIP_AMD_CHECK=true uvicorn src.orchestration.api:app --host 0.0.0.0 --port 8080 --reload
```

**Without a GPU — offline / deterministic mode (demo-ready, no model required):**
```bash
AGEBAND_INFERENCE_MODE=deterministic SKIP_AMD_CHECK=true \
  uvicorn src.orchestration.api:app --host 0.0.0.0 --port 8080 --reload
```

In offline mode the keyword extractor (`signal_extraction/keyword_extractor.py`) and rule estimator (`ageband_inference/rule_estimator.py`) replace the LLM delegates. All safety logic (gate, confidence, policy, posture, guardrails) runs identically. The full demo pipeline works end-to-end with no GPU.

### 4. Build and start the UI

```bash
cd src/ui
npm install
npm run dev
```

The UI proxies `/v1/` to `localhost:8080`. Open http://localhost:5173.

### 5. Run tests

> `PYTHONPATH=.` is required because the project does not install itself as an editable package in all environments.

```bash
# Unit tests (fast, mocked LLM)
PYTHONPATH=. pytest tests/unit/

# Integration tests
PYTHONPATH=. pytest tests/integration/

# E2E scenario tests (adversarial, fairness, happy-path, offline scenarios)
PYTHONPATH=. pytest tests/e2e/

# All tests with coverage
PYTHONPATH=. pytest tests/ --cov=src --cov-report=term-missing
```

---

## API reference

The agent service exposes a FastAPI app at `http://localhost:8080`.

| Route | Method | Description |
|---|---|---|
| `GET /health` | — | Liveness check — `{"status": "ok"}` |
| `POST /v1/turn` | JSON body | Process a turn; returns full verbose session state (band, confidence, posture, evidence, planner trace) |
| `POST /v1/chat/completions` | OpenAI-compatible body | Same pipeline as `/v1/turn`; response wraps `SessionState` in `choices[0].message.content` — used by the UI's agent client |
| `POST /v1/confirm` | `{"session_id": ..., "band": ...}` | Persist a confirmed age band for a session; calls `persist_confirmed(..., confirmed=True)` |
| `POST /v1/roster` | DiscordChatExporter JSON (optional) | Replay a whole channel export through AgeBand — one session per author — and return a risk-ranked per-user table. Omit body to use the bundled synthetic sample. **Intended use only:** a channel you own, consenting participants, or synthetic data. |

### `/v1/turn` example

```bash
curl -s -X POST http://localhost:8080/v1/turn \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo","turn_text":"i need help w my homework lol","turn_number":1}' | python3 -m json.tool
```

Response fields: `session_id`, `band`, `confidence`, `posture` (`{level, flags}`), `evidence` (cue list + corroboration score), `trace` (planner action list), `step_up` (null or step-up message).

---

## Makefile

A `Makefile` at the repo root wraps everything above (and the Docker /
Helm / quality-gate commands further down this README) into short,
memorable targets. Run `make help` (or just `make`) to see the full,
auto-generated list — it stays in sync with the file, so it's always
current.

### One-time setup

```bash
make setup          # pip install + npm install (UI) + create .env from .env.example
```

`.env.example` documents every variable the agent reads (`LOCAL_API_BASE`,
`LOCAL_MODEL`, `LOCAL_API_KEY`, `SKIP_AMD_CHECK`, planner/gate tuning,
`LOG_LEVEL`). Copy it once via `make setup-env` (also run automatically by
`make setup`) and edit `.env` for your endpoint — `make run` / `make
docker-run` read the same defaults, override any of them inline, e.g.
`make run LOCAL_MODEL=Qwen/Qwen2.5-14B-Instruct`.

### Day-to-day development

| Command | What it does |
|---|---|
| `make run` | Start the agent service (`uvicorn --reload`, `SKIP_AMD_CHECK=true`) |
| `make run-ui` | Start the Vite UI dev server (proxies `/v1/` → `localhost:8080`) |
| `make health` | Curl the local `/health` endpoint |
| `make test` | Full suite with coverage (`tests/`) |
| `make test-unit` / `test-integration` / `test-e2e` | Run one test tier only |
| `make test-ui` | Run the UI's vitest suite |
| `make lint` / `make lint-ui` | ruff (Python) / eslint (UI) |
| `make format` | black + `ruff --fix` |
| `make typecheck` | `mypy --strict` |
| `make complexity` | Radon CC + MI thresholds |
| `make quality` | lint + typecheck + complexity + the 85% coverage gate, in one shot — what CI should run |

### Docker

| Command | What it does |
|---|---|
| `make docker` | Build `ageband-agent:$(VERSION)` (+ `:latest`) locally |
| `make docker-ui` | Build `ageband-ui:$(VERSION)` (+ `:latest`) locally (via `src/ui/Dockerfile.ui`) |
| `make docker-build-all` | Build both images |
| `make docker-run` | Run the agent image locally on port 8080 |
| `make docker-run-ui` | Run the UI image locally on port 8081 (nginx) |
| `make docker-stop` | Stop both local containers |
| `make docker-push IMAGEREPO=myregistry:5000` | Tag + push the **agent** image only |
| `make docker-push-ui IMAGEREPO=myregistry:5000` | Tag + push the **UI** image only |
| `make docker-push-all IMAGEREPO=myregistry:5000` | Tag + push **both** images |

All push targets fail fast if `IMAGEREPO` isn't set — no registry is
hardcoded. Pass `VERSION=1.2.3` to tag a real release instead of `latest`
(default).

### Helm

| Command | What it does |
|---|---|
| `make helm-lint` | `helm lint helm/ageband` |
| `make helm-install-local` | `helm upgrade --install` into the current `kubectl` context using whatever images/tags are already in `values.yaml`, passing through `LOCAL_API_BASE` / `LOCAL_MODEL` |
| `make helm-release IMAGEREPO=myregistry:5000` | **Builds + pushes both images**, then installs the chart with `agent.image.*` and `ui.image.*` pointed at the freshly-pushed `IMAGEREPO/…:VERSION` — the one-command path from source to a running agent+UI deployment |
| `make helm-uninstall` | `helm uninstall` the release |

The chart (`helm/ageband/values.yaml`) deploys **both** the agent
(`deployment-agent.yaml`) and the UI (`deployment-ui.yaml`, toggled via
`ui.enabled`) — `helm-release` is the target that keeps both images'
tags in sync with what you just built, so you don't hand-edit
`values.yaml` before every deploy.

### Cleanup

| Command | What it does |
|---|---|
| `make clean` | Remove Python caches, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, coverage output, `build/`/`dist/` |
| `make clean-ui` | Remove `src/ui/dist` and `src/ui/node_modules` |
| `make clean-all` | `clean` + `clean-ui` + local virtualenvs |

All targets are declared `.PHONY`; `IMAGE_NAME`, `HELM_CHART_PATH`,
`LOCAL_API_BASE`, `LOCAL_MODEL`, etc. are Makefile variables you can
override per-invocation (`make run LOCAL_API_BASE=http://gpu-box:8000/v1`)
without editing the file.

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
  -e LOCAL_MODEL=google/gemma-3-4b-it \
  -e SKIP_AMD_CHECK=true \
  ageband-agent:1.0.0
```

---

## Helm / Kubernetes

```bash
# Install
helm install ageband ./helm/ageband \
  --set agent.env.LOCAL_API_BASE=http://vllm-service:8000/v1 \
  --set agent.env.LOCAL_MODEL=google/gemma-3-4b-it

# Upgrade
helm upgrade ageband ./helm/ageband --reuse-values

# Uninstall
helm uninstall ageband
```

Key values to override (`-f my-values.yaml`):

| Key | Default | Description |
|---|---|---|
| `agent.env.LOCAL_API_BASE` | `http://vllm-service:8000/v1` | vLLM / AMD endpoint |
| `agent.env.LOCAL_MODEL` | `google/gemma-3-4b-it` | Shared fallback model |
| `agent.env.EXTRACTOR_MODEL` | `google/gemma-3-4b-it` | M2 signal extractor (small, fast; falls back to `LOCAL_MODEL`) |
| `agent.env.ESTIMATOR_MODEL` | `google/gemma-3-27b-it` | M4 age-band estimator (larger, better reasoning; falls back to `LOCAL_MODEL`) |
| `agent.replicaCount` | `2` | Agent pod replicas |
| `agent.autoscaling.enabled` | `false` | Enable HPA |
| `ui.enabled` | `true` | Deploy the React UI |
| `ingress.enabled` | `false` | Expose via Ingress |

---

## AMD ROCm / vLLM serving

AgeBand is designed to run against a local vLLM instance on AMD ROCm GPUs:

```bash
# Example: start vLLM with ROCm
vllm serve google/gemma-3-4b-it \
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

| Gate | Target | Current status |
|---|---|---|
| `pytest` coverage | ≥ 85% | **86.63%** ✓ |
| `mypy --strict` | Zero errors | **0 errors** ✓ (`explicit_package_bases = true` set in `pyproject.toml`; dual-module-name error resolved; 9 stale `unused-ignore` stubs removed) |
| `ruff` | Zero errors in `src/` | ✓ |
| Radon CC | ≤ A (routers/planners), ≤ B with justification | ✓ |
| Radon MI | ≥ 75 | `runner.py` MI ≈ 37 (written justification in `docs/modules/orchestration.md`) |

Run all gates (`make quality` runs them all in one shot):

```bash
PYTHONPATH=. pytest tests/ --cov=src --cov-fail-under=85
mypy src/ --strict
ruff check src/
radon cc src/ -n B
radon mi src/ -n B
```

### Synthetic evaluation

A separate manual eval harness measures pipeline accuracy against LLM-generated
synthetic transcripts. It is **not** wired into `pytest` or CI — it calls real
model endpoints and is an offline analysis tool:

```bash
# Generate 20 fixtures per band×difficulty combo (if empty), then eval:
GENERATOR_API_BASE=http://localhost:11434/v1 GENERATOR_MODEL=<writer> \
EVAL_API_BASE=http://localhost:8001/v1      EVAL_MODEL=<evaluator>    \
  make eval-synthetic
```

Outputs a confusion matrix (band × band), per-band precision/recall/F1, and
false-positive rates broken down by difficulty tier (`clear` / `ambiguous` /
`evasive`). Reports are saved to `scripts/eval_results/<timestamp>.json`.

See [`docs/modules/synthetic_eval.md`](docs/modules/synthetic_eval.md) for the
full two-model design rationale, CLI reference, and how to read the output.

---

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) for the full text.

Copyright 2026 Asish Bose.
