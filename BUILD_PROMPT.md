# AgeBand — Build Prompt (paste into Cursor Composer/Agent in this workspace)

> This is the master build prompt for the AgeBand project. It assumes the Cursor
> "agent starter kit" already present in this workspace (`.cursor/rules`,
> `.cursor/agents`, `.cursor/skills`). It uses the kit's subagents and skills by
> name and follows the kit's standing workflow (design-first and gated,
> production bundle by default, modular prompts, deterministic-safety-over-LLM).
>
> **Terminology guard:** there are TWO planners in play — keep them distinct.
> - The kit's **`planning` subagent** is a *design-time* planner: it writes an
>   Implementation Plan to `.cursor/plans/` and does not execute. Use it to plan
>   the build.
> - AgeBand's **runtime planner-supervisor** is a *component of the product* — an
>   agent that, at runtime, iteratively decides which AgeBand subagent/tool to
>   invoke next for each turn. It is built by this project; it is not the kit's
>   planner.

---

## Project layout 

Non-negotiable output structure. Do not invent alternative locations.

```
<repo root>/
├── src/                # ALL application code (Python packages + YAML agent configs)
│   ├── contracts/          # shared Pydantic models + module interfaces (Phase A)
│   ├── gateway_session/    # M1
│   ├── gate/               # M1.5
│   ├── signal_extraction/  # M2   (incl. the signal_extractor YAML agent)
│   ├── evidence_fabric/    # M3
│   ├── ageband_inference/  # M4   (incl. the ageband_estimator YAML agent + confidence math)
│   ├── policy_decision/    # M5
│   ├── enforcement/        # M6
│   ├── stepup_verification/# M7   (incl. the stepup_composer YAML agent)
│   ├── audit_fairness/     # M8   (minimal/seam for lean build)
│   ├── orchestration/      # M9/M10 (planner_supervisor YAML + Python wiring/guardrails)
│   └── ui/                 # UI service code (or a top-level ui/ if you prefer — see note)
├── tests/              # ALL tests, mirroring src/ (tests/unit, tests/integration, tests/e2e)
├── helm/               # ALL Helm chart(s) — one chart with agent+UI deployments, or a subchart each
├── Dockerfile          # agent-service image at the root
├── Dockerfile.ui       # UI image at the root (second Dockerfile; keep both at root)
├── docs/               # draw.io design(s) + per-module design docs + architecture/data-flow doc
├── Makefile            # task runner incl. `make demo`, test tiers, quality gates
├── README.md
└── reference/          # (existing) source specs + diagrams — DO NOT modify
```

Rules:
- **Code → `src/`** (each module its own package under `src/`; YAML agent config files
  live beside their module's code inside `src/`, e.g. `src/orchestration/planner_supervisor.yaml`).
- **Tests → `tests/`** (mirror the `src/` layout; split `tests/unit`, `tests/integration`,
  `tests/e2e`).
- **Helm → `helm/`** (all chart material here; nothing Helm-related outside `helm/`).
- **Docker → `Dockerfile`** at the repo root for the agent service, and a second
  root-level `Dockerfile.ui` for the UI. Both Dockerfiles stay at the root.
- `docs/`, `Makefile`, `README.md` at the root; `reference/` is read-only input.
- The `@architect` file-tree proposal in step 1 MUST conform to this layout.

---

## 0. Ground yourself first (no code yet)

- Read `./reference/` in full:
  - `ageband_solution.md` — **SINGLE SOURCE OF TRUTH** (architecture, design
    decisions & known limits, glossary). If anything you write contradicts it,
    the doc wins.
  - `ageband_pitch.md` — the pitch (taglines, demo scenarios incl. the
    adversarial one).
  - `ageband_modular_architecture.drawio` — **11-tab** detailed architecture:
    integration; input/entry; per-module M2/M4/M3/M5/M6-M7/M9-M10; agent/subagent
    tree; **Planner-Supervisor** (the runtime plan→act→observe loop + deterministic
    guardrails — READ THIS ONE CLOSELY, it is the orchestration for this build);
    and the lean "as-built".
  - `ageband_diagrams.drawio` — 2-tab high-level (architecture + Agents-SDK UML).
  - `AgeBand_AMD_Pitch.pptx` — the deck.
- Use the solution-doc **glossary** as canonical names everywhere in code, YAML,
  and docs: `TurnEvent`, `SignalSet`, `AgeBandEstimate`, `safety_posture`,
  `confidence`, `confirmed` vs. `inferred`, `settled`, `planner-supervisor`.
- Load skills by relevance (don't bulk-read): **`tinyagent`** (Nokia Agents SDK —
  and its `references/`), **`openai-sdk`**, **`mcp`**, plus **`tdd-workflow`**,
  **`test-case-design`**, **`test-levels`**, **`verification-loop`**. Consult
  **`telco-core`** only if a specific detail needs it.

---

## Framework & structure: YAML per subagent, Python to wire

AgeBand runs on **tinyagent (Nokia Agents SDK)** — the config-driven manager
layer over the OpenAI Agents SDK. Structure the system as:

**YAML — one file per LLM SUBAGENT (declarative):** system prompt, `output_type`,
tool grants, model, input/output filters. Author these as the kit's required
"modular per-role prompt files," and place each YAML beside its module's code in
`src/` (e.g. `src/signal_extraction/signal_extractor.yaml`). The LLM subagents are:
- `signal_extractor` (M2) — one structured extraction pass → `SignalSet`.
- `ageband_estimator` (M4) — proposes band + cited cues + evasion flag.
  **Does NOT emit the confidence number** — confidence is computed
  deterministically in Python.
- `stepup_composer` (M7) — composes the confirm-age / restrict / handoff message.
- `planner_supervisor` (M9/M10) — the runtime planner (see next section).

**Python — the wiring + ALL deterministic logic (no LLM), each in its own module
under `src/`:**
- `orchestration` (M9/M10) — hosts the runtime planner loop, loads the YAML
  subagents via tinyagent, exposes the deterministic tools to the planner, and
  enforces the guardrails below.
- `gateway_session` (M1), `gate` (M1.5), `evidence_fabric` (M3), the
  **confidence math** in M4, `policy_decision` (M5), `enforcement` (M6),
  persistence/override rules in `stepup_verification` (M7) — all pure Python,
  LLM-free, fully unit-testable, exposed to the planner as `@function_tool`s.

**This makes the core invariant a FILE-TYPE boundary:** the *estimate* lives in a
YAML agent; the *decision* (plus confidence, gate, policy, posture, persistence)
lives in deterministic Python. Never put policy/confidence/gate logic inside a
YAML prompt.

### How this maps onto tinyagent's built-ins (resolve the ambiguity explicitly)

tinyagent is config-driven and already provides a supervisor/delegate multi-agent
mechanism, session persistence, MCP wiring, and model serving. Use them — do NOT
re-invent them:

- **Use tinyagent's supervisor + delegate mechanism** for the agent graph
  (`starting_agent: planner_supervisor`, with `signal_extractor`,
  `ageband_estimator`, `stepup_composer` as **delegates** — call-and-return,
  caller keeps identity — using `compress` input filters and `final_message`
  output filters). Declare this in YAML.
- **BUT the safety guardrails and precondition-rejection are CUSTOM Python** that
  wraps the deterministic tool calls. tinyagent will happily run whatever the
  planner asks; it will NOT enforce your "model estimates / deterministic policy
  decides / fail-closed" invariant for you. So the deterministic tools
  (`gate_check`, `read_evidence`, `compute_confidence`, `policy_decide`,
  `emit_posture`, `persist_confirmed`) are `@function_tool`s whose wrapper
  validates preconditions and rejects out-of-order / posture-emitting-by-planner
  / persist-inferred requests before executing. The enforcement lives in YOUR
  Python wrapper, not in tinyagent config.
- **Session state** (band, confidence, settled?, evidence) rides tinyagent's
  session/context; the ephemeral evidence store is your module, keyed by
  `session_id`.

---

## The runtime planner-supervisor (this is the orchestration — NOT hardcoded Python)

Instead of a hardcoded pipeline, orchestration is an **iterative planner-supervisor
agent** (`planner_supervisor`, authored in YAML with its own modular prompt). Per
turn it runs a plan → act → observe → re-plan loop:

1. **Plan** — given the current session state (band, confidence, settled?,
   turn count, evidence summary) and the goal ("produce/refresh a safe
   `safety_posture` for this turn"), decide the *next single action* to take.
2. **Act** — invoke exactly one available action: a deterministic tool
   (`gate_check`, `read_evidence`, `compute_confidence`, `policy_decide`,
   `emit_posture`, `persist_confirmed`) or a delegate subagent
   (`signal_extractor`, `ageband_estimator`, `stepup_composer`).
3. **Observe** — read the typed result.
4. **Re-plan or finish** — loop until the turn's goal is met (a `safety_posture`
   is emitted, or a step-up is raised), then stop.

The planner chooses *the route* (does this turn need re-extraction? more evidence?
is it settled so we can reuse posture? should we escalate to step-up?). It makes
the open-ended judgment calls that a fixed pipeline can't.

### Non-negotiable guardrails on the planner (safety invariant)

The planner decides *which* action runs; it does **not** get to decide safety
outcomes. Enforce in Python (this is the kit's "deterministic safety, LLM
flexibility" rule and the solution doc's "model estimates / deterministic policy
decides" invariant):

- The planner **cannot emit a `safety_posture` itself** — only the deterministic
  `policy_decide` / `emit_posture` tools produce one. The planner may only
  *request* a decision.
- The planner **cannot skip or reorder the safety-critical guards**: a
  `safety_posture` may only be emitted after a valid `AgeBandEstimate` +
  deterministic `compute_confidence` + `policy_decide`. The orchestration layer
  validates the action's preconditions and **rejects** an out-of-order or
  precondition-violating action (fail closed), regardless of what the planner
  asks for.
- **Confidence** is always computed by the deterministic tool, never taken from
  the LLM.
- **Persistence**: only `persist_confirmed` (fed by an explicit user-confirmed
  age) may persist; inferred bands are never persisted. The planner cannot
  persist an inferred band.
- The planner runs **async** by default; a **high-severity transition forces the
  synchronous step-up path** — the orchestration enforces the sync/async choice
  deterministically, not the planner.
- Bounded loop: cap planner iterations per turn (e.g. ≤ N) and fall back to a
  safe default posture if the cap is hit (fail closed).

Author the planner's decision policy as a **modular prompt file**, and give it a
typed action schema (Pydantic) so every planner output is validated before the
orchestration executes it. Invalid / out-of-order → rejected, not run.

---

## 1. Design gate (use `@architect` → STOP for my sign-off)

Use the kit's **`architect`** subagent to produce draw.io design(s) in `./docs/`
that map the reference architecture onto this tinyagent + planner-supervisor
implementation:
- which parts are YAML subagents vs. deterministic Python `@function_tool`s;
- the module boundaries (below);
- the **runtime planner loop** (plan → act → observe → re-plan) and the
  deterministic guardrails/preconditions that constrain it (mirror the
  Planner-Supervisor tab in the reference drawio);
- control/data flow: `TurnEvent` → (planner-driven) gate / extract / evidence /
  estimate / confidence / policy → `safety_posture`, plus step-up / confirm;
- runtime/deployment topology: **2 containers** (agent, UI) + model serving on
  **AMD ROCm / vLLM** (OpenAI-compatible endpoint).

Also propose the **full file tree** (conforming to the FIXED Project layout above)
and the **tinyagent YAML layout**.

**STOP and wait for my verification** before any implementation code, per the
design gate. Do not skip the gate.

### Modules (each in its OWN distinct package under `src/` — clean boundaries, depend on interfaces)

- `gateway_session` (M1) — `TurnEvent` intake, user-turn filter, session/context.
- `gate` (M1.5) — cheap state-check + heuristic tripwire; deterministic, NOT an
  LLM call; catches the settled-session mid-conversation handoff case.
- `signal_extraction` (M2) — one structured LLM pass → `SignalSet`; reading-level
  is a deterministic tool.
- `evidence_fabric` (M3) — session-scoped, ephemeral store; corroboration +
  decay; no profile, no PII.
- `ageband_inference` (M4) — LLM proposes band + cues + evasion flag; **confidence
  computed DETERMINISTICALLY** from evidence + bounded nudge; may return
  `unknown`.
- `policy_decision` (M5) — deterministic table `band × confidence → safety_posture`;
  product mode; step-up + high-severity thresholds; trusted/signed config.
- `enforcement` (M6) — emit `safety_posture {level, flags}`; the host is the
  enforcer; AgeBand never mutates the host model / reply path.
- `stepup_verification` (M7) — step-up; SYNC on high-severity; explicit
  **CONFIRMED** age overrides; only CONFIRMED persists, INFERRED never persists.
- `audit_fairness` (M8) — minimal, ephemeral decision/telemetry trace + the
  false-positive/fairness loop (every step-up that resolves to "actually adult"
  is a labeled false positive that feeds threshold tuning). **Optional for the
  lean first build** — include the module seam and a no-op/minimal implementation
  now, expand later; do not drop it silently.
- `orchestration` (M9/M10) — the runtime planner-supervisor loop + tinyagent
  wiring + MCP registry + model serving config (AMD ROCm/vLLM).

Enforce the solution-doc invariants: model ESTIMATES / deterministic policy
DECIDES; async by default, SYNC only on high-severity; bands not precise ages;
grounded (deterministic) confidence; ephemeral evidence with confirmed-only
persistence; AgeBand emits posture, never touches the host model.

---

## 2. Plan  →  3. Build test-first

- After my sign-off, use the kit's **`planning`** subagent to write a phased
  Implementation Plan to `.cursor/plans/`. Recommended phasing: **lean as-built
  path first** (gate → extract → evidence → estimate → confidence → policy →
  posture, planner-routed, guardrails enforced, one model), then step-up/confirm,
  then audit/fairness and the optional module scale-outs.
- Build with **`tdd-guide`** (RED → GREEN → REFACTOR). Author every agent/role/
  phase prompt as a **separate modular file**. Deterministic modules (gate,
  evidence, confidence math, policy, posture, persistence, planner guardrails)
  must be pure Python, LLM-free, fully unit-testable. All code lands under `src/`,
  all tests under `tests/` (see FIXED Project layout).

---

## AMD serving (this is a hackathon judged on USE OF AMD — make it real, not nominal)

- Serve the open-weight model (Llama-/Qwen-class) via **vLLM on AMD ROCm**,
  exposing an **OpenAI-compatible endpoint**. Point tinyagent at it with the
  local overrides (e.g. `LOCAL_API_BASE`, `LOCAL_MODEL`, and the fast-model
  override if you split later) — **no cloud egress**; the model must be served
  locally/on-prem.
- **One model to start** serves both LLM calls (extract, estimate); only split
  into small+large models if profiling justifies it (keep it single-model for the
  lean build).
- Verify at runtime that inference actually hits the ROCm/vLLM endpoint (a
  startup check or a logged model/endpoint banner), so "runs on AMD" is
  demonstrable, not assumed. Fireworks API is an acceptable *fallback* for dev
  only; the AMD/vLLM path is the story.
- Document the exact serving command + env in the README so a judge can reproduce
  it.

---

## UI (distinct module, separate container)

A lightweight web UI showing a live session: current band, confidence, the
cues/evidence behind it, the active `safety_posture`, the **planner's decision
trace** (which action it chose each step — nice for the demo), and step-up
prompts. Thin client over the agent's API (tinyagent exposes OpenAI-compatible
HTTP + `/v1/*` endpoints — use those). UI code lives under `src/ui/`; its image is
built from the root-level `Dockerfile.ui`.

---

## Runnable demo (you will present this live — make it one command)

- Provide a **`make demo`** (or equivalent single command) that starts the agent
  + UI locally and **replays the 4 scripted conversations** from the solution doc
  (clear-adult, young-teen, ambiguous-adult, and the **adversarial** child-claims-
  adult), showing the band/confidence/posture updating turn-by-turn and the
  step-up firing on the adversarial one.
- The demo must run without a live judge typing — a seeded replay — but also
  allow free-typing into the UI. Keep setup to a couple of commands, documented
  in the README.

---

## Code quality (kit rules, tightened)

- Clean Code + SOLID, strictly. Modules depend on interfaces/protocols, not
  concretions.
- **Radon: grade A wherever achievable (target CC ≤ 5), B only with written
  justification; pure routers/planner-executors grade A; MI ≥ 75.**
- Full type hints; `mypy --strict`; `ruff` + `black`; no dead code.
- Wire the complexity/type/lint/coverage gates into the **`verification-loop`** /
  CI so they FAIL the build.

---

## Docs (`./docs/`)

- The draw.io design(s) from step 1.
- One design doc per module: responsibility, interface/contract (the Pydantic
  types), invariants, and mapping to the drawio module.
- An overall architecture + data-flow doc, including the runtime planner loop, the
  planner guardrails, and the async/sync and confirmed/inferred rules.

---

## Artifacts & deployment

- **TWO containers:** (1) agent service (tinyagent + planner) built from the
  root-level **`Dockerfile`**; (2) UI built from the root-level **`Dockerfile.ui`**.
  Minimal/secure base images. Both Dockerfiles stay at the repo root.
- **Helm chart(s) under `helm/`** for both — values for model endpoint
  (AMD ROCm/vLLM), MCP servers, policy/threshold config, planner iteration cap,
  resources. Document every value. `helm template`/`helm lint` (run against
  `helm/`) must render cleanly.

---

## Tests & automation (use `test-designer` → `test-author` + the testing skills)

- All tests live under **`tests/`**, mirroring `src/` and split into
  `tests/unit`, `tests/integration`, `tests/e2e`.
- **`test-designer`** derives a test-case catalog (tag unit / integration / e2e +
  priority) from the solution doc; **`test-author`** implements and runs it.
- **Unit** (`tests/unit`): every deterministic module (gate tripwire, evidence
  corroboration/decay, confidence math, policy table, posture emission,
  persistence rules) with the LLM mocked; **and the planner guardrails** — assert
  the orchestration rejects out-of-order / precondition-violating /
  posture-emitting-by-planner actions, and that hitting the iteration cap falls
  back to a safe posture (fail closed).
- **Integration** (`tests/integration`): planner-driven flows — extract →
  evidence → estimate → confidence → policy → posture; step-up → confirm →
  override; gate short-circuit on a settled session; sync-on-high-severity.
- **E2E** (`tests/e2e`): the 4 demo scenarios incl. the **ADVERSARIAL** one
  (child claiming adult → evasion signal → planner routes to step-up). Assert
  posture/step-up outcomes.
- **Automation:** root **`Makefile`** + CI running lint, mypy, radon gate,
  unit → integration → e2e, coverage ≥ 85%.

---

## README + reflect

- Proper README (root `README.md`): what AgeBand is; architecture (link `docs/` +
  diagrams); the project layout (`src/`, `tests/`, `helm/`, `Dockerfile`/
  `Dockerfile.ui`); prerequisites; install (local dev + both containers + Helm);
  configuration (model endpoint, MCP, policy/thresholds, planner cap); the exact
  **AMD ROCm/vLLM serving command**; how to run agent + UI; how to run the
  **`make demo`** replay; how to run each test tier; how the quality gates are
  enforced.
- After building, run **`code-review`** and **`logic-checker`** (pay special
  attention to the planner guardrails and any fail-open path). Then reflect and
  update/create the relevant `.cursor/skills` per the standing self-reflection
  loop.

---

## Definition of done (do NOT declare complete until ALL of these hold)

- [ ] `@architect` design in `docs/` approved by me (the design gate).
- [ ] Repo conforms to the FIXED layout: code in `src/`, tests in `tests/`, Helm
      in `helm/`, `Dockerfile` + `Dockerfile.ui` at the root.
- [ ] All modules implemented in their own `src/` packages; the estimate/decision
      file-type boundary respected (no policy/confidence/gate logic in any YAML).
- [ ] Planner-supervisor runs the plan→act→observe loop; **guardrail tests prove
      it cannot emit a posture, skip/reorder guards, take LLM confidence, persist
      an inferred band, or exceed the iteration cap** (all fail closed).
- [ ] Unit + integration + e2e suites GREEN; coverage ≥ 85%.
- [ ] Radon gate passes (grade A target; documented B exceptions only); mypy
      strict clean; ruff + black clean.
- [ ] Both Docker images build (`Dockerfile`, `Dockerfile.ui`); `helm template`/
      `helm lint` on `helm/` render cleanly.
- [ ] Model served via vLLM on AMD ROCm (OpenAI-compatible), verified at runtime;
      no cloud egress on the AMD path.
- [ ] `make demo` runs the 4-scenario replay end-to-end, adversarial one triggers
      step-up, UI shows band/confidence/posture + planner decision trace.
- [ ] README install + demo steps work from a clean checkout.
- [ ] `code-review` + `logic-checker` passes; skills reflected/updated.

---

## Start here

Begin with **step 0 (ground yourself)** and **step 1 (the gated `@architect`
draw.io design + file tree + YAML layout)**. Do **not** write implementation code
until I approve the design and the file tree.
