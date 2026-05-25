from __future__ import annotations

from typing import Optional

HIGH_CONFIDENCE_THRESHOLD = 75
MEDIUM_CONFIDENCE_THRESHOLD = 45


def confidence_level(score: Optional[float]) -> str:
    if score is None:
        return "未評估"
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return "高"
    if score >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "中"
    return "低"


def format_confidence_score(score: Optional[float]) -> str:
    if score is None:
        return "未評估"
    number = float(score)
    formatted = str(int(number)) if number.is_integer() else f"{number:.1f}"
    return f"{confidence_level(number)} {formatted}"


def is_high_confidence(score: Optional[float]) -> bool:
    return score is not None and score >= HIGH_CONFIDENCE_THRESHOLD


def is_low_formal_confidence(score: Optional[float]) -> bool:
    return score is not None and score < HIGH_CONFIDENCE_THRESHOLD
