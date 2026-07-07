"""Convert a copied-from-Discord .md transcript into DiscordChatExporter JSON.

Discord's copy-paste format is:

    DisplayName [ROLE],  — 2:37 PM
    message line 1
    message line 2
    NextUser — 2:38 PM
    ...

This parser groups message lines under each "Name — time" header, strips the
usual UI noise (bot/FAQ/thread-preview/server-info lines and stray role-tag
artifacts), and emits the JSON shape that src/roster ingestion expects.

Usage:
    python scripts/discord_md_to_export.py chat.md chat_export.json
"""

from __future__ import annotations

import json
import re
import sys

_HEADER_RE = re.compile(r"^(?P<name>.+?)\s+—\s+(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>AM|PM)$")
_ROLE_TAG_ONLY_RE = re.compile(r"^\[[^\]]+\],?$")
_NAME_TAG_RE = re.compile(r"\s*\[[^\]]+\],?\s*$")
_NOISE_RE = re.compile(
    r"^(APP|LabLab Admin|lablab\.ai-bot|Go to Server|AI|Game Development|Software|"
    r"Hardware|Developer|AMD Developer Community|\d[\d,]*\s+(Online|Members)|"
    r"Est\..*|\d+\s+Messages?\s+›|\d+\s*[mhd]\s*ago|Official AMD Developer.*)$"
)
_SKIP_PREFIX = ("FAQ:", "started a thread")
_BOT_AUTHORS = {"lablab.ai-bot", "lablab admin", "app", ""}


def _clean_name(name: str) -> str:
    return _NAME_TAG_RE.sub("", name).strip().rstrip(",").strip()


def _is_noise(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if _ROLE_TAG_ONLY_RE.match(s) or _NOISE_RE.match(s):
        return True
    return any(s.startswith(p) for p in _SKIP_PREFIX)


def _iso(h: int, m: int, ap: str, idx: int) -> str:
    """Synthesize an ISO timestamp on a fixed demo date (order is what matters)."""
    hh = h % 12 + (12 if ap == "PM" else 0)
    # idx keeps per-message ordering stable even within the same minute
    return f"2026-07-06T{hh:02d}:{m:02d}:{idx % 60:02d}Z"


def parse(md: str) -> dict:
    messages: list[dict] = []
    cur_author: str | None = None
    cur_ts: str = ""
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_author, cur_lines
        if cur_author is None:
            return
        content = " ".join(cur_lines).strip()
        if content and cur_author.lower() not in _BOT_AUTHORS:
            messages.append(
                {
                    "id": str(len(messages) + 1),
                    "type": "Default",
                    "timestamp": cur_ts,
                    "content": content,
                    "author": {
                        "id": re.sub(r"\s+", "_", cur_author.lower()),
                        "name": cur_author,
                        "isBot": False,
                    },
                }
            )
        cur_lines = []

    for line in md.splitlines():
        h = _HEADER_RE.match(line.strip())
        if h:
            flush()
            cur_author = _clean_name(h.group("name"))
            cur_ts = _iso(int(h.group("h")), int(h.group("m")), h.group("ap"), len(messages))
            continue
        if cur_author is not None and not _is_noise(line):
            cur_lines.append(line.strip())
    flush()

    return {
        "guild": {"id": "amd", "name": "AMD Developer Community"},
        "channel": {"id": "general", "name": "general-chat-amd-hackathon"},
        "messages": messages,
    }


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "chat.md"
    dst = sys.argv[2] if len(sys.argv) > 2 else "chat_export.json"
    with open(src, encoding="utf-8") as f:
        export = parse(f.read())
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    authors = sorted({m["author"]["name"] for m in export["messages"]})
    print(f"parsed {len(export['messages'])} messages from {len(authors)} authors -> {dst}")
    print("authors:", ", ".join(authors))


if __name__ == "__main__":
    main()
