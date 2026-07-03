"""AgeBandInferenceService — M4 LLM-backed age-band estimation.

The service delegates to the ageband_estimator YAML agent for the LLM pass,
then validates the raw output with validate_ageband_estimate (enforcing the
invariant that no confidence value may appear in LLM output).

In unit tests pass `_mock_response` to bypass real tinyagent calls.
"""

from __future__ import annotations

import logging

from src.contracts.models import AgeBandEstimate, EvidenceSummary
from src.contracts.protocols import IAgeBandInference
from src.contracts.validators import validate_ageband_estimate

logger = logging.getLogger(__name__)


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
        """
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
        """Run the ageband_estimator YAML agent and return its raw output dict.

        In production this will invoke tinyagent with the configured YAML agent.
        In tests the mock seam is used instead.
        """
        if self._mock_response is not None:
            return self._mock_response

        # Production path: delegate to tinyagent ageband_estimator agent.
        # Import lazily to avoid hard dependency during unit tests.
        try:
            from tinyagent import AgentRunner  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "tinyagent is required for the production estimation path. "
                "Pass _mock_response in tests."
            ) from exc

        runner = AgentRunner.from_yaml("src/ageband_inference/ageband_estimator.yaml")
        result: dict[str, object] = await runner.run(evidence.model_dump())
        return result


# Verify service satisfies IAgeBandInference at import time (fail closed).
assert isinstance(AgeBandInferenceService(), IAgeBandInference), (
    "AgeBandInferenceService must satisfy IAgeBandInference protocol"
)
