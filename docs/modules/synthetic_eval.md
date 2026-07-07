# Module: `synthetic_eval` — Synthetic Evaluation Harness

**Location:** `scripts/generate_synthetic_chats.py`, `scripts/eval_pipeline_against_synthetic.py`  
**Fixture output:** `tests/fixtures/synthetic/`  
**Report output:** `scripts/eval_results/<timestamp>.json`  
**LLM calls:** Two independent model endpoints — generator and evaluator are deliberately separate  
**Protocol:** Manual eval tool — NOT part of the production pipeline, NOT wired into pytest or CI

---

## Purpose

AgeBand needs a quantifiable accuracy and fairness signal, but real user chat data
is not available (and would be inappropriate) for this kind of offline evaluation.
The synthetic eval harness solves this by:

1. **Generating** short multi-turn chat transcripts in a known age band and difficulty
   tier, using an LLM prompted by
   `src/synthetic_eval/prompts/chat_generator_prompt.md`.
2. **Evaluating** those transcripts by replaying each turn through the *real*
   production pipeline — unchanged code, same modules, same safety logic — and
   measuring how accurately the pipeline recovers the ground-truth band.

The output is a confusion matrix plus per-band precision/recall/F1 and
false-positive rates broken down by difficulty tier. The last metric is the most
important one for the fairness story (see [Reading the output](#reading-the-output)
below).

---

## Two-model design

```
GENERATOR_MODEL  ──────── writes transcripts  ──────► tests/fixtures/synthetic/
(Model A)                                                      │
                                                               ▼
EVAL_MODEL  ──── runs the real pipeline  ◄──── replays turns from fixture
(Model B)        (same code as production)
```

**Why two different models?** If the generator and evaluator are the same model,
the pipeline can recognise its own writing style — sentence structures, vocabulary
patterns, and cue placement that the generator used — artificially inflating accuracy.
Using a separate evaluator gives a realistic picture of generalisation to genuine
user input.

### Configured endpoints

| Role | Env var | Default (`.env.example`) | Override |
|---|---|---|---|
| Generator base URL | `GENERATOR_API_BASE` | `http://localhost:11434/v1` | Set per-run |
| Generator model | `GENERATOR_MODEL` | *(none — required)* | e.g. `qwen3.5:2b` |
| Generator API key | `GENERATOR_API_KEY` | `EMPTY` | Bearer token |
| Evaluator base URL | `EVAL_API_BASE` | falls back to `LOCAL_API_BASE` | e.g. `http://localhost:8001/v1` |
| Evaluator model | `EVAL_MODEL` | *(none — required)* | e.g. `Qwen/Qwen2.5-7B-Instruct` |
| Evaluator API key | `EVAL_API_KEY` | falls back to `LOCAL_API_KEY` | Bearer token |

> **AMD/vLLM demo:** running with two different models simultaneously loads two
> distinct GPU workloads off the same (or different) ROCm endpoints, making this
> a natural demo of concurrent multi-model serving. See [docs/synthetic_eval.md](../synthetic_eval.md).

---

## Generator script

`scripts/generate_synthetic_chats.py` calls `GENERATOR_API_BASE`/`GENERATOR_MODEL`
via its *own* HTTP client (never shares config with `LOCAL_API_BASE`/`LOCAL_MODEL`
to prevent accidental cross-contamination).

System prompt is loaded verbatim from
`src/synthetic_eval/prompts/chat_generator_prompt.md` — not inlined in the script.

### CLI

```bash
# Single combination (5 clear adult transcripts):
GENERATOR_API_BASE=http://localhost:11434/v1 \
GENERATOR_MODEL=qwen3.5:2b \
  python scripts/generate_synthetic_chats.py \
  --band adult --difficulty clear --count 5

# All 9 combinations (band × difficulty), 20 samples each:
GENERATOR_API_BASE=http://localhost:11434/v1 \
GENERATOR_MODEL=qwen3.5:2b \
  python scripts/generate_synthetic_chats.py --all --count 20
```

### Fixture format

```json
{
  "band": "teen",
  "difficulty": "ambiguous",
  "turns": [
    "omg i have so much hw tonight",
    "my teacher assigned a whole chapter"
  ],
  "notes": "clear teen cues: school homework, texting shorthand",
  "generation_model": "qwen3.5:2b",
  "seed": 1234567890
}
```

`turns` is a plain list of strings (one per chat message). `notes` is one sentence
from the generator annotating which cues were intentionally included — useful for
diagnosing misclassifications.

### Difficulty tiers

| Tier | Description | Expected pipeline behaviour |
|---|---|---|
| `clear` | Unambiguous, consistent age signals | High accuracy; band settles quickly |
| `ambiguous` | Mixed or subtle cues | Lower confidence; may not settle |
| `evasive` | Persona claims a contradictory age — true age leaks through cues | Tests `_STRONG_TYPES` fairness guard and `evasion_flag` logic |

---

## Eval harness script

`scripts/eval_pipeline_against_synthetic.py` replays each fixture through the
real production pipeline. Before construction it sets:

```
LOCAL_API_BASE  ← EVAL_API_BASE
LOCAL_MODEL     ← EVAL_MODEL
LOCAL_API_KEY   ← EVAL_API_KEY
AGEBAND_INFERENCE_MODE = llm   (forced — fixtures are designed for the LLM path)
```

This ensures the eval uses exactly the production inference code, not the offline
fallback. Using the deterministic offline estimator would give artificially clean
results on well-crafted template transcripts — not a useful signal.

### CLI

```bash
EVAL_API_BASE=http://localhost:8001/v1 \
EVAL_MODEL=Qwen/Qwen2.5-7B-Instruct \
  python scripts/eval_pipeline_against_synthetic.py

# Filter to specific band / difficulty:
EVAL_API_BASE=http://localhost:8001/v1 \
EVAL_MODEL=Qwen/Qwen2.5-7B-Instruct \
  python scripts/eval_pipeline_against_synthetic.py \
  --band child teen --difficulty clear evasive
```

### Per-fixture result fields

| Field | Type | Description |
|---|---|---|
| `ground_truth` | str | Band from the fixture file |
| `predicted` | str | Band after the final turn |
| `confidence` | float | Deterministic confidence at end of fixture |
| `difficulty` | str | `clear` / `ambiguous` / `evasive` |
| `turns_to_settle` | int \| null | 1-indexed first turn where confidence ≥ `EVAL_SETTLE_CONFIDENCE` (default 0.6) |
| `evasion_flag_raised` | bool | Whether the pipeline set `evasion_flag=True` on any turn |
| `settled` | bool | Whether the fixture settled before the last turn |
| `correct` | bool | `predicted == ground_truth` |

Every result is also fed to `AuditFairnessService.record()` under action
`"eval_result"`, using the `{session_id, action, **payload}` shape expected by
`EphemeralTrace`. This is intentionally in-process only (ephemeral).

---

## Reading the output

### Confusion matrix

```
Confusion matrix  (rows = ground truth, cols = predicted)
             child   teen  adult  unknown
  child          4      1      0        0
  teen           0      5      0        0
  adult          0      0      4        1
```

- **Diagonal** = correct classifications.
- **Off-diagonal** = confusions. `child → teen` is a false negative for child
  protection — the system under-protects. `adult → teen` is a false positive.
- **`unknown` column** = fixtures where the pipeline never accumulated enough
  evidence to settle. High counts here mean the difficulty tier is genuinely hard
  or `--turns` is too few for the pipeline to collect evidence.

### Per-band metrics

Standard precision / recall / F1 computed from the confusion matrix. **Recall on
`child` and `teen` is the safety-relevant metric**: low recall means real minors
are being missed. Prefer high recall on those bands even at the cost of some adult
false positives.

### False-positive rates by difficulty

```
By difficulty tier
  difficulty        n    error%    unsettled%  evasion_flag%
  clear            15      6.7%          0.0%          0.0%
  ambiguous        15     40.0%         53.3%          6.7%
  evasive          15     33.3%         13.3%         46.7%
```

This breakdown is the fairness-critical metric, directly motivated by the PR #2
lexical-gating fix: before `_STRONG_TYPES` was introduced, `rule_estimator`
could produce a `child`/`teen` verdict from style cues alone (vocabulary,
reading level, texting shorthand) — cues that are weakly correlated with age
and strongly correlated with demographics. A low error rate on `clear` with a
high (expected) error rate on `ambiguous`/`evasive` is the target shape.

The `evasion_flag%` column for the `evasive` tier shows how often the pipeline
correctly flagged an adversarial pattern — this should be significantly higher
for `evasive` than for `clear`.

---

## How to run

```bash
# Quick start — generate + eval in one command:
GENERATOR_API_BASE=http://localhost:11434/v1 \
GENERATOR_MODEL=<writer-model> \
EVAL_API_BASE=http://localhost:8001/v1 \
EVAL_MODEL=<eval-model> \
  make eval-synthetic

# Generate fixtures separately, then eval:
GENERATOR_API_BASE=http://localhost:11434/v1 \
GENERATOR_MODEL=<writer-model> \
  python scripts/generate_synthetic_chats.py --all --count 20

EVAL_API_BASE=http://localhost:8001/v1 \
EVAL_MODEL=<eval-model> \
  python scripts/eval_pipeline_against_synthetic.py

# Clean up fixtures and reports:
make eval-clean
```

`make eval-synthetic` generates N=20 fixtures per combination
(9 combinations = 180 total) if `tests/fixtures/synthetic/` is empty,
then runs the eval harness.

---

## Scope and constraints

| | |
|---|---|
| **Is it part of the production pipeline?** | No. The scripts are under `scripts/`, not `src/`. They are not imported by any production module. |
| **Is it wired into pytest?** | No. Both scripts call real LLM endpoints. Adding them to `pytest`/CI would make the test suite network-dependent and non-deterministic. |
| **Is it a CI gate?** | No. `make quality` does not run `eval-synthetic`. |
| **Does it modify production code?** | No. The pipeline code (`src/`) is unchanged during eval — the harness only sets env vars before constructing `OrchestrationService`. |
| **PII / data handling** | Fixtures are synthetic only — no real user data. The `notes` field contains the generator's intent annotation, not user content. |

---

## Files

| File | Contents |
|---|---|
| `scripts/generate_synthetic_chats.py` | Generator — own HTTP client, loads prompt from file, outputs fixture JSON |
| `scripts/eval_pipeline_against_synthetic.py` | Eval harness — replays pipeline, computes metrics, writes timestamped report |
| `scripts/eval_results/` | Output directory for eval reports (`<timestamp>.json`) |
| `tests/fixtures/synthetic/` | Generated fixture files (`{band}_{difficulty}_{index:03d}.json`) |
| `src/synthetic_eval/prompts/chat_generator_prompt.md` | Verbatim system prompt for the generator LLM |
