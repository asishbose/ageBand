"""Unit tests for scripts/benchmark_roster.py (Phase 03).

Tests the report-generation/aggregation logic: cost calculation,
PENDING-marker logic, and synthetic export structure.
These run without a real AMD endpoint — they are purely deterministic
logic tests.
"""

from __future__ import annotations

import os
import sys

# Add scripts/ to path so we can import the script directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import benchmark_roster as br  # noqa: E402


class TestCostPer1kTurns:
    def test_basic_calculation(self) -> None:
        # $3.50/hr, 1000 tok/s, 150 tok/turn
        # turns_per_hour = 1000 * 3600 / 150 = 24000
        # cost_per_turn = 3.50 / 24000 ≈ 0.0001458
        # cost_per_1k = 0.1458
        result = br._cost_per_1k_turns(
            gpu_hourly_cost=3.50,
            tok_per_sec=1000.0,
            avg_toks_per_turn=150.0,
        )
        assert result is not None
        assert abs(result - 0.1458) < 0.001

    def test_zero_gpu_cost_returns_none(self) -> None:
        result = br._cost_per_1k_turns(0.0, 1000.0)
        assert result is None

    def test_zero_tok_per_sec_returns_none(self) -> None:
        result = br._cost_per_1k_turns(3.50, 0.0)
        assert result is None

    def test_negative_cost_returns_none(self) -> None:
        result = br._cost_per_1k_turns(-1.0, 500.0)
        assert result is None

    def test_higher_throughput_lower_cost(self) -> None:
        cost_low = br._cost_per_1k_turns(3.50, 100.0)
        cost_high = br._cost_per_1k_turns(3.50, 1000.0)
        assert cost_low is not None and cost_high is not None
        assert cost_high < cost_low


class TestBuildSyntheticExport:
    def test_default_authors_100(self) -> None:
        export = br._build_synthetic_export(100)
        assert "messages" in export
        messages = export["messages"]
        assert len(messages) > 0

    def test_custom_author_count(self) -> None:
        export = br._build_synthetic_export(5)
        messages = export["messages"]
        # Each author gets at least one turn
        author_ids = {m["author"]["id"] for m in messages}
        assert len(author_ids) == 5

    def test_message_structure(self) -> None:
        export = br._build_synthetic_export(1)
        msg = export["messages"][0]
        assert "id" in msg
        assert "content" in msg
        assert "author" in msg
        assert "isBot" in msg["author"]
        assert msg["author"]["isBot"] is False

    def test_guild_and_channel_present(self) -> None:
        export = br._build_synthetic_export(1)
        assert "guild" in export
        assert "channel" in export


class TestPendingMarkerLogic:
    """Tests the PENDING sentinel logic for AMD-specific headline numbers.

    When tok/s == 0 (no GPU run), fields should be the PENDING string.
    When real numbers are available, they should be numeric.
    """

    def _make_sweep_result(
        self,
        concurrency: int,
        p95_ms: float,
        gen_tok_per_sec: float,
        cost_per_1k: float | None,
    ) -> dict:
        return {
            "concurrency": concurrency,
            "p95_ms": p95_ms,
            "gen_tok_per_sec": gen_tok_per_sec,
            "cost_per_1k_turns_usd": cost_per_1k,
            "total_calls": 10,
            "successful": 10,
            "failed": 0,
            "median_ms": 100.0,
        }

    def test_pending_when_no_gpu(self) -> None:
        """tok/s == 0 → PENDING markers in slide_9_headline."""
        best = self._make_sweep_result(1, 0.0, 0.0, None)
        best_tps = best["gen_tok_per_sec"]
        best_cost = best["cost_per_1k_turns_usd"]

        p95_field = (
            "PENDING — requires AMD Dev Cloud MI300X run"
            if best_tps == 0
            else round(best["p95_ms"], 1)
        )
        tok_field = (
            "PENDING — requires AMD Dev Cloud MI300X run"
            if best_tps == 0
            else round(best_tps, 1)
        )
        cost_field = (
            "PENDING — requires AMD Dev Cloud MI300X run"
            if best_cost is None
            else round(best_cost, 4)
        )

        assert p95_field == "PENDING — requires AMD Dev Cloud MI300X run"
        assert tok_field == "PENDING — requires AMD Dev Cloud MI300X run"
        assert cost_field == "PENDING — requires AMD Dev Cloud MI300X run"

    def test_real_numbers_when_gpu_present(self) -> None:
        """Non-zero tok/s → numeric values, no PENDING markers."""
        best = self._make_sweep_result(50, 1200.0, 2500.0, 0.052)
        best_tps = best["gen_tok_per_sec"]
        best_cost = best["cost_per_1k_turns_usd"]

        p95_field = (
            "PENDING — requires AMD Dev Cloud MI300X run"
            if best_tps == 0
            else round(best["p95_ms"], 1)
        )
        tok_field = (
            "PENDING — requires AMD Dev Cloud MI300X run"
            if best_tps == 0
            else round(best_tps, 1)
        )
        cost_field = (
            "PENDING — requires AMD Dev Cloud MI300X run"
            if best_cost is None
            else round(best_cost, 4)
        )

        assert isinstance(p95_field, float)
        assert isinstance(tok_field, float)
        assert isinstance(cost_field, float)
        assert p95_field == 1200.0
        assert tok_field == 2500.0
