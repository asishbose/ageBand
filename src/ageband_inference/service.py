"""AgeBandInferenceService — M4 LLM-backed age-band estimation.

The service delegates to the ageband_estimator YAML agent for the LLM pass,
then validates the raw output with validate_ageband_estimate (enforcing the
invariant that no confidence value may appear in LLM output).

In unit tests pass `_mock_response` to bypass real tinyagent calls.
"""

from __future__ import annotations

import logging

from src.ageband_inference import rule_estimator
from src.contracts.models import AgeBandEstimate, EvidenceSummary
from src.contracts.protocols import IAgeBandInference
from src.contracts.runtime import use_llm
from src.contracts.validators import validate_ageband_estimate

logger = logging.getLogger(__name__)

# JSON schema for guided decoding (vLLM guided_decoding_backend).
# When GUIDED_DECODING_ENABLED=1, this schema is sent to the LLM endpoint so
# the model is structurally constrained to the expected response shape.
# NOTE: 'confidence' is intentionally ABSENT — the LLM must never emit it.
_ESTIMATOR_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "band": {"type": "string", "enum": ["child", "teen", "adult", "unknown"]},
        "cited_cues": {"type": "array", "items": {"type": "string"}},
        "evasion_flag": {"type": "boolean"},
        "evasion_patterns": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["mismatch", "deflection", "register_switching", "over_insistence"],
            },
        },
        "contradictions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["band", "cited_cues", "evasion_flag", "evasion_patterns", "contradictions"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You estimate a chat user's age BAND from accumulated linguistic cues. "
    "Return ONLY JSON: {\"band\": <child|teen|adult|unknown>, \"cited_cues\": "
    "[<the cue values you relied on>], \"evasion_flag\": <true|false>, "
    "\"evasion_patterns\": [<pattern names, see below>], "
    "\"contradictions\": [<short strings>]}. "
    "NEVER output a confidence, score, or probability — confidence is computed "
    "deterministically downstream. Prefer 'unknown' when evidence is thin. "
    "\n\nMasking/evasion patterns to detect (set evasion_flag=true and list "
    "any that apply in evasion_patterns):\n"
    "  - 'mismatch': user claims to be an adult while child/teen cues are present "
    "(stated age is weighted evidence, not an override — do NOT conclude 'adult').\n"
    "  - 'deflection': user avoids or deflects direct age-related questions "
    "(e.g. 'why do you keep asking', 'I already told you', changing subject).\n"
    "  - 'register_switching': sudden, marked shift in vocabulary/style register "
    "mid-conversation (e.g. switches from casual/immature to formal/sophisticated "
    "without apparent reason — may indicate trying to appear older).\n"
    "  - 'over_insistence': repeated, escalating, unprompted repetition of an "
    "adult age claim without being challenged (the pattern of insistence itself, "
    "especially unprompted, is the signal).\n"
    "Leave evasion_patterns as [] when none apply."
)


class AgeBandInferenceService:
    """Implements IAgeBandInference — delegates to the LLM estimator agent.

    Args:
        _mock_response: When provided, bypass the real tinyagent call and use
            this dict as the raw LLM response (unit-test seam only).
    """

    def __init__(self, _mock_response: dict[str, object] | None = None) -> None:
        self._mock_response = _mock_response

    async def estimate(self, evidence: EvidenceSummary) -> AgeBandEstimate:
        """Propose an age-band estimate from accumulated session evidence.

        Calls validate_ageband_estimate on the raw LLM output before returning,
        raising ValueError if the LLM illegally included a confidence key.

        When no model endpoint is configured (and no mock), delegates to the
        deterministic rule-based estimator so the pipeline runs offline.
        """
        if self._mock_response is None and not use_llm():
            estimate = rule_estimator.estimate(evidence)
        else:
            raw = await self._call_estimator(evidence)
            estimate = validate_ageband_estimate(raw)
        logger.info(
            "ageband_estimate session=%s band=%s evasion=%s cues=%d contradictions=%d",
            evidence.session_id,
            estimate.band,
            estimate.evasion_flag,
            len(estimate.cited_cues),
            len(estimate.contradictions),
        )
        return estimate

    async def _call_estimator(self, evidence: EvidenceSummary) -> dict[str, object]:
        """Call the LLM endpoint (Ollama/vLLM/Fireworks) to propose a band.

        The model proposes a band + cited cues + evasion/contradictions. It must
        NOT emit a confidence value (validate_ageband_estimate enforces this;
        confidence is computed deterministically). In tests the mock seam is used.
        """
        if self._mock_response is not None:
            return self._mock_response

        import os

        from src.contracts.llm_client import complete_json, estimator_model

        cue_lines = "\n".join(
            f"- {c.type}/{c.subtype or '?'}: {c.value} (w={c.weight:.2f})"
            for c in evidence.cues
        ) or "- (no cues yet)"
        user_prompt = (
            f"Accumulated cues for this session (turn {evidence.turn_count}):\n"
            f"{cue_lines}\n\nPropose the age band."
        )
        # Phase 5 — guided decoding: when GUIDED_DECODING_ENABLED=1 and the
        # vLLM endpoint supports guided_decoding_backend, pass a JSON schema
        # so the model is constrained to a valid response shape. This removes
        # the need to coerce out-of-vocabulary outputs in _sanitise_estimate.
        schema: dict[str, object] | None = None
        if os.environ.get("GUIDED_DECODING_ENABLED", "").strip() in ("1", "true", "yes"):
            schema = _ESTIMATOR_JSON_SCHEMA
        raw = await complete_json(
            _SYSTEM_PROMPT, user_prompt, model=estimator_model(), json_schema=schema
        )
        return self._sanitise_estimate(raw)

    @staticmethod
    def _sanitise_estimate(raw: dict[str, object]) -> dict[str, object]:
        """Coerce a model-emitted estimate into a valid, confidence-free dict.

        Strips any confidence-like key the model may have added (confidence stays
        deterministic) and defaults an out-of-vocabulary band to 'unknown'.
        Extracts evasion_patterns (Phase 4 addition).
        """
        band = str(raw.get("band", "unknown")).strip().lower()
        if band not in {"child", "teen", "adult", "unknown"}:
            band = "unknown"
        cited = raw.get("cited_cues", [])
        contradictions = raw.get("contradictions", [])
        _valid_patterns = {"mismatch", "deflection", "register_switching", "over_insistence"}
        _raw_patterns = raw.get("evasion_patterns", [])
        raw_patterns: list[object] = _raw_patterns if isinstance(_raw_patterns, list) else []
        patterns = [str(p) for p in raw_patterns if str(p) in _valid_patterns]
        return {
            "band": band,
            "cited_cues": [str(x) for x in cited] if isinstance(cited, list) else [],
            "evasion_flag": bool(raw.get("evasion_flag", False)),
            "contradictions": [str(x) for x in contradictions]
            if isinstance(contradictions, list)
            else [],
            "evasion_patterns": patterns,
        }


# Verify service satisfies IAgeBandInference at import time (fail closed).
assert isinstance(AgeBandInferenceService(), IAgeBandInference), (
    "AgeBandInferenceService must satisfy IAgeBandInference protocol"
)
