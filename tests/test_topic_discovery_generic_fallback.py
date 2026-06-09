from app.services.topic_discovery import TopicDiscoveryService
from app.services.topic_discovery_generic_fallback import (
    generic_anchor_candidates,
    generic_exploration_plan,
)


def test_generic_exploration_plan_exposes_template_and_anchor_candidates() -> None:
    plan = generic_exploration_plan("量子運算")
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)
    anchors = generic_anchor_candidates("量子運算")

    assert quality.status in {"ready", "caution"}
    assert len(plan.subtopics) >= 6
    assert len(plan.candidate_companies) >= 6
    assert plan.candidate_companies == anchors
    assert any("主題定義與範圍收斂" in subtopic.name for subtopic in plan.subtopics)
    assert any("候選驗證與收斂" in subtopic.name for subtopic in plan.subtopics)
    assert all(candidate.evidence_keywords for candidate in plan.candidate_companies)
