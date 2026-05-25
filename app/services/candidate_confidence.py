from __future__ import annotations

from typing import Optional

from app.core.config import get_settings

HIGH_CONFIDENCE_THRESHOLD = 75
MEDIUM_CONFIDENCE_THRESHOLD = 45


def confidence_thresholds() -> tuple[int, int]:
    settings = get_settings()
    high = int(settings.candidate_confidence_high_threshold)
    medium = int(settings.candidate_confidence_medium_threshold)
    if medium >= high:
        medium = max(0, high - 1)
    return high, medium


def confidence_level(score: Optional[float]) -> str:
    if score is None:
        return "未評估"
    high, medium = confidence_thresholds()
    if score >= high:
        return "高"
    if score >= medium:
        return "中"
    return "低"


def format_confidence_score(score: Optional[float]) -> str:
    if score is None:
        return "未評估"
    number = float(score)
    formatted = str(int(number)) if number.is_integer() else f"{number:.1f}"
    return f"{confidence_level(number)} {formatted}"


def is_high_confidence(score: Optional[float]) -> bool:
    high, _ = confidence_thresholds()
    return score is not None and score >= high


def is_low_formal_confidence(score: Optional[float]) -> bool:
    high, _ = confidence_thresholds()
    return score is not None and score < high
