import pytest

from app.services.topic_discovery_parser import extract_json, parse_plan


def test_parse_plan_extracts_fenced_json_and_enriches_source_intents() -> None:
    raw = """
    前文
    ```json
    {
      "subtopics": [
        {
          "name": "液冷散熱",
          "rationale": "功耗提升",
          "objective": "確認液冷訂單是否支撐散熱成長",
          "required_evidence": ["液冷訂單"],
          "risk_focus": ["認證延遲"],
          "search_queries": ["AI 伺服器 液冷"]
        }
      ],
      "candidate_companies": [
        {
          "ticker": "3017",
          "name": "奇鋐",
          "segment": "散熱模組",
          "rationale": "液冷散熱升級",
          "evidence_keywords": ["液冷", "CDU"]
        }
      ]
    }
    ```
    """

    plan = parse_plan(raw)

    assert extract_json(raw).lstrip().startswith("{")
    assert plan.subtopics[0].name == "液冷散熱"
    assert plan.subtopics[0].source_intents
    assert plan.candidate_companies[0].ticker == "3017"


def test_extract_json_rejects_text_without_json_object() -> None:
    with pytest.raises(ValueError, match="json object not found"):
        extract_json("沒有 JSON")
