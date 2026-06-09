from app.services.topic_discovery import TopicDiscoveryService
from app.services.topic_discovery_robotics_fallback import robotics_fallback_plan


def test_robotics_fallback_plan_exposes_components_materials_and_candidates() -> None:
    plan = robotics_fallback_plan("機器人 產業鏈")
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)
    tickers = {candidate.ticker for candidate in plan.candidate_companies}

    assert quality.status == "ready"
    assert quality.score == 100
    assert quality.coverage["上游材料"] is True
    assert len(plan.subtopics) >= 6
    assert len(plan.candidate_companies) == 20
    assert {"2308", "2049", "6188", "2002", "5009", "1303"}.issubset(tickers)
    assert any("協作" in subtopic.name for subtopic in plan.subtopics)
    assert any("上游材料" in subtopic.name for subtopic in plan.subtopics)
