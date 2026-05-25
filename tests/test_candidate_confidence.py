from app.services.candidate_confidence import (
    HIGH_CONFIDENCE_THRESHOLD,
    confidence_level,
    format_confidence_score,
    is_high_confidence,
    is_low_formal_confidence,
)


def test_candidate_confidence_labels_thresholds() -> None:
    assert confidence_level(None) == "未評估"
    assert confidence_level(HIGH_CONFIDENCE_THRESHOLD) == "高"
    assert confidence_level(60) == "中"
    assert confidence_level(30) == "低"


def test_candidate_confidence_format_and_gate_helpers() -> None:
    assert format_confidence_score(88.5) == "高 88.5"
    assert is_high_confidence(HIGH_CONFIDENCE_THRESHOLD) is True
    assert is_low_formal_confidence(HIGH_CONFIDENCE_THRESHOLD - 1) is True
