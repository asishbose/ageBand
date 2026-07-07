"""Regression test for the conversation-level uncertainty penalty (Phase 3).

HARD REQUIREMENT: The uncertainty penalty MUST compute to exactly 0.0 for
every existing fixture (single-shot scenarios with no multi-turn volatility).
A non-zero penalty on existing fixtures would indicate the penalty logic
is incorrectly touching cases where band_history is empty.

See: hackathon plan §7, Phase 3 — "must compute to 0 for every existing
fixture" invariant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ageband_inference.confidence import _compute_uncertainty
from src.contracts.models import AgeBandEstimate, Cue, EvidenceSummary


def _make_estimate(band: str = "adult") -> AgeBandEstimate:
    return AgeBandEstimate(
        band=band,  # type: ignore[arg-type]
        cited_cues=[],
        evasion_flag=False,
        contradictions=[],
    )


def _make_evidence_no_history(
    session_id: str = "test",
    turn_count: int = 5,
    cues: list[Cue] | None = None,
) -> EvidenceSummary:
    """EvidenceSummary with no band_history — simulates existing fixtures."""
    return EvidenceSummary(
        session_id=session_id,
        cues=cues or [],
        corroboration_score=0.8,
        turn_count=turn_count,
        band_history=[],  # empty — the critical field for this test
    )


class TestUncertaintyPenaltyZeroOnExistingFixtures:
    """The single most important check in Phase 3."""

    def test_empty_band_history_returns_zero(self) -> None:
        """Empty band_history must yield exactly 0.0 uncertainty penalty."""
        evidence = _make_evidence_no_history()
        estimate = _make_estimate()
        penalty = _compute_uncertainty(evidence, estimate)
        assert penalty == 0.0, (
            f"Uncertainty penalty was {penalty} (expected 0.0) with empty band_history. "
            "This would silently change the confidence of every existing fixture."
        )

    @pytest.mark.parametrize("band", ["child", "teen", "adult", "unknown"])
    def test_empty_history_all_bands(self, band: str) -> None:
        evidence = _make_evidence_no_history()
        estimate = _make_estimate(band)
        assert _compute_uncertainty(evidence, estimate) == 0.0

    def test_empty_history_with_cues(self) -> None:
        """Adding cues doesn't change the 0.0 result when history is empty."""
        cues = [
            Cue(type="topic", value="mortgage", subtype="adult_life_topic", weight=0.6),
        ]
        evidence = _make_evidence_no_history(cues=cues)
        estimate = _make_estimate("adult")
        assert _compute_uncertainty(evidence, estimate) == 0.0

    @pytest.mark.parametrize("turn_count", [1, 2, 3, 5, 10])
    def test_empty_history_all_turn_counts(self, turn_count: int) -> None:
        """Turn count doesn't matter when band_history is empty."""
        evidence = _make_evidence_no_history(turn_count=turn_count)
        estimate = _make_estimate()
        assert _compute_uncertainty(evidence, estimate) == 0.0


class TestUncertaintyPenaltyFires:
    """Positive tests — penalty fires as expected on volatile sessions."""

    def test_conflicting_bands_in_history(self) -> None:
        evidence = _make_evidence_no_history()
        evidence = evidence.model_copy(
            update={"band_history": ["adult", "teen", "adult"]}
        )
        estimate = _make_estimate("adult")
        penalty = _compute_uncertainty(evidence, estimate)
        assert penalty > 0.0, "Conflicting bands should produce a positive penalty."

    def test_volatile_bands_flip_many_times(self) -> None:
        # 4 flips: child→teen→child→adult→child
        history = ["child", "teen", "child", "adult", "child"]
        evidence = _make_evidence_no_history()
        evidence = evidence.model_copy(update={"band_history": history})
        estimate = _make_estimate("child")
        penalty = _compute_uncertainty(evidence, estimate)
        assert penalty > 0.0, "High volatility should produce a positive penalty."

    def test_penalty_is_capped(self) -> None:
        from src.ageband_inference.config import MAX_UNCERTAINTY_PENALTY
        # Max-stress scenario: conflict + volatility + mismatch + sparsity.
        history = ["child", "adult", "teen", "child", "adult"]
        cues = [
            Cue(
                type="style",
                value="maturity_high=0.8",
                subtype="maturity_high",
                weight=0.3,
            )
        ]
        evidence = EvidenceSummary(
            session_id="cap-test",
            cues=cues,
            corroboration_score=0.5,
            turn_count=1,
            band_history=history,
        )
        estimate = _make_estimate("child")  # maturity_high contradicts child
        penalty = _compute_uncertainty(evidence, estimate)
        assert penalty <= MAX_UNCERTAINTY_PENALTY, (
            f"Penalty {penalty} exceeds cap {MAX_UNCERTAINTY_PENALTY}."
        )


def _all_fixture_files() -> list[Path]:
    """Collect all *.json fixtures from synthetic/ and synthetic_multilang/**/."""
    root = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"
    files: list[Path] = []
    for pattern in ("synthetic/*.json", "synthetic_multilang/**/*.json"):
        files.extend(root.glob(pattern))
    return files


class TestUncertaintyPenaltyOnSyntheticFixtures:
    """Load all synthetic fixture files and verify penalty = 0 (no band_history).

    Covers both tests/fixtures/synthetic/ and tests/fixtures/synthetic_multilang/
    so that multilingual fixtures added in Phase 06 are included in the regression
    guard — not just the original English set.
    """

    @pytest.fixture
    def synthetic_fixture_files(self) -> list[Path]:
        return _all_fixture_files()

    def test_penalty_zero_on_all_synthetic_fixtures(
        self, synthetic_fixture_files: list[Path]
    ) -> None:
        """Each synthetic fixture replayed as single-shot has no band_history."""
        if not synthetic_fixture_files:
            pytest.skip("No synthetic fixtures found.")

        for fp in synthetic_fixture_files:
            with fp.open() as f:
                fx = json.load(f)
            gt_band = fx.get("band", "unknown")
            # Simulate the evidence that would exist after replaying this fixture
            # without band_history population.
            evidence = EvidenceSummary(
                session_id=f"test-{fp.stem}",
                cues=[],
                corroboration_score=0.5,
                turn_count=len(fx.get("turns", [])),
                band_history=[],  # existing fixtures don't populate this
            )
            estimate = AgeBandEstimate(
                band=gt_band,  # type: ignore[arg-type]
                cited_cues=[],
                evasion_flag=False,
                contradictions=[],
            )
            penalty = _compute_uncertainty(evidence, estimate)
            assert penalty == 0.0, (
                f"Fixture {fp.name}: penalty={penalty} (expected 0.0). "
                "The uncertainty penalty is changing behaviour of existing fixtures."
            )
