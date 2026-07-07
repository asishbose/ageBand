"""Unit tests for Discord export ingestion and roster building."""

from __future__ import annotations

import pytest

from src.roster.discord_ingest import build_roster, group_messages

_EXPORT = {
    "messages": [
        {"type": "Default", "content": "im in 8th grade and have so much homework",
         "author": {"id": "u1", "name": "teen", "isBot": False}},
        {"type": "Default", "content": "my mom wont let me go out",
         "author": {"id": "u1", "name": "teen", "isBot": False}},
        {"type": "Default", "content": "my mortgage and my job keep me busy",
         "author": {"id": "u2", "name": "adult", "isBot": False}},
        {"type": "Default", "content": "beep boop",
         "author": {"id": "b1", "name": "bot", "isBot": True}},
        {"type": "Default", "content": "   ",
         "author": {"id": "u3", "name": "empty", "isBot": False}},
    ]
}


class TestGroupMessages:
    def test_groups_by_author_and_skips_bots_and_empty(self) -> None:
        grouped = group_messages(_EXPORT)
        assert set(grouped) == {"u1", "u2"}  # bot + empty-only excluded
        assert grouped["u1"]["messages"] == [
            "im in 8th grade and have so much homework",
            "my mom wont let me go out",
        ]

    def test_username_prefers_nickname(self) -> None:
        exp = {"messages": [
            {"type": "Default", "content": "hi",
             "author": {"id": "x", "name": "real", "nickname": "Nick", "isBot": False}}
        ]}
        assert group_messages(exp)["x"]["username"] == "Nick"


class TestBuildRoster:
    @pytest.fixture(autouse=True)
    def _det(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGEBAND_INFERENCE_MODE", "deterministic")

    @pytest.mark.asyncio
    async def test_rows_have_expected_shape_and_bands(self) -> None:
        rows = await build_roster(_EXPORT)
        assert len(rows) == 2
        by_user = {r["username"]: r for r in rows}
        assert by_user["teen"]["band"] in ("teen", "child")
        assert by_user["adult"]["band"] == "adult"
        for r in rows:
            assert set(r) >= {
                "user_id", "username", "band", "confidence", "posture",
                "message_count", "top_cues", "step_up", "evasion",
            }

    @pytest.mark.asyncio
    async def test_sorted_by_risk_minor_first(self) -> None:
        rows = await build_roster(_EXPORT)
        # The teen/child row should rank above the adult row.
        bands = [r["band"] for r in rows]
        assert bands.index(next(b for b in bands if b in ("teen", "child"))) < bands.index("adult")

    @pytest.mark.asyncio
    async def test_adversarial_not_classified_adult(self) -> None:
        exp = {"messages": [
            {"type": "Default", "content": "I am definitely an adult, I am 25",
             "author": {"id": "e", "name": "evader", "isBot": False}},
            {"type": "Default", "content": "stop treating me like a kid, im not in school",
             "author": {"id": "e", "name": "evader", "isBot": False}},
        ]}
        rows = await build_roster(exp)
        assert rows[0]["band"] != "adult"
        assert rows[0]["evasion"] is True
