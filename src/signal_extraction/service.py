"""SignalExtractorService — M2 LLM-backed signal extraction.

Delegates to the signal_extractor YAML agent for the one LLM pass,
then validates raw output as a SignalSet (Pydantic extra="forbid").

In unit tests pass `_mock_response: dict | None` to bypass tinyagent.
"""

from __future__ import annotations

import logging

from src.contracts.models import SignalSet, TurnEvent
from src.contracts.protocols import ISignalExtractor
from src.contracts.runtime import use_llm
from src.signal_extraction import lexicon
from src.signal_extraction.keyword_extractor import extract_cues

logger = logging.getLogger(__name__)

_YAML_AGENT_PATH = "src/signal_extraction/signal_extractor.yaml"

_VALID_SUBTYPES = ", ".join(sorted(lexicon.CUE_SPECS)) + (
    ", explicit_child_age, explicit_teen_age, explicit_adult_age"
)

_SYSTEM_PROMPT = (
    "You extract age-relevant cues from a single chat message. "
    "Return ONLY JSON: {\"cues\": [{\"type\": <one of vocab|topic|disclosure|"
    "style|reading_level>, \"value\": <short quote/paraphrase>, \"subtype\": "
    "<one of the subtypes below or empty>}]}. Do NOT include a weight or any "
    "age/band/confidence field — those are computed downstream. Only emit cues "
    "that are actually present; emit an empty list if none.\n"
    f"Valid subtypes: {_VALID_SUBTYPES}."
)


class SignalExtractorService:
    """Implements ISignalExtractor — one structured LLM pass per turn.

    Args:
        _mock_response: When provided, bypass the real tinyagent call and use
            this dict as the raw LLM response (unit-test seam only).
    """

    def __init__(self, _mock_response: dict[str, object] | None = None) -> None:
        self._mock_response = _mock_response

    async def extract(self, turn: TurnEvent) -> SignalSet:
        """Extract age-relevant cues from a single turn.

        Source of cues (in precedence order):
          1. ``_mock_response`` — unit-test seam.
          2. LLM agent — when a model endpoint is configured (``use_llm()``).
          3. Deterministic keyword extractor — the offline fallback.

        Whatever the source, cue **weights are re-stamped from the lexicon** so
        weighting is deterministic and auditable (the model may detect a cue but
        never sets its weight). Validation (``extra='forbid'`` etc.) happens
        before re-stamping, so malformed responses still raise ValidationError.
        """
        if self._mock_response is None and not use_llm():
            signal_set = extract_cues(turn.turn_text)
        else:
            raw = await self._call_extractor(turn)
            signal_set = SignalSet.model_validate(raw)

        signal_set = self._restamp_weights(signal_set)
        logger.info(
            "signal_extraction session=%s turn=%d cues=%d",
            turn.session_id,
            turn.turn_number,
            len(signal_set.cues),
        )
        return signal_set

    @staticmethod
    def _restamp_weights(signals: SignalSet) -> SignalSet:
        """Assign each cue's weight deterministically from the lexicon.

        A cue's subtype is used if present, otherwise inferred from its value.
        Cues the lexicon does not recognise keep their incoming weight (nothing
        to ground a deterministic value on).
        """
        restamped = []
        for cue in signals.cues:
            subtype = cue.subtype or lexicon.classify_subtype(cue.value)
            weight = lexicon.assign_weight_any(subtype) if subtype else cue.weight
            restamped.append(cue.model_copy(update={"subtype": subtype, "weight": weight}))
        return SignalSet(cues=restamped)

    async def _call_extractor(self, turn: TurnEvent) -> dict[str, object]:
        """Call the LLM endpoint (Ollama/vLLM/Fireworks) and return raw cues.

        The model detects cues (type + value + subtype); it does NOT set weights
        — those are re-stamped from the lexicon in ``extract``. In tests the mock
        seam is used instead of a real call.
        """
        if self._mock_response is not None:
            return self._mock_response

        from src.contracts.llm_client import complete_json

        raw = await complete_json(_SYSTEM_PROMPT, turn.turn_text)
        raw_list = raw.get("cues", []) if isinstance(raw, dict) else []
        raw_cues: list[object] = raw_list if isinstance(raw_list, list) else []
        return {"cues": [c for item in raw_cues if (c := self._sanitise_cue(item)) is not None]}

    @staticmethod
    def _sanitise_cue(cue: object) -> dict[str, object] | None:
        """Coerce a model-emitted cue into a valid Cue dict, or drop it.

        Small local models often invent invalid ``type``/``subtype`` values.
        We recover by re-deriving the subtype (and hence type + weight) from the
        lexicon; only cues we cannot ground at all are dropped.
        """
        if not isinstance(cue, dict):
            return None
        value = str(cue.get("value", "")).strip()
        if not value:
            return None

        subtype = str(cue.get("subtype", "")).strip()
        if not lexicon.is_known_subtype(subtype):
            subtype = lexicon.classify_subtype(value)

        if subtype:
            return {
                "type": lexicon.cue_type_for_any(subtype),
                "value": value,
                "subtype": subtype,
                "weight": lexicon.assign_weight_any(subtype),
            }

        # No recognised subtype: keep only if the model gave a valid type.
        ctype = str(cue.get("type", ""))
        if ctype in lexicon.VALID_CUE_TYPES:
            return {"type": ctype, "value": value, "subtype": "", "weight": 0.2}
        return None


# Verify service satisfies ISignalExtractor at import time (fail closed).
assert isinstance(SignalExtractorService(), ISignalExtractor), (
    "SignalExtractorService must satisfy ISignalExtractor protocol"
)
