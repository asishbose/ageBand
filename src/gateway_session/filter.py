"""Turn-role filter for gateway_session (M1).

Lean build: every turn is treated as a user turn.
This is a hook point for role-based filtering in future builds
(e.g. skipping assistant/system turns from the analysis pipeline).
"""

from __future__ import annotations

from src.contracts.models import TurnEvent


def is_user_turn(turn: TurnEvent) -> bool:
    """Return True for user turns.

    In the lean build this always returns True.
    Future: inspect turn.role or a similar field when the schema adds it.
    """
    return True
