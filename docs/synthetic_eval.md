# Synthetic Evaluation Harness

## Overview

The synthetic eval harness lets you measure AgeBand's age-band inference
accuracy without needing a labelled real-user dataset.  Two scripts work
together:

| Script | Role |
|---|---|
| `scripts/generate_synthetic_chats.py` | Generate `{band, difficulty, turns}` fixture JSON files |
| `scripts/eval_pipeline_against_synthetic.py` | Replay fixtures through the real pipeline and compute metrics |

Generated fixtures live in `tests/fixtures/synthetic/` but are **not** run
by `pytest` — this harness calls real LLM endpoints and is a manual eval
tool, not a CI gate.

---

## Quick start (offline, no GPU required)

```bash
# 1. Generate 5 fixtures per band (child/teen/adult) × difficulty (clear/ambiguous/evasive)
#    using built-in template transcripts — no LLM needed.
python scripts/generate_synthetic_chats.py --template --count 5

# 2. Evaluate with the deterministic offline pipeline (rule_estimator + keyword_extractor).
AGEBAND_INFERENCE_MODE=deterministic \
  python scripts/eval_pipeline_against_synthetic.py

# Or via Make:
make eval-synthetic
```

## Quick start (LLM-backed)

```bash
# LLM generation + LLM eval — two distinct models served from the same endpoint.
GENERATOR_MODEL=qwen3.5:2b \
EVAL_MODEL=qwen3.5:2b \
AGEBAND_INFERENCE_MODE=llm \
  python scripts/generate_synthetic_chats.py --count 20
  python scripts/eval_pipeline_against_synthetic.py

# Or via Make (set GENERATOR_MODEL and EVAL_MODEL first):
make eval-synthetic-llm GENERATOR_MODEL=qwen3.5:2b EVAL_MODEL=qwen3.5:397b-cloud
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `GENERATOR_MODEL` | (required in LLM mode) | Model used to *generate* transcripts. Should differ from `EVAL_MODEL` to avoid train-test contamination. |
| `EVAL_MODEL` | (required in LLM mode) | Model used for *inference* during eval. Passed to `LOCAL_MODEL` inside the pipeline. |
| `LOCAL_API_BASE` | `http://localhost:11434/v1` | OpenAI-compatible API base URL (Ollama / vLLM). |
| `LOCAL_API_KEY` | `EMPTY` | Bearer token for the API. |
| `AGEBAND_INFERENCE_MODE` | `llm` | `'llm'` uses the LLM estimator; `'deterministic'` (or `'offline'`) uses the deterministic `rule_estimator` with no network calls. |
| `EVAL_SETTLE_CONFIDENCE` | `0.6` | Minimum confidence to count a band as "settled" in `turns_to_settle` tracking. |
| `SKIP_AMD_CHECK` | `true` | Automatically set to `true` by the eval script — skips the vLLM ROCm startup check. |

### Why two separate models?

Using the same model for both generation and evaluation risks **train-test
leakage**: the generator's phrasing echoes back through the same model's
learned patterns and inflates accuracy.  Deliberately pairing a small fast
model for generation (`GENERATOR_MODEL=qwen3.5:2b`) with a larger one for
evaluation (`EVAL_MODEL=qwen3.5:397b-cloud`) gives a more realistic picture
of generalisation.

---

## Difficulty tiers

| Tier | Description | Expected behaviour |
|---|---|---|
| `clear` | Strong, unambiguous age signals in every turn | High accuracy; band settles quickly |
| `ambiguous` | Deliberately neutral topics, mixed cues | Lower confidence; may not settle |
| `evasive` | Persona *claims* contradictory age — true age leaks through linguistic cues | Tests the `_STRONG_TYPES` fairness guard and evasion-flag logic |

---

## Generation modes

### LLM mode (default)

Calls `GENERATOR_MODEL` via `LOCAL_API_BASE` (OpenAI-compatible) to produce
varied, natural-sounding transcripts.  The generator temporarily overrides
`LOCAL_MODEL` while each transcript is being produced; `EVAL_MODEL` is
restored before the evaluation phase.

```bash
python scripts/generate_synthetic_chats.py \
  --band child teen adult \
  --difficulty clear ambiguous evasive \
  --count 20 \
  --turns 5 \
  --seed 42
```

### Template mode (`--template`)

Uses hard-coded transcripts built from lexicon keywords — no LLM, no
network call.  Each (band, difficulty) combination has six variants; the
script cycles through them when `--count` exceeds six.

Template mode is the default for `make eval-synthetic` so the harness works
end-to-end without a running GPU/Ollama instance (useful for local dev and
CI dry-runs).

---

## Output files

| File | Contents |
|---|---|
| `tests/fixtures/synthetic/{band}_{difficulty}_{index:03d}.json` | One fixture: `{band, difficulty, turns, generation_model, seed}` |
| `eval_report.json` | Full report: metrics + raw per-sample results |
| `eval_report_llm.json` | Separate report produced by `make eval-synthetic-llm` |

---

## Reading the confusion matrix

```
Confusion matrix  (rows = ground truth, cols = predicted)
              child       teen      adult    unknown
     child        4          1          0          0
      teen        0          5          0          0
     adult        0          0          4          1
```

* **Diagonal** = correct classifications.
* **Off-diagonal** = band confusions.  `child → teen` is a *false negative
  for child protection* — the system under-protects.  `adult → teen` is a
  false positive.
* **`unknown` column** = fixtures where the pipeline never accumulated
  enough evidence to settle above `EVAL_SETTLE_CONFIDENCE`.  High counts
  here mean the difficulty tier is genuinely hard or `--turns` is too low.

### Per-band metrics

Standard precision / recall / F1 computed from the confusion matrix.

> **Recall** for `child` and `teen` is the safety-relevant metric: low
> recall means real minors are being missed (under-protection).  Prefer
> high recall on those bands even at the cost of some adult false positives.

### Error rates by difficulty

```
Error rates by difficulty tier
  difficulty         n    error%  unsettled%
  ambiguous         15    40.0%       53.3%
  clear             15     6.7%        0.0%
  evasive           15    33.3%       13.3%
```

`error%` = fraction of fixtures where `predicted != ground_truth`.
`unsettled%` = fraction where confidence never reached `EVAL_SETTLE_CONFIDENCE`.

---

## AMD / vLLM utilisation demo

Running `make eval-synthetic-llm` with two different models loads **two
distinct models concurrently** off the same ROCm endpoint (assuming vLLM
is configured with enough VRAM for multi-tenancy or you swap between
requests).  This makes the harness a natural demo of the AMD GPU serving
capability: generation requests go to `GENERATOR_MODEL` and evaluation
requests to `EVAL_MODEL` in interleaved async calls.

To demonstrate this on a single ROCm node:

```bash
# Start vLLM serving two models (or use Ollama which handles this automatically):
vllm serve qwen/Qwen2.5-7B-Instruct --port 8001 &
vllm serve qwen/Qwen2.5-72B-Instruct --port 8002 &

# Point generator at the smaller model, evaluator at the larger:
LOCAL_API_BASE=http://localhost:8001/v1 \
GENERATOR_MODEL=Qwen/Qwen2.5-7B-Instruct \
python scripts/generate_synthetic_chats.py --count 20

LOCAL_API_BASE=http://localhost:8002/v1 \
EVAL_MODEL=Qwen/Qwen2.5-72B-Instruct \
AGEBAND_INFERENCE_MODE=llm \
python scripts/eval_pipeline_against_synthetic.py
```

---

## Audit trace integration

Every evaluated sample is written to the in-process `AuditFairnessService`
trace under action `"eval_result"`.  The payload shape matches the
`{session_id, action, **payload}` contract expected by `EphemeralTrace`:

```python
{
    "session_id": "eval-<12-char uuid>",
    "action": "eval_result",
    "ground_truth": "teen",
    "predicted": "teen",
    "confidence": 0.72,
    "difficulty": "clear",
    "turns_to_settle": 3,
    "settled": true,
    "correct": true
}
```

This is intentionally ephemeral (in-process only).  To persist audit records
swap the `_trace` backend in `src/audit_fairness/trace.py` for a durable
adapter without touching the eval script.

---

## Makefile targets

| Target | Description |
|---|---|
| `make eval-synthetic` | Template generation + offline eval (no LLM) |
| `make eval-synthetic-llm` | LLM generation + LLM eval |
| `make eval-clean` | Remove `tests/fixtures/synthetic/` and report files |

Override `EVAL_N` (default 20), `GENERATOR_MODEL`, and `EVAL_MODEL` on the
command line:

```bash
make eval-synthetic-llm EVAL_N=50 GENERATOR_MODEL=qwen3.5:2b EVAL_MODEL=qwen3.5:2b
```
