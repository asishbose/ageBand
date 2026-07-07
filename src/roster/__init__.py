"""Roster — multi-user age-band view from a Discord chat export.

Replays a DiscordChatExporter JSON export through the AgeBand pipeline, one
session per author, and produces a per-user roster (band / confidence / posture
/ cues) — the operator's-eye view of a whole channel.

Ethics: only run this on a channel you control with consenting participants, an
export you are authorised to process, or synthetic data. Inferring age from real
non-consenting users' private chat is exactly what AgeBand is designed NOT to do.
"""

from src.roster.discord_ingest import build_roster, group_messages

__all__ = ["build_roster", "group_messages"]
