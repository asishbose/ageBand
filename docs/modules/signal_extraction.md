# Module: `signal_extraction` — Age-Relevant Signal Extractor (M2)

**Package:** `src/signal_extraction/`  
**Phase:** B (parallel)  
**LLM calls:** Yes — one structured pass per turn via tinyagent delegate  
**Protocol:** `ISignalExtractor`

---

## Purpose

Signal extraction is the **first LLM step** in the pipeline. Given the raw text of a user turn, it produces a `SignalSet` — a list of typed, weighted `Cue` objects that represent age-relevant signals. It also computes a deterministic Flesch-Kincaid reading level as a no-LLM pre-signal.

---

## Files

| File | Contents |
|---|---|
| `service.py` | `SignalExtractionService` — delegates to the tinyagent LLM |
| `reading_level.py` | Deterministic Flesch-Kincaid reading level calculator |
| `tool.py` | `@function_tool` wrapper for the planner |
| `signal_extractor.yaml` | tinyagent YAML config for the `signal_extractor` delegate |
| `prompts/signal_extractor_prompt.md` | LLM system prompt (modular prompt file) |

---

## Signal Types

The LLM is instructed to extract cues of these types only:

| Type | Description | Example |
|---|---|---|
| `vocab` | Vocabulary complexity or simplicity | "sophisticated technical terminology" |
| `topic` | Subject matter with age relevance | "school homework", "mortgage refinancing" |
| `disclosure` | Explicit self-disclosure of age or life stage | "I'm 12 years old", "I'm in 8th grade" |
| `style` | Writing style features | "all lowercase, emoji-heavy", "formal prose" |
| `reading_level` | Flesch-Kincaid grade level | computed deterministically, not by LLM |

Each cue carries a `weight` in `[0.0, 1.0]` representing signal strength.

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
tests/unit/signal_extraction/test_reading_level.py   — FK formula, edge cases
tests/unit/signal_extraction/test_service.py          — LLM mocked, output validation
```
