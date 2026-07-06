# Module: `signal_extraction` — Age-Relevant Signal Extractor (M2)

**Package:** `src/signal_extraction/`  
**Phase:** B (parallel)  
**LLM calls:** Optional — one structured pass via LLM **or** deterministic offline fallback  
**Protocol:** `ISignalExtractor`

---

## Purpose

Signal extraction is the **first LLM step** in the pipeline. Given the raw text of a user turn, it produces a `SignalSet` — a list of typed, weighted `Cue` objects that represent age-relevant signals. It also computes a deterministic Flesch-Kincaid reading level as a no-LLM pre-signal.

---

## Files

| File | Contents |
|---|---|
| `service.py` | `SignalExtractorService` — LLM path or offline fallback; re-stamps weights from lexicon |
| `lexicon.py` | **Deterministic cue lexicon** — single source of truth for cue weights, subtypes, and band hints |
| `keyword_extractor.py` | **Offline keyword extractor** — deterministic M2 path; no LLM required |
| `reading_level.py` | Deterministic Flesch-Kincaid reading level calculator |
| `tool.py` | `@function_tool` wrapper for the planner |
| `signal_extractor.yaml` | tinyagent YAML config for the `signal_extractor` delegate |
| `prompts/signal_extractor_prompt.md` | LLM system prompt (modular prompt file) |

---

## Signal Types

| Type | Description | Example |
|---|---|---|
| `vocab` | Vocabulary complexity or simplicity | "sophisticated technical terminology" |
| `topic` | Subject matter with age relevance | "school homework", "mortgage refinancing" |
| `disclosure` | Explicit self-disclosure of age or life stage | "I'm 12 years old", "I'm in 8th grade" |
| `style` | Writing style features | "all lowercase, emoji-heavy", "formal prose" |
| `reading_level` | Flesch-Kincaid grade level | computed deterministically, not by LLM |

Each cue carries:
- `weight` in `[0.0, 1.0]` — **always assigned by the lexicon, never by the LLM**
- `subtype` (optional string, e.g. `guardian_reference`, `adult_self_claim`) — drives the lexicon weight lookup; LLM/offline-detected cues include it; legacy cues default to `""`

---

## Deterministic Cue Lexicon (`lexicon.py`)

`lexicon.py` is the **single source of truth for cue weights**. It replaces ad-hoc or LLM-assigned weights with a grounded, auditable mapping:

- Weight hierarchy: **disclosure > topic/context > lexical style** — grounded in author-profiling literature (Schler 2006; Nguyen 2013; PAN; van der Vegt 2020)
- Lexical/reading-level signals are **down-weighted** for fairness and empirical accuracy (demographics correlate with these, not age alone)
- Provides `classify_text(text)` — keyword scan returning `(type, subtype, matched_token)` triples
- Provides `band_hint_any(subtype)` — maps a subtype to `"child"`, `"teen"`, `"adult"`, or `""`
- Provides `assign_weight_any(subtype)` — canonical weight for a subtype

**Whatever the source of cues (LLM or keyword extractor), weights are always re-stamped from the lexicon in `service.py`.** The model detects; Python scores.

---

## Offline Keyword Extractor (`keyword_extractor.py`)

`keyword_extractor.py` is the **deterministic M2 fallback** — it produces a `SignalSet` from plain keyword matching when no LLM endpoint is configured:

```python
def extract_cues(text: str) -> SignalSet:
    """Keyword-scan a turn text and return lexicon-weighted cues."""
```

Used automatically when `AGEBAND_INFERENCE_MODE=deterministic` or when `LOCAL_MODEL` is unset (auto mode). This is what makes the demo pipeline runnable without a GPU.

---

## Inference Mode Selection

`service.py` selects the extraction path via `src/contracts/runtime.use_llm()`:

| `AGEBAND_INFERENCE_MODE` | Path |
|---|---|
| `deterministic` | `keyword_extractor` always |
| `llm` | LLM endpoint always |
| `auto` (default) | LLM when `LOCAL_MODEL` is set, else `keyword_extractor` |

In all cases, weights are **re-stamped from the lexicon** after extraction.

---

## Reading Level (Deterministic)

`reading_level.py` computes the Flesch-Kincaid Grade Level formula:

```
FKGL = 0.39 × (words/sentences) + 11.8 × (syllables/words) − 15.59
```

This runs before the LLM call and injects a `reading_level` cue into the SignalSet without any model involvement — a pure deterministic signal.

---

## tinyagent Configuration

`signal_extractor.yaml` configures the delegate agent:

- **Output type:** `SignalSet` (Pydantic-validated on return)
- **Input filter:** `compress` — passes only the current turn text, not full session history
- **Prompt:** `prompts/signal_extractor_prompt.md`

The LLM is explicitly instructed to:
1. Return only the listed cue types
2. Not infer or output confidence scores
3. Set weight based on signal strength, not certainty about the band

---

## Interface

```python
class ISignalExtractor(Protocol):
    async def extract(self, turn: TurnEvent) -> SignalSet: ...
```

**Input:** `TurnEvent`  
**Output:** `SignalSet(cues=[Cue(...), ...])`

---

## Tests

```
tests/unit/signal_extraction/test_reading_level.py      — FK formula, edge cases
tests/unit/signal_extraction/test_lexicon.py             — weight assignments, band hints, subtype mapping
tests/unit/signal_extraction/test_keyword_extractor.py  — offline extraction, cue coverage
tests/unit/signal_extraction/test_service.py             — weight re-stamping, LLM mocked, offline path
```
