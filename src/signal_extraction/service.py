"""SignalExtractorService — M2 LLM-backed signal extraction.

Delegates to the signal_extractor YAML agent for the one LLM pass,
then validates raw output as a SignalSet (Pydantic extra="forbid").

In unit tests pass `_mock_response: dict | None` to bypass tinyagent.
"""

from __future__ import annotations

import logging

from src.contracts.models import SignalSet, TurnEvent
from src.contracts.protocols import ISignalExtractor

logger = logging.getLogger(__name__)

_YAML_AGENT_PATH = "src/signal_extraction/signal_extractor.yaml"


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

        Calls the signal_extractor YAML agent (or mock) and validates the
        response as a SignalSet.  Raises pydantic.ValidationError if the
        response does not match the schema (extra fields included).
        """
        raw = await self._call_extractor(turn)
        signal_set = SignalSet.model_validate(raw)
        logger.info(
            "signal_extraction session=%s turn=%d cues=%d",
            turn.session_id,
            turn.turn_number,
            len(signal_set.cues),
        )
        return signal_set

    async def _call_extractor(self, turn: TurnEvent) -> dict[str, object]:
        """Run the signal_extractor YAML agent and return its raw output dict.

        In tests the mock seam is used instead of a real tinyagent call.
        """
        if self._mock_response is not None:
            return self._mock_response

        try:
            from tinyagent import AgentRunner  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "tinyagent is required for the production extraction path. "
                "Pass _mock_response in tests."
            ) from exc

        runner = AgentRunner.from_yaml(_YAML_AGENT_PATH)
        result: dict[str, object] = await runner.run({"turn_text": turn.turn_text})
        return result


# Verify service satisfies ISignalExtractor at import time (fail closed).
assert isinstance(SignalExtractorService(), ISignalExtractor), (
    "SignalExtractorService must satisfy ISignalExtractor protocol"
)
