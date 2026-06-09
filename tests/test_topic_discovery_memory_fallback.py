from app.services.topic_discovery_memory_fallback import memory_fallback_plan
from app.services.topic_discovery import TopicDiscoveryService


def test_memory_fallback_plan_exposes_cycle_inventory_and_material_layers() -> None:
    plan = memory_fallback_plan("記憶體產業鏈")
    quality = TopicDiscoveryService.evaluate_plan_quality(plan)
    tickers = {candidate.ticker for candidate in plan.candidate_companies}
    query_text = " ".join(query for subtopic in plan.subtopics for query in subtopic.search_queries)

    assert quality.status in {"ready", "caution"}
    assert len(plan.subtopics) >= 5
    assert len(plan.candidate_companies) >= 8
    assert {"2408", "2344", "8299", "2451", "3260", "4967"}.issubset(tickers)
    assert any("庫存" in subtopic.name or "需求" in subtopic.name for subtopic in plan.subtopics)
    assert any("上游材料" in subtopic.name for subtopic in plan.subtopics)
    assert "memory" in query_text.lower() or "記憶體" in query_text
    assert "矽晶圓" in query_text
