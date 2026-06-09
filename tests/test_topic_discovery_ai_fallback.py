from __future__ import annotations

from app.services.topic_discovery_ai_fallback import ai_fallback_plan
from app.services.topic_discovery_quality import evaluate_plan_quality


def test_ai_fallback_plan_lives_outside_topic_discovery_router() -> None:
    plan = ai_fallback_plan()
    quality = evaluate_plan_quality(plan)
    tickers = {candidate.ticker for candidate in plan.candidate_companies}

    assert quality.status == "ready"
    assert quality.coverage["上游材料"] is True
    assert {"2330", "2382", "3324", "2383", "6213", "1815", "8358", "6488"}.issubset(tickers)
    assert any("CoWoS" in subtopic.name for subtopic in plan.subtopics)
    assert any("半導體上游材料" in subtopic.name for subtopic in plan.subtopics)
