"""Ingest a DiscordChatExporter JSON export and build an age-band roster.

DiscordChatExporter (https://github.com/Tyrrrz/DiscordChatExporter) JSON shape:

    {
      "guild": {...}, "channel": {...},
      "messages": [
        {"id": "...", "type": "Default", "timestamp": "2023-...",
         "content": "hello", "author": {"id": "1", "name": "u", "isBot": false}}
      ]
    }

We group non-bot text messages by author, replay each author's messages through
the AgeBand pipeline (one session per author), and return one roster row per user.
"""

from __future__ import annotations

import logging
from typing import Any

from src.contracts.models import TurnEvent
from src.evidence_fabric.store import _store
from src.orchestration.runner import OrchestrationService
from src.stepup_verification.persistence import clear_confirmed

logger = logging.getLogger(__name__)

# Risk ordering for sorting the roster (most protective concern first).
_BAND_RISK = {"child": 3, "teen": 2, "unknown": 1, "adult": 0}


def group_messages(export: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Group message text by author id, preserving order.

    Returns {author_id: {"username": str, "messages": [str, ...]}}.
    Skips bots, non-Default message types, and empty content.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for msg in export.get("messages", []):
        if not isinstance(msg, dict):
            continue
        # DiscordChatExporter marks system messages with non-"Default" types.
        if msg.get("type", "Default") not in ("Default", "Reply", 0, 19):
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        author = msg.get("author") or {}
        if author.get("isBot"):
            continue
        author_id = str(author.get("id", "")) or "unknown"
        entry = grouped.setdefault(
            author_id,
            {"username": author.get("nickname") or author.get("name") or author_id,
             "messages": []},
        )
        entry["messages"].append(content)
    return grouped


def _top_cues(cues: list[dict[str, Any]], limit: int = 4) -> list[str]:
    """Return the highest-weight distinct cue subtypes for display."""
    seen: dict[str, float] = {}
    for c in cues:
        sub = c.get("subtype") or c.get("type", "")
        seen[sub] = max(seen.get(sub, 0.0), float(c.get("weight", 0.0)))
    ranked = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)
    return [sub for sub, _w in ranked[:limit] if sub]


def _risk_key(row: dict[str, Any]) -> tuple[int, float]:
    """Sort key: band risk first, then confidence (descending via reverse)."""
    return (_BAND_RISK.get(row["band"], 1), row["confidence"])


async def build_roster(
    export: dict[str, Any], service: OrchestrationService | None = None
) -> list[dict[str, Any]]:
    """Replay an export through AgeBand and return per-user roster rows.

    Each row: user_id, username, band, confidence, posture, message_count,
    top_cues, step_up, evasion.
    """
    service = service or OrchestrationService()
    grouped = group_messages(export)
    rows: list[dict[str, Any]] = []

    for author_id, info in grouped.items():
        sid = f"discord:{author_id}"
        # Fresh session per build so re-runs are deterministic.
        _store.clear(sid)
        clear_confirmed(sid)

        last: dict[str, Any] | None = None
        for i, text in enumerate(info["messages"], 1):
            last = await service.run_turn_verbose(
                TurnEvent(session_id=sid, turn_text=text, turn_number=i)
            )
        if last is None:
            continue

        cues = last.get("evidence", {}).get("cues", [])
        evasion = any(c.get("subtype") == "adult_self_claim" for c in cues)
        rows.append(
            {
                "user_id": author_id,
                "username": info["username"],
                "band": last["band"],
                "confidence": round(last["confidence"], 2),
                "posture": last["posture"]["level"],
                "message_count": len(info["messages"]),
                "top_cues": _top_cues(cues),
                "step_up": bool(last["step_up"]),
                "evasion": evasion,
            }
        )
        _store.clear(sid)

    rows.sort(key=_risk_key, reverse=True)
    logger.info("roster built: %d users", len(rows))
    return rows
