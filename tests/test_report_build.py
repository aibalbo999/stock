from types import SimpleNamespace

from app.models.schemas import ReportRequest, ReportResponse
from app.services.report_build import ReportBuildService


def test_report_build_service_uses_generated_evidence_for_quality_gate() -> None:
    captured = {}

    class FakeGenerator:
        def __init__(self) -> None:
            self.last_evidence_documents = []
            self.last_llm_result = SimpleNamespace(fallback=False)

        def generate(self, request):
            self.last_evidence_documents = ["doc-1", "doc-2", "doc-3"]
            return ReportResponse(title=f"{request.topic} report", markdown="# report")

    def fake_quality_gate(request, **kwargs):
        captured["quality_kwargs"] = kwargs
        return {"status": "ready", "source_count": kwargs.get("source_count")}

    def fake_attach(response, quality_gate):
        return response.model_copy(update={"quality_gate": quality_gate})

    result = ReportBuildService(
        report_generator_cls=FakeGenerator,
        build_quality_gate_for_request_func=fake_quality_gate,
        attach_quality_gate_to_report_func=fake_attach,
        report_execution_summary_func=lambda generator: {
            "evidence_count": len(generator.last_evidence_documents)
        },
    ).build(ReportRequest(topic="AI 產業鏈", tickers=["2330"]), source_count=1)

    assert result["evidence_count"] == 3
    assert result["report_execution"] == {"evidence_count": 3}
    assert captured["quality_kwargs"]["documents"] == ["doc-1", "doc-2", "doc-3"]
    assert captured["quality_kwargs"]["source_count"] == 3
    assert captured["quality_kwargs"]["llm_result"].fallback is False
    assert result["response"].quality_gate == {"status": "ready", "source_count": 3}


def test_report_build_service_passes_whitelist_documents_and_optional_quality_context() -> None:
    captured = {}

    class FakeGenerator:
        def __init__(self, whitelist=None) -> None:
            self.whitelist = whitelist
            self.last_evidence_documents = []
            self.last_llm_result = None

        def generate(self, request, documents=None):
            captured["whitelist"] = self.whitelist
            captured["documents_arg"] = documents
            self.last_evidence_documents = documents or []
            return ReportResponse(title="rerun", markdown="# rerun")

    def fake_quality_gate(request, **kwargs):
        captured["quality_kwargs"] = kwargs
        return {"status": "caution"}

    result = ReportBuildService(
        report_generator_cls=FakeGenerator,
        build_quality_gate_for_request_func=fake_quality_gate,
        attach_quality_gate_to_report_func=lambda response, gate: response.model_copy(update={"quality_gate": gate}),
        report_execution_summary_func=lambda generator: {"whitelist": generator.whitelist.name},
    ).build(
        ReportRequest(topic="機器人", tickers=["2308"]),
        whitelist=SimpleNamespace(name="dynamic"),
        documents=["formal-doc"],
        company_filing_sufficient_count=1,
        candidate_support={"supported": 1},
        plan_quality={"status": "complete"},
    )

    assert captured["whitelist"].name == "dynamic"
    assert captured["documents_arg"] == ["formal-doc"]
    assert captured["quality_kwargs"]["company_filing_sufficient_count"] == 1
    assert captured["quality_kwargs"]["candidate_support"] == {"supported": 1}
    assert captured["quality_kwargs"]["plan_quality"] == {"status": "complete"}
    assert "source_count" not in captured["quality_kwargs"]
    assert result["report_execution"] == {"whitelist": "dynamic"}
