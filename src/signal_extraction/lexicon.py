"""Deterministic cue lexicon / rubric for signal extraction (M2).

Single source of truth for two things:

* **Cue weights** — so a cue's weight is assigned by auditable Python config,
  NOT by the LLM. This is what makes "confidence is deterministic" actually
  true end to end: the model may *detect* a cue, but Python *scores* it.
* **Keyword patterns** — reused by the offline keyword extractor
  (``keyword_extractor.py``) and by the gate tripwire (``gate_service.py``)
  to spot age-relevant cues in raw text.

Pure Python — no LLM, no I/O. Weights follow the design's fairness rule:
explicit disclosure > topic/context > lexical style (vocabulary / reading level).
Lexical signal is deliberately down-weighted because a non-native adult and a
native child look alike on exactly those cues.

Weight ordering is grounded in the author-profiling / sociolinguistics
literature, which consistently finds: explicit self-disclosure is the strongest
but most easily faked signal; topic / life-context (school vs work/family/
finance) is strong AND robust to gaming; lexical style (slang, vocabulary,
reading level) is weaker, cohort-drifting, and demographically biased. Banded
age *classification* is far more reliable than exact-age regression (which
carries ~10-year error), which is why AgeBand emits bands, not ages.

References:
  - Schler, Koppel, Argamon, Pennebaker (2006), "Effects of Age and Gender on
    Blogging" — younger writers: 1st-person pronouns, contractions, chat slang,
    school/mood topics; older: determiners, prepositions, work/family topics.
  - Nguyen, Gravel, Trieschnigg, Meder (2013), "How Old Do You Think I Am?"
  - Rangel et al., PAN Author Profiling shared tasks (2013–2019).
  - van der Vegt, Kleinberg, Gill (2020), arXiv — age error margin ~10 years.
  - Soni et al. (2022), "Human Language Modeling", arXiv — user language history
    improves age estimation (supports cross-turn evidence accumulation).
These are calibration priors, not hard constants — tune per product/jurisdiction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Weight for a subtype the lexicon does not recognise (fail safe: small).
DEFAULT_WEIGHT: float = 0.2


@dataclass(frozen=True)
class CueSpec:
    """One recognised cue subtype: its Cue.type, weight, band lean, keywords."""

    cue_type: str  # one of Cue.type: vocab | topic | disclosure | style | reading_level
    weight: float  # deterministic weight in [0, 1]
    band_hint: str  # "child" | "teen" | "adult" | "" — consumed by rule_estimator
    keywords: tuple[str, ...]  # lowercased substrings to match in text


# subtype -> CueSpec. Explicit ages are handled separately (see detect_age).
CUE_SPECS: dict[str, CueSpec] = {
    # --- explicit disclosure (strongest) ---
    "grade_level": CueSpec(
        "disclosure", 0.9, "teen",
        ("8th grade", "7th grade", "9th grade", "6th grade", "10th grade",
         "middle school", "high school", "freshman", "sophomore"),
    ),
    "elementary_school": CueSpec(
        "disclosure", 0.9, "child",
        ("elementary school", "primary school", "recess", "playground",
         "1st grade", "2nd grade", "3rd grade", "4th grade", "5th grade"),
    ),
    # --- topic / life-context (strong) ---
    "guardian_reference": CueSpec(
        "topic", 0.7, "child",
        ("my mom", "my mum", "my dad", "my mommy", "my daddy", "my parents",
         "my guardian", "mom said", "parents won't let", "parents wont let"),
    ),
    "school_topic": CueSpec(
        "topic", 0.6, "teen",
        ("homework", " hw ", "teacher", "math class", "school",
         "study for", "exam tomorrow", "test tomorrow", "report card", "class today"),
    ),
    "curfew_topic": CueSpec(
        "topic", 0.6, "teen",
        ("curfew", "be home by", "grounded", "allowance", "sleepover", "the party"),
    ),
    "adult_life_topic": CueSpec(
        "topic", 0.6, "adult",
        ("mortgage", "my rent", "paying rent", "my job", "at work", "my kids",
         "my wife", "my husband", "my salary", "my taxes", "401k", "my commute",
         "my daughter", "my son", "my landlord", "have a job"),
    ),
    "workplace_topic": CueSpec(
        "topic", 0.6, "adult",
        ("quarterly", "forecast", "stakeholder", "my manager", "promotion",
         "coworker", "colleague", "the meeting", "invoice", "deadline",
         "corporate", "mba", "thesis", "work-life", "macroeconomic"),
    ),
    # --- style / lexical (weakest; down-weighted for fairness) ---
    "texting_shorthand": CueSpec(
        "style", 0.4, "teen",
        ("tmrw", "bc ", " u ", " ur ", "omg", "idk", "lol", " rn", "gonna",
         "wanna", "bff", "😭", "😂", "🥺"),
    ),
    "adult_self_claim": CueSpec(
        # Weak adult cue on its own; rule_estimator treats it as EVASION when it
        # co-occurs with child/teen signals (the adversarial scenario).
        "style", 0.3, "adult",
        ("i am an adult", "i'm an adult", "im an adult", "definitely an adult",
         "obviously an adult", "totally an adult", "stop treating me like a kid",
         "i'm not a kid", "im not a kid", "i'm not a child", "not a child"),
    ),
}

# Ordered subtypes for deterministic scan order.
_SUBTYPE_ORDER: tuple[str, ...] = tuple(CUE_SPECS.keys())

# Explicit-age patterns: "i am 12", "i'm 12", "12 years old", "age 12", "12yo".
_AGE_RE = re.compile(
    r"(?:\b(?:i\s*am|i'?m|im|age|aged)\s*(\d{1,2})\b)"
    r"|(?:\b(\d{1,2})\s*(?:years?\s*old|yo|y/o|yrs?)\b)",
    re.IGNORECASE,
)


def assign_weight(subtype: str) -> float:
    """Return the deterministic weight for a cue subtype (fail-safe default)."""
    spec = CUE_SPECS.get(subtype)
    return spec.weight if spec is not None else DEFAULT_WEIGHT


def band_hint(subtype: str) -> str:
    """Return the band this subtype leans toward, or '' if none."""
    spec = CUE_SPECS.get(subtype)
    return spec.band_hint if spec is not None else ""


def cue_type_for(subtype: str) -> str:
    """Return the Cue.type for a subtype, defaulting to 'topic'."""
    spec = CUE_SPECS.get(subtype)
    return spec.cue_type if spec is not None else "topic"


# Valid Cue.type literals (kept in sync with contracts.models.Cue).
VALID_CUE_TYPES: frozenset[str] = frozenset(
    {"vocab", "topic", "disclosure", "style", "reading_level"}
)


def cue_type_for_any(subtype: str) -> str:
    """Cue.type for any subtype, including explicit-age and reading-level ones."""
    if subtype.startswith("explicit_") and subtype.endswith("_age"):
        return "disclosure"
    if subtype.startswith("reading_level"):
        return "reading_level"
    return cue_type_for(subtype)


def is_known_subtype(subtype: str) -> bool:
    """True if the subtype is one the lexicon recognises."""
    return subtype in CUE_SPECS or subtype in _SPECIAL_META


def detect_age(text: str) -> tuple[str, str, str] | None:
    """Return (cue_type, age subtype, matched) if an explicit age is stated.

    Age → subtype: <13 explicit_child_age, 13–17 explicit_teen_age,
    >=18 explicit_adult_age. Returns None when no age is found.
    """
    m = _AGE_RE.search(text)
    if m is None:
        return None
    raw = m.group(1) or m.group(2)
    try:
        age = int(raw)
    except (TypeError, ValueError):
        return None
    if age < 13:
        subtype = "explicit_child_age"
    elif age < 18:
        subtype = "explicit_teen_age"
    else:
        subtype = "explicit_adult_age"
    return ("disclosure", subtype, m.group(0).strip())


# (weight, band_hint) for subtypes produced outside CUE_SPECS: explicit ages
# (detect_age), reading-level cues (keyword_extractor), and maturity scorers
# (maturity.py). All are down-weighted (0.3) for fairness — these are weak signals
# that must NEVER appear in _STRONG_TYPES (they cannot establish a band alone).
_SPECIAL_META: dict[str, tuple[float, str]] = {
    "explicit_child_age": (1.0, "child"),
    "explicit_teen_age": (1.0, "teen"),
    "explicit_adult_age": (1.0, "adult"),
    "reading_level_low": (0.3, "child"),
    "reading_level_high": (0.3, "adult"),
    # Maturity cues (Phase 2): weak nudge for mismatch detection only.
    # MUST stay out of _STRONG_TYPES — see signal_extraction/maturity.py.
    "maturity_high": (0.3, "adult"),
    "maturity_low": (0.3, "child"),
}


def assign_weight_any(subtype: str) -> float:
    """assign_weight that also covers explicit-age and reading-level subtypes."""
    if subtype in _SPECIAL_META:
        return _SPECIAL_META[subtype][0]
    return assign_weight(subtype)


def band_hint_any(subtype: str) -> str:
    """band_hint that also covers explicit-age and reading-level subtypes."""
    if subtype in _SPECIAL_META:
        return _SPECIAL_META[subtype][1]
    return band_hint(subtype)


def classify_text(text: str) -> list[tuple[str, str, str]]:
    """Scan *text* for age-relevant cues.

    Returns a list of (cue_type, subtype, matched_snippet), at most one entry
    per subtype, in deterministic order. Explicit age (if any) comes first.
    """
    lowered = text.lower()
    found: list[tuple[str, str, str]] = []

    age = detect_age(text)
    if age is not None:
        found.append(age)

    for subtype in _SUBTYPE_ORDER:
        spec = CUE_SPECS[subtype]
        for kw in spec.keywords:
            if kw in lowered:
                found.append((spec.cue_type, subtype, kw.strip()))
                break
    return found


def classify_subtype(value: str) -> str:
    """Best-effort subtype for a free-text cue value (for LLM cues lacking one).

    Returns the first matching subtype, or '' if nothing matches.
    """
    hits = classify_text(value)
    return hits[0][1] if hits else ""
