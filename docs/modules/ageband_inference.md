# Module: `ageband_inference` — Age Band Estimator (M4)

**Package:** `src/ageband_inference/`  
**Phase:** B (parallel)  
**LLM calls:** Yes — one structured pass via tinyagent delegate  
**Protocol:** `IAgeBandInference`

---

## Purpose

AgeBand Inference is the **core reasoning module**. An LLM reads the accumulated evidence and proposes an age band. A deterministic Python function then computes confidence from the evidence — the LLM **never** outputs a confidence value.

> **Load-bearing invariant:** The LLM proposes; Python decides. Confidence is always deterministic.

---

## Files

| File | Contents |
|---|---|
| `service.py` | `AgeBandInferenceService` — delegates to LLM, validates output |
| `confidence.py` | Deterministic `compute_confidence()` — no LLM involvement |
| `config.py` | Env-configurable weights and penalties |
| `tool.py` | `@function_tool` wrapper (`compute_confidence_tool`) |
| `ageband_estimator.yaml` | tinyagent YAML for the `ageband_estimator` delegate |
| `prompts/ageband_estimator_prompt.md` | LLM system prompt |

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
tests/unit/ageband_inference/test_confidence.py  — formula, penalties, edge cases
tests/unit/ageband_inference/test_service.py     — LLM mocked, output validation, evasion
```
