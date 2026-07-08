"""EvidenceFabricService — implements IEvidenceFabric (M3).

Ephemeral session store: accumulates cues across turns, applies corroboration
and decay. No LLM, no persistent storage, no PII retained between sessions.
"""

from __future__ import annotations

import logging

from src.contracts.models import EvidenceSummary, SignalSet
from src.contracts.protocols import IEvidenceFabric
from src.evidence_fabric.corroboration import compute_corroboration
from src.evidence_fabric.decay import apply_decay
from src.evidence_fabric.store import _store

_log = logging.getLogger(__name__)


class EvidenceFabricService:
    """Concrete implementation of IEvidenceFabric backed by an EphemeralStore."""

    def read(self, session_id: str) -> EvidenceSummary:
        """Return stored evidence, or an empty EvidenceSummary for new sessions."""
        stored = _store.get(session_id)
        if stored is not None:
            return stored
        _log.info("evidence_fabric.read: new session %s", session_id)
        return EvidenceSummary(session_id=session_id)

    def update(self, session_id: str, signals: SignalSet) -> EvidenceSummary:
        """Append new cues from *signals*, recompute corroboration, increment turn_count."""
        current = self.read(session_id)
        merged_cues = current.cues + signals.cues
        updated = EvidenceSummary(
            session_id=session_id,
            cues=merged_cues,
            corroboration_score=compute_corroboration(merged_cues),
            turn_count=current.turn_count + 1,
            # Preserve existing band_history across turns; the orchestration
            # layer appends to it via update_band_history().
            band_history=list(current.band_history),
            # Reset embedding_similarity each turn; new value set via
            # set_embedding_similarity() after async embedding call.
            embedding_similarity=None,
        )
        _store.set(session_id, updated)
        _log.info(
            "evidence_fabric.update: session=%s cues=%d turn=%d",
            session_id,
            len(merged_cues),
            updated.turn_count,
        )
        return updated

    def set_embedding_similarity(self, session_id: str, similarity: float) -> None:
        """Record the cosine similarity of the latest turn to the session centroid.

        Called asynchronously by the orchestration layer after the embedding call
        completes. A no-op if no session exists (e.g. called after an error path).
        """
        current = _store.get(session_id)
        if current is None:
            return
        updated = current.model_copy(update={"embedding_similarity": similarity})
        _store.set(session_id, updated)

    def decay(self, session_id: str) -> None:
        """Apply weight decay to stored evidence; discard zero-weight cues."""
        current = self.read(session_id)
        decayed = apply_decay(current)
        _store.set(session_id, decayed)
        _log.info(
            "evidence_fabric.decay: session=%s surviving_cues=%d",
            session_id,
            len(decayed.cues),
        )


# Satisfy the Protocol at import time (structural, not nominal).
_: IEvidenceFabric = EvidenceFabricService()
del _
