from datetime import date
from pathlib import Path

from app.models.schemas import EntityMatch, ReportRequest, RiskFinding, RiskType, Source
from app.services import report_decision_narrative
from app.services.report_generator import ReportGenerator


def make_finding(
    ticker: str,
    name: str,
    evidence: str,
    risk_type: RiskType = RiskType.short_term_volatility,
) -> RiskFinding:
    return RiskFinding(
        risk_type=risk_type,
        topic="測試主題",
        evidence=evidence,
        source=Source(title=evidence, publisher="測試新聞", published_at=date(2026, 5, 22)),
        related_companies=[
            EntityMatch(
                ticker=ticker,
                name=name,
                segment_id="test",
                segment_name="測試產業",
                matched_alias=name,
            )
        ],
    )


def test_structural_bottleneck_reason_names_specific_evidence() -> None:
    finding = make_finding(
        "2395",
        "研華",
        "產能吃緊造成交期延長",
        RiskType.structural_bottleneck,
    )
    estimate = {"upside_pct": 18, "downside_pct": 4}
    quality = {"grade": "supported", "missing": []}

    rating = ReportGenerator._decision_label(estimate, quality, [finding], 12)
    reason = ReportGenerator._decision_reason(
        rating,
        estimate,
        quality,
        [finding],
        [],
        12,
        ReportRequest(topic="機器人 產業鏈", tickers=["2395"]),
    )

    assert rating == "觀察 / 等風險降低"
    assert "瓶頸/限制證據：產能吃緊造成交期延長" in reason
    assert "存在結構性瓶頸證據" not in reason


def test_decision_reason_logic_lives_outside_generator() -> None:
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
    estimate = {"upside_pct": 18, "downside_pct": 4}
    quality = {"grade": "supported", "missing": []}
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    narrative_source = Path("app/services/report_decision_narrative.py").read_text()

    assert "report_decision_narrative" not in generator_source
    assert "ReportGeneratorDecisionRiskMixin" in generator_source
    assert "report_decision_narrative" in decision_risk_mixin_source
    assert "def _decision_reason(" in decision_risk_mixin_source
    assert "def _decision_reason(" not in generator_source
    assert "def decision_reason(" in narrative_source
    assert "def structural_bottleneck_reason(" in narrative_source
    assert "缺少可驗證市場資料" not in generator_source
    assert ReportGenerator._decision_reason(
        "可小額分批研究",
        estimate,
        quality,
        [],
        [],
        5,
        request,
    ) == report_decision_narrative.decision_reason(
        "可小額分批研究",
        estimate,
        quality,
        [],
        [],
        5,
        request,
    )
