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

_SYSTEM_PROMPT = (
    "You estimate a chat user's age BAND from accumulated linguistic cues. "
    "Return ONLY JSON: {\"band\": <child|teen|adult|unknown>, \"cited_cues\": "
    "[<the cue values you relied on>], \"evasion_flag\": <true|false>, "
    "\"contradictions\": [<short strings>]}. "
    "NEVER output a confidence, score, or probability — confidence is computed "
    "deterministically downstream. Prefer 'unknown' when evidence is thin. "
    "If the user insists they are an adult while child/teen cues are present, "
    "set evasion_flag=true and do NOT conclude 'adult' (stated age is weighted "
    "evidence, not an override)."
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

        from src.contracts.llm_client import complete_json

        cue_lines = "\n".join(
            f"- {c.type}/{c.subtype or '?'}: {c.value} (w={c.weight:.2f})"
            for c in evidence.cues
        ) or "- (no cues yet)"
        user_prompt = (
            f"Accumulated cues for this session (turn {evidence.turn_count}):\n"
            f"{cue_lines}\n\nPropose the age band."
        )
        raw = await complete_json(_SYSTEM_PROMPT, user_prompt)
        return self._sanitise_estimate(raw)

    @staticmethod
    def _sanitise_estimate(raw: dict[str, object]) -> dict[str, object]:
        """Coerce a model-emitted estimate into a valid, confidence-free dict.

        Strips any confidence-like key the model may have added (confidence stays
        deterministic) and defaults an out-of-vocabulary band to 'unknown'.
        """
        band = str(raw.get("band", "unknown")).strip().lower()
        if band not in {"child", "teen", "adult", "unknown"}:
            band = "unknown"
        cited = raw.get("cited_cues", [])
        contradictions = raw.get("contradictions", [])
        return {
            "band": band,
            "cited_cues": [str(x) for x in cited] if isinstance(cited, list) else [],
            "evasion_flag": bool(raw.get("evasion_flag", False)),
            "contradictions": [str(x) for x in contradictions]
            if isinstance(contradictions, list)
            else [],
        }


# Verify service satisfies IAgeBandInference at import time (fail closed).
assert isinstance(AgeBandInferenceService(), IAgeBandInference), (
    "AgeBandInferenceService must satisfy IAgeBandInference protocol"
)
