# AgeBand — Backend comparison & research grounding

How the three inference backends behave on the four demo transcripts, why the
lexicon weights are set the way they are, and how AgeBand compares to commercial
age-assurance products.

## Backends

AgeBand's LLM delegates (signal extraction M2, age-band inference M4) run against
whatever `LOCAL_MODEL` / `LOCAL_API_BASE` point at, or fall back to a fully
deterministic path when no endpoint is configured. Switch with one env var:

```bash
# Deterministic (no GPU, no model) — the offline default
AGEBAND_INFERENCE_MODE=deterministic

# Local model via Ollama
AGEBAND_INFERENCE_MODE=llm LOCAL_API_BASE=http://localhost:11434/v1 LOCAL_MODEL=llama3.2:3b
```

Reproduce the table below:

```bash
ollama pull llama3.2:3b        # or gemma2:9b, llama3.1:8b, etc.
python scripts/compare_backends.py llama3.2:3b gemma4:31b
```

## Results (final turn of each scenario)

| scenario | deterministic | llama3.2:3b | gemma4:31b |
|---|---|---|---|
| clear_adult | adult · c=0.60 · standard | adult · c=0.58 · standard | adult · c=0.46 · standard |
| young_teen | teen · c=0.98 · **restricted** | teen · c=0.27 · caution | teen · c=0.68 · **restricted** |
| ambiguous_adult | child · c=0.16 · caution | teen · c=0.28 · caution | **unknown · c=0.00 · standard** |
| adversarial | teen · c=0.51 · **restricted** | teen · c=0.36 · caution | **adult · c=0.86 · standard** ⚠️ |

Regardless of backend, **Python assigns cue weights (from the lexicon) and
computes confidence** — the model only detects cues and proposes a band.

## What the comparison shows

- **The deterministic layer is load-bearing.** On the adversarial transcript (a
  child insisting "I'm 25"), `gemma4:31b` was **fooled — adult, 0.86, wide-open
  posture** — even though its prompt explicitly said not to trust a self-claim
  against child cues. The deterministic evasion rule refused to conclude adult.
  This is the design thesis ("the careful shell is the point") shown empirically.
- **Bigger model wins on nuance.** On `ambiguous_adult` (an adult writing
  simply), `gemma4:31b` correctly **abstained (`unknown`)** rather than
  tightening — the fairest outcome. The deterministic rubric slightly
  over-tightens (child/caution).
- **Small models under-extract.** `llama3.2:3b` produced weak, low-confidence
  signals and blurred the teen case.
- **Conclusion → hybrid.** LLM proposes (nuance, abstention) + deterministic
  evasion-guard & weighting (robust to gaming) beats either alone. That *is* the
  architecture: model estimates, Python decides.

> Robustness note: one `gemma4:31b` extraction call returned unparseable JSON and
> **failed closed** (safe default posture) — correct behaviour; a bounded retry
> is a reasonable follow-up.

## Why the lexicon weights are set as they are (research grounding)

Weight ordering — **explicit disclosure > topic/life-context > lexical style
(vocab/reading-level)** — follows the author-profiling / sociolinguistics
literature:

- **Schler, Koppel, Argamon, Pennebaker (2006)**, *Effects of Age and Gender on
  Blogging* — younger writers: 1st-person pronouns, contractions, chat slang,
  school/mood topics; older: determiners, prepositions, work/family topics.
- **Nguyen et al. (2013)**, *How Old Do You Think I Am?*
- **Rangel et al.**, PAN Author Profiling shared tasks (2013–2019).
- **van der Vegt, Kleinberg, Gill (2020)** — age prediction carries **~10-year
  error**, so banded classification (not exact age) is the honest output.
- **Soni et al. (2022)**, *Human Language Modeling* — user language *history*
  improves age estimation, supporting cross-turn evidence accumulation.

Two consequences baked into the code:
1. **Lexical/reading-level cues are down-weighted (0.3)** — not just for fairness
   but because they are empirically weak and biased (a non-native adult ≈ a
   native child on exactly these cues; ±10yr regression error).
2. **Bands, not ages**, with deterministic confidence — because exact-age
   prediction from text is unreliable and LLM self-reported confidence is
   uncalibrated.

Weights are calibration priors, not constants — tune per product/jurisdiction.

## Competitive landscape

| | Method | Passive | Continuous | Deployment | Stores |
|---|---|---|---|---|---|
| **Yoti** | Facial age estimation (selfie), ID docs, email-age. 99.3% TPR (13–17→under-21) | ❌ needs selfie/doc | ❌ one-time gate | Cloud / on-device | results only |
| **k-ID** | Age classification + active verification (facial/ID/tokens) + parental consent, jurisdiction-driven | ❌ verification touchpoints | ❌ at signup/gate | Cloud (+on-device model) | tokens |
| **AgeBand** | Passive text-based band inference from the conversation | ✅ no user action | ✅ **every turn** (tripwire) | **On-prem / first-party** | **nothing (ephemeral)** |

**For the age-*gating decision*, biometric products (Yoti) are more accurate and
are the certified/legal assurance path — we don't claim to beat them there.**
AgeBand's edge is coverage and deployment: zero friction, always-on, catches
mid-session hand-offs, no biometric capture, on-prem text. The credible framing
is **complementary**: AgeBand is the continuous, cheap risk detector that decides
*when* to invoke a high-assurance check — and **step-up can route to a Yoti/k-ID
flow**. Cheap smoke detector → expensive sprinkler.
