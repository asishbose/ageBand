"""Unit tests for the deterministic rule-based estimator (M4 fallback)."""

from __future__ import annotations

from src.ageband_inference import rule_estimator
from src.contracts.models import Cue, EvidenceSummary


def _evidence(*cues: Cue) -> EvidenceSummary:
    return EvidenceSummary(session_id="rule-test", cues=list(cues), turn_count=1)


def _cue(subtype: str, weight: float, value: str = "x") -> Cue:
    from src.signal_extraction import lexicon

    return Cue(
        type=lexicon.cue_type_for(subtype),  # type: ignore[arg-type]
        value=value,
        weight=weight,
        subtype=subtype,
    )


class TestBandSelection:
    def test_no_cues_is_unknown(self) -> None:
        assert rule_estimator.estimate(_evidence()).band == "unknown"

    def test_adult_dominant(self) -> None:
        est = rule_estimator.estimate(
            _evidence(_cue("adult_life_topic", 0.6), _cue("workplace_topic", 0.6))
        )
        assert est.band == "adult"
        assert est.evasion_flag is False

    def test_teen_dominant(self) -> None:
        est = rule_estimator.estimate(
            _evidence(_cue("grade_level", 0.9), _cue("school_topic", 0.6))
        )
        assert est.band == "teen"

    def test_child_dominant(self) -> None:
        est = rule_estimator.estimate(
            _evidence(_cue("elementary_school", 0.9), _cue("guardian_reference", 0.7))
        )
        assert est.band == "child"


class TestEvasion:
    def test_adult_claim_with_child_cues_flags_evasion_and_not_adult(self) -> None:
        # The adversarial case: "I'm an adult" + explicit adult age, but school cue.
        est = rule_estimator.estimate(
            _evidence(
                _cue("explicit_adult_age", 1.0, "I am 25"),
                _cue("adult_self_claim", 0.3, "I'm an adult"),
                _cue("school_topic", 0.6, "not in school"),
            )
        )
        assert est.evasion_flag is True
        assert est.band != "adult"  # must NOT be fooled
        assert est.contradictions

    def test_genuine_adult_no_evasion(self) -> None:
        est = rule_estimator.estimate(
            _evidence(_cue("explicit_adult_age", 1.0), _cue("adult_life_topic", 0.6))
        )
        assert est.evasion_flag is False
        assert est.band == "adult"


class TestContract:
    def test_never_emits_confidence(self) -> None:
        est = rule_estimator.estimate(_evidence(_cue("grade_level", 0.9)))
        assert not hasattr(est, "confidence")
