# Module: `ageband_inference` — Age Band Estimator (M4)

**Package:** `src/ageband_inference/`  
**Phase:** B (parallel)  
**LLM calls:** Optional — one structured pass via LLM **or** deterministic offline fallback  
**Protocol:** `IAgeBandInference`

---

## Purpose

AgeBand Inference is the **core reasoning module**. An LLM reads the accumulated evidence and proposes an age band. A deterministic Python function then computes confidence from the evidence — the LLM **never** outputs a confidence value.

> **Load-bearing invariant:** The LLM proposes; Python decides. Confidence is always deterministic.

---

## Files

| File | Contents |
|---|---|
| `service.py` | `AgeBandInferenceService` — LLM path or offline fallback; strips confidence from LLM output |
| `rule_estimator.py` | **Deterministic offline estimator** — tallies lexicon band scores without LLM |
| `confidence.py` | Deterministic `compute_confidence()` — no LLM involvement |
| `config.py` | Env-configurable weights and penalties |
| `tool.py` | `@function_tool` wrapper (`compute_confidence_tool`) |
| `ageband_estimator.yaml` | tinyagent YAML for the `ageband_estimator` delegate |
| `prompts/ageband_estimator_prompt.md` | LLM system prompt |

---

## Model Selection for the M4 Delegate

The estimator uses `ESTIMATOR_MODEL` (via `contracts/llm_client.estimator_model()`) when making LLM calls, falling back to `LOCAL_MODEL` when that variable is unset:

```
ESTIMATOR_MODEL=google/gemma-3-27b-it  # explicit per-delegate override
LOCAL_MODEL=google/gemma-3-4b-it       # fallback when ESTIMATOR_MODEL is empty
```

**Rationale:** `model_comparison.md` shows that larger models (gemma4:31b) correctly **abstain on `ambiguous_adult`** (the fairness-critical scenario) where smaller models over-tighten. The estimator — which makes the multi-turn, reasoning-rich band judgment — gets the larger model. The lower-cost extractor (M2) uses the smaller model; see `signal_extraction.md`. Both models are served from the same `LOCAL_API_BASE` endpoint.

Single-model deployments leave `ESTIMATOR_MODEL` empty; `complete_json()` falls back to `LOCAL_MODEL`.

---

## Offline Rule Estimator (`rule_estimator.py`)

`rule_estimator.py` is the **deterministic M4 fallback** — it produces an `AgeBandEstimate` from accumulated evidence without any LLM call. Used when `AGEBAND_INFERENCE_MODE=deterministic` or when no model endpoint is configured.

### Lexical cue gating (fairness fix — PR #2)

`rule_estimator` enforces a **topic/disclosure requirement** before establishing any age band:

```python
# Imported from src.contracts.models (Phase 11 boundary fix — no longer defined here)
from src.contracts.models import STRONG_CUE_TYPES as _STRONG_TYPES
# STRONG_CUE_TYPES = frozenset({"disclosure", "topic"})
# Only cues of these types can establish a band.
# Lexical cues (vocab, style, reading_level) are EXCLUDED entirely.
```

**Why:** lexical signals (short sentences, simple vocabulary, low reading level) are the weakest age indicators and the most demographically biased — a non-native speaker, a neurodivergent user, or anyone who writes tersely scores identically to a child on these signals. Replaying a real 35-user Discord logistics channel, **33/35 adults were mislabeled `child`** purely from `reading_level_low` (short/terse messages read as "simple"). After this guard the same channel yields **all `unknown` / `standard` — zero false positives**, matching the system's fairness promise.

**Behaviour:** if the only evidence is lexical (vocab/style/reading_level), `_decide_band` returns `"unknown"` regardless of how many cues are present. A `topic` or `disclosure` cue is required to move the band off `unknown`.

This guard applies to the **offline path only**. The LLM estimator path is not constrained by `_STRONG_TYPES` — the LLM sees all cue types and applies its own holistic reasoning. The downstream `confidence.py` formula applies equally to both paths.

> **Architecture note:** `_STRONG_TYPES` / `STRONG_CUE_TYPES` was moved from `rule_estimator.py` to `contracts/models.py` during the Phase 11 conformance audit to remove an M2 (`signal_extraction/maturity.py`) → M4 (`ageband_inference`) cross-module dependency. `rule_estimator.py` re-exports `STRONG_CUE_TYPES as _STRONG_TYPES` for backward compatibility.

### Algorithm
1. For each `Cue` in the `EvidenceSummary`, look up its `subtype` (or derive via `lexicon.classify_subtype`)
2. Map the subtype to a band hint (`child`, `teen`, `adult`) via `lexicon.band_hint_any`
3. Accumulate weighted scores only for `disclosure`/`topic` cues — lexical cues are logged but not tallied
4. **Adversarial evasion guard (Phase 4 — 4 masking patterns):** Detects and flags up to four masking patterns; `evasion_flag=True` is set when any fire. See §Masking Patterns below.
5. Pick the dominant band from strong scores; fall back to `"unknown"` when no strong signal exists

Like the LLM path, `rule_estimator` **never emits a confidence value** — confidence is always computed deterministically in `confidence.py`.

---

## Masking / Evasion Detector (Phase 4 — 4 patterns)

`rule_estimator._detect_masking_patterns()` detects up to four evasion strategies:

| Pattern | Description |
|---|---|
| `mismatch` | Adult self-claim present while child/teen cues dominate — the original rule, unchanged semantics |
| `deflection` | User explicitly denies being young or protests age questions ("why do you keep asking") |
| `register_switching` | Band history shows sudden flip from young-leaning to adult-leaning after ≥ 3 turns |
| `over_insistence` | ≥ 2 adult self-claim cues — repeated, escalating unprompted age claims |

**Strict superset:** every case that previously triggered `evasion_flag=True` still does so via the `mismatch` pattern. The three new patterns only add detection.

`AgeBandEstimate.evasion_patterns: list[str]` carries which patterns fired.
The LLM estimator path (`service.py`) also detects all four via prompt instructions.

---

## Conversation-Level Uncertainty Penalty (Phase 3)

`confidence._compute_uncertainty()` adds a deterministic penalty for multi-turn
signal noise. Five factors, each a small nudge:

| Factor | Trigger | Penalty |
|---|---|---|
| Conflict | `band_history` contains 2+ different non-unknown bands | `UNCERTAINTY_CONFLICT_PENALTY` (0.08) |
| Volatility | ≥ 3 band flips across history | `UNCERTAINTY_VOLATILITY_PENALTY` (0.08) |
| Maturity mismatch | Maturity cue disagrees with candidate band | `UNCERTAINTY_MATURITY_MISMATCH_PENALTY` (0.05) |
| Sparsity | `turn_count < MIN_TURNS_FOR_CONFIDENCE` (3) | `UNCERTAINTY_SPARSITY_PENALTY` (0.05) |
| Embedding drift | `embedding_similarity < EMBEDDING_DRIFT_THRESHOLD` (0.65) | `UNCERTAINTY_EMBEDDING_DRIFT_PENALTY` (0.05) |

**Hard requirement:** penalty = exactly 0.0 when `band_history` is empty (single-turn, offline).
**Total cap:** `MAX_UNCERTAINTY_PENALTY` (0.20) — cannot drive confidence negative alone.

The embedding drift factor (Phase 5) is a no-op when `EMBEDDING_MODEL` is unset.

---

## Guided Decoding (Phase 5)

When `GUIDED_DECODING_ENABLED=1`, `service._call_estimator()` passes
`_ESTIMATOR_JSON_SCHEMA` to `complete_json(json_schema=...)`. This constrains
the vLLM model output to the exact JSON schema shape (band enum, evasion_patterns
enum, no confidence key, `additionalProperties: false`), eliminating the need for
`_sanitise_estimate()` fallback parsing on clean GPU runs.

**Schema key:** `confidence` is **absent** from `_ESTIMATOR_JSON_SCHEMA`.
Attempting to add it would fail the schema's `additionalProperties: false` constraint.

Requires vLLM ≥ 0.4.0 with `--guided-decoding-backend lm-format-enforcer`.
Leave `GUIDED_DECODING_ENABLED` empty for Ollama or endpoints without guided decoding.

---

## Embedding Consistency (Phase 5)

When `EMBEDDING_MODEL` is set, each turn's text is embedded and compared to the
session centroid via `contracts/embeddings_client.update_session_similarity()`.
The cosine similarity score is stored in `EvidenceSummary.embedding_similarity`
and feeds into the uncertainty penalty Factor 5 above.

**No-op offline:** `embedding_similarity = None` contributes zero penalty.

---

## LLM Step: Band Estimation

`ageband_estimator.yaml` configures a delegate agent that:

1. Reads the `EvidenceSummary` (cues accumulated so far)
2. Proposes a `band`: `child | teen | adult | unknown`
3. Lists `cited_cues` — the evidence that drove the estimate
4. Sets `evasion_flag: true` if the user appears to be avoiding age-revealing signals
5. Lists `contradictions` — inconsistencies in the evidence

The LLM prompt explicitly **prohibits** outputting any confidence, probability, certainty, or score. The output is validated by `validate_ageband_estimate()` before use — any response containing confidence-like keys raises a `ValidationError`.

---

## Deterministic Confidence Formula

```python
base      = evidence.corroboration_score × CORROBORATION_WEIGHT      # default 0.6
cue_bonus = min(len(cited_cues), MAX_CITED_CUES_BONUS) 
            / MAX_CITED_CUES_BONUS × CITED_CUES_WEIGHT               # default 0.4

raw = base + cue_bonus

penalty = 0.0
if evasion_flag:
    penalty += EVASION_PENALTY                                        # default 0.15
penalty += min(len(contradictions), 3) × CONTRADICTION_PENALTY       # default 0.10 each

confidence = max(0.0, min(raw − penalty, 1.0))
```

**Special case:** If `corroboration_score == 0.0` and `cited_cues` is empty, confidence is always `0.0` regardless of other fields.

### Confidence thresholds (consumed by M5)

| Range | Bucket |
|---|---|
| 0.0 – 0.39 | `low` |
| 0.40 – 0.69 | `medium` |
| 0.70 – 1.00 | `high` |

### Worked example

5 cues × weight 0.95:
```
corroboration_score = (5 × 0.95) / 5.0 = 0.95
base      = 0.95 × 0.6 = 0.57
cue_bonus = 5/5 × 0.4  = 0.40
raw       = 0.97
penalties = 0
confidence = 0.97  →  bucket: "high"
```

2 cues × weight 0.95 (adversarial, evasion=True):
```
corroboration_score = (2 × 0.95) / 5.0 = 0.38
base      = 0.38 × 0.6 = 0.228
cue_bonus = 2/5 × 0.4  = 0.16
raw       = 0.388
evasion   = −0.15
confidence = 0.238  →  bucket: "low"
```

---

## Configuration

| Env var | Default | Description |
|---|---|---|
| `INFERENCE_CORROBORATION_WEIGHT` | `0.6` | Contribution of evidence corroboration |
| `INFERENCE_CITED_CUES_WEIGHT` | `0.4` | Contribution of cited cues count |
| `INFERENCE_MAX_CITED_CUES_BONUS` | `5` | Cue count at which cue_bonus saturates |
| `INFERENCE_EVASION_PENALTY` | `0.15` | Confidence reduction when evasion detected |
| `INFERENCE_CONTRADICTION_PENALTY` | `0.10` | Per-contradiction penalty (max 3 counted) |
| `INFERENCE_UNCERTAINTY_CONFLICT_PENALTY` | `0.08` | Uncertainty: conflicting leans in band_history |
| `INFERENCE_UNCERTAINTY_VOLATILITY_PENALTY` | `0.08` | Uncertainty: band flip count ≥ 3 |
| `INFERENCE_UNCERTAINTY_MATURITY_MISMATCH_PENALTY` | `0.05` | Uncertainty: maturity cue disagrees with band |
| `INFERENCE_UNCERTAINTY_SPARSITY_PENALTY` | `0.05` | Uncertainty: fewer than MIN_TURNS turns |
| `INFERENCE_MIN_TURNS_FOR_CONFIDENCE` | `3` | Turn threshold below which sparsity applies |
| `INFERENCE_MAX_UNCERTAINTY_PENALTY` | `0.20` | Hard cap on total uncertainty penalty |
| `INFERENCE_EMBEDDING_DRIFT_THRESHOLD` | `0.65` | Cosine similarity threshold for drift penalty |
| `INFERENCE_UNCERTAINTY_EMBEDDING_DRIFT_PENALTY` | `0.05` | Uncertainty: embedding drift (Phase 5) |
| `GUIDED_DECODING_ENABLED` | `` | `1` to pass JSON schema to vLLM (requires vLLM ≥ 0.4.0) |
| `ESTIMATOR_MODEL` | `` | Model ID for M4 delegate (falls back to `LOCAL_MODEL`) |

---

## Interface

```python
class IAgeBandInference(Protocol):
    async def estimate(self, evidence: EvidenceSummary) -> AgeBandEstimate: ...
```

`compute_confidence` is a standalone function consumed directly by the orchestration runner:

```python
def compute_confidence(evidence: EvidenceSummary, estimate: AgeBandEstimate) -> float: ...
```

---

## Tests

```
tests/unit/ageband_inference/test_confidence.py           — formula, penalties, edge cases
tests/unit/ageband_inference/test_rule_estimator.py       — offline estimation, adversarial evasion guard
tests/unit/ageband_inference/test_service.py              — LLM mocked, output validation, offline path
tests/unit/ageband_inference/test_uncertainty_penalty.py  — 5-factor uncertainty penalty; 0.0 on all single-turn fixtures
tests/unit/ageband_inference/test_masking_patterns.py     — all 4 masking patterns; superset regression
tests/unit/ageband_inference/test_guided_decoding.py      — JSON schema confidence exclusion; guided decoding toggle
```
