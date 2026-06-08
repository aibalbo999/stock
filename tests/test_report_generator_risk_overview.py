from datetime import date
from pathlib import Path

from app.models.schemas import EntityMatch, RiskFinding, RiskType, Source
from app.services import report_risk_overview
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist
from report_generator_factories import make_finding


def test_risk_overview_filters_ai_infra_labels_for_robotics_companies() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    risk_source = Path("app/services/report_risk_overview.py").read_text()
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "1597",
                "name": "直得",
                "segment": "微型線性滑軌",
                "rationale": "微型線性滑軌可切入精密自動化與機器人",
                "evidence_keywords": ["微型線性滑軌", "機器人", "自動化"],
                "evidence_count": 2,
                "evidence_source_count": 2,
                "status": "evidence_supported",
            }
        ]
    )
    generator = ReportGenerator(whitelist=whitelist)
    finding = RiskFinding(
        risk_type=RiskType.structural_bottleneck,
        topic="HBM, 良率, 先進封裝",
        evidence="直得微型線性滑軌良率仍需觀察。",
        source=Source(title="直得風險", publisher="測試新聞", published_at=date(2026, 5, 22)),
        related_companies=[
            EntityMatch(
                ticker="1597",
                name="直得",
                segment_id="robotics",
                segment_name="微型線性滑軌",
                matched_alias="直得",
            )
        ],
    )

    overview = generator._render_risk_overview([finding], ["1597"])

    assert "良率(1)" in overview
    assert "HBM" not in overview
    assert "先進封裝" not in overview
    assert generator._company_risk_summary([finding]) == report_risk_overview.company_risk_summary(
        [finding],
        whitelist=whitelist,
    )
    assert generator._company_risk_summary([]) == report_risk_overview.company_risk_summary([], whitelist=whitelist)
    assert "report_risk_overview" not in generator_source
    assert "ReportGeneratorDecisionRiskMixin" in generator_source
    assert "report_risk_overview" in decision_risk_mixin_source
    assert "def _render_risk_overview(" in decision_risk_mixin_source
    assert "def _render_risk_overview(" not in generator_source
    assert "def render_risk_overview(" in risk_source
    assert "def company_risk_summary(" in risk_source
    assert "AI_INFRA_RISK_TERMS" in risk_source
    assert "AI_INFRA_RISK_TERMS" not in generator_source
    assert "### 代表性證據" not in generator_source
    assert "未偵測到可歸因的重大風險" not in generator_source
    assert report_risk_overview.sanitize_risk_topic(
        "HBM, 良率, 先進封裝",
        ["1597"],
        whitelist=whitelist,
    ) == "良率"


def test_related_findings_logic_lives_outside_generator_and_dedupes() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    risk_source = Path("app/services/report_risk_overview.py").read_text()
    finding = make_finding(
        "2330",
        "台積電",
        "先進製程產能吃緊",
        RiskType.structural_bottleneck,
    )
    duplicate = make_finding(
        "2330",
        "台積電",
        "先進製程產能吃緊",
        RiskType.structural_bottleneck,
    )
    unrelated = make_finding(
        "2382",
        "廣達",
        "AI 伺服器出貨波動",
        RiskType.short_term_volatility,
    )
    findings = [finding, duplicate, unrelated]

    assert "def related_findings(" in risk_source
    assert "def _related_findings(" in decision_risk_mixin_source
    assert "def _related_findings(" not in generator_source
    assert "seen: set[tuple" not in generator_source
    assert ReportGenerator._related_findings("2330", findings) == report_risk_overview.related_findings(
        "2330",
        findings,
    )
    assert ReportGenerator._related_findings("2330", findings) == [finding]
    assert ReportGenerator._related_findings("2382", findings) == [unrelated]


def test_findings_summary_logic_lives_outside_generator() -> None:
    generator_source = Path("app/services/report_generator.py").read_text()
    decision_risk_mixin_source = Path("app/services/report_generator_decision_risk.py").read_text()
    risk_source = Path("app/services/report_risk_overview.py").read_text()
    findings = [
        make_finding("2330", "台積電", "先進製程產能吃緊", RiskType.structural_bottleneck),
        make_finding("2382", "廣達", "AI 伺服器出貨短期波動", RiskType.short_term_volatility),
        make_finding("3324", "雙鴻", "液冷散熱滲透率提升", RiskType.opportunity_or_growth),
    ]

    assert "def findings_summary(" in risk_source
    assert "def _summary(" in decision_risk_mixin_source
    assert "def _summary(" not in generator_source
    assert "本次檢出" not in generator_source
    assert "目前檢索證據不足" not in generator_source
    assert ReportGenerator._summary([]) == report_risk_overview.findings_summary([])
    assert ReportGenerator._summary(findings) == report_risk_overview.findings_summary(findings)
    assert ReportGenerator._summary(findings) == "本次檢出 1 項結構性瓶頸、1 項短期波動、1 項機會/成長歸因。"
