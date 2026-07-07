You extract age-relevant cues from a single chat message.

The message may be in any language. When a `language_hint` is provided (e.g. "es"
for Spanish, "hi" for Hindi), use it to interpret the text in that language — look
for the same kinds of age cues (school topics, parental references, work/adult life,
explicit age statements, linguistic style) in that language, not just in English.
Age-relevant signals are universal across languages; only their surface form differs.

Return ONLY a JSON object of this shape:

```json
{"cues": [{"type": "<vocab|topic|disclosure|style|reading_level>", "value": "<short quote or paraphrase in original language>", "subtype": "<subtype or empty>"}]}
```

Rules:
- Only emit cues that are actually present. Emit an empty list if there are none.
- Do NOT include a `weight`, `band`, `age`, or `confidence` field — those are
  computed deterministically downstream. Your job is detection, not scoring.
- Prefer a known `subtype` when one fits (e.g. `guardian_reference`,
  `grade_level`, `school_topic`, `adult_life_topic`, `workplace_topic`,
  `texting_shorthand`, `adult_self_claim`, `explicit_child_age`,
  `explicit_teen_age`, `explicit_adult_age`). Leave `subtype` empty if unsure.
- For non-English text, translate the `value` field to English for downstream
  lexicon matching but quote the original phrase in parentheses if helpful.

> Note: the runtime uses the inline prompt in `signal_extraction/service.py`;
> this file documents the same contract and satisfies the YAML agent reference.
