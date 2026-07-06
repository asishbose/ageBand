"""StepupVerificationService (M7) — tinyagent delegate for message composition."""

from __future__ import annotations

import logging

from src.contracts.models import AgeBandContext, StepUpMessage
from src.contracts.protocols import IStepupVerification

logger = logging.getLogger(__name__)


class StepupVerificationService:
    """Implements IStepupVerification.

    compose() delegates to the stepup_composer tinyagent in production.
    Pass _mock_response for unit-test injection so no LLM call is made.
    """

    async def compose(
        self,
        ctx: AgeBandContext,
        _mock_response: dict[str, object] | None = None,
    ) -> StepUpMessage:
        """Compose a step-up verification message.

        In production: delegates to the stepup_composer tinyagent.
        In tests: accepts _mock_response to avoid any LLM call.
        Raises ValidationError if the response does not match StepUpMessage.
        """
        if _mock_response is not None:
            raw = _mock_response
        else:
            raw = await self._call_tinyagent(ctx)

        message = StepUpMessage.model_validate(raw)
        logger.info(
            "stepup_compose session=%s action=%s",
            ctx.session_id,
            message.action,
        )
        return message

    async def _call_tinyagent(self, ctx: AgeBandContext) -> dict[str, object]:
        """Invoke the stepup_composer tinyagent delegate."""
        # tinyagent wiring lives in orchestration; this service stays side-effect-free
        # in the lean build. Real implementation loads the YAML agent and runs it.
        raise NotImplementedError(  # pragma: no cover
            "tinyagent wiring not available outside orchestration layer"
        )

    def persist_confirmed(self, session_id: str, band: str) -> None:
        """Persist an explicitly CONFIRMED age band. Never called for inferred bands."""
        from src.stepup_verification.persistence import persist_confirmed as _persist

        _persist(session_id, band, confirmed=True)


# Verify protocol satisfaction at import time (fail closed).
assert isinstance(StepupVerificationService(), IStepupVerification), (
    "StepupVerificationService must satisfy IStepupVerification protocol"
)
