from __future__ import annotations

import asyncio
from datetime import date

from app.models.schemas import CompanyFilingDocument, Source
from scripts import structured_company_filing_smoke as smoke


def _runtime(*, configured: bool = True, fallback_reason: str | None = None) -> dict:
    return {
        "configured": configured,
        "provider": "tej" if configured else None,
        "url_configured": configured,
        "token_configured": configured,
        "fallback_reason": fallback_reason,
    }


def _document() -> CompanyFilingDocument:
    return CompanyFilingDocument(
        id="structured-2330",
        ticker="2330",
        company_name="台積電",
        document_type="investor_presentation",
        title="台積電 2026 法說會簡報",
        text="2330 台積電 法說會 investor presentation 揭露 AI/HPC 需求與資本支出。",
        source=Source(
            title="台積電 2026 法說會簡報",
            url="https://api.tej.example/documents/2330",
            publisher="TEJ",
            published_at=date(2026, 5, 1),
        ),
    )


def test_structured_company_filing_smoke_reports_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "company_filing_structured_api_status",
        lambda: _runtime(configured=False, fallback_reason="missing_structured_api_provider_or_url"),
    )

    report = asyncio.run(smoke.structured_company_filing_smoke_report())

    assert report["status"] == "not_configured"
    assert report["ready"] is False
    assert report["runtime"]["fallback_reason"] == "missing_structured_api_provider_or_url"
    assert "structured_company_filing_smoke.py" in report["smoke_command"]
    assert smoke.smoke_exit_code(report, strict=False) == 0
    assert smoke.smoke_exit_code(report, strict=True) == 1


def test_structured_company_filing_smoke_reports_ready(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "company_filing_structured_api_status", lambda: _runtime())

    class FakeFetcher:
        async def fetch_structured_api_documents(self, **kwargs):
            self.kwargs = kwargs
            return [_document()], []

    fake_fetcher = FakeFetcher()

    report = asyncio.run(
        smoke.structured_company_filing_smoke_report(
            ticker="2330",
            company_name="台積電",
            document_types=["investor_presentation"],
            limit=2,
            fetcher=fake_fetcher,
        )
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["document_count"] == 1
    assert report["error_count"] == 0
    assert report["documents"][0]["publisher"] == "TEJ"
    assert report["documents"][0]["published_at"] == "2026-05-01"
    assert report["documents"][0]["text_length"] > 0
    assert fake_fetcher.kwargs["ticker"] == "2330"
    assert fake_fetcher.kwargs["document_types"] == ("investor_presentation",)
    assert smoke.smoke_exit_code(report, strict=True) == 0


def test_structured_company_filing_smoke_reports_degraded_when_no_documents(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "company_filing_structured_api_status", lambda: _runtime())

    class FakeFetcher:
        async def fetch_structured_api_documents(self, **_kwargs):
            return [], []

    report = asyncio.run(
        smoke.structured_company_filing_smoke_report(fetcher=FakeFetcher())
    )

    assert report["status"] == "degraded"
    assert report["ready"] is False
    assert "produced no convertible" in report["remediation"]
    assert smoke.smoke_exit_code(report, strict=False) == 1


def test_structured_company_filing_smoke_reports_errors(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "company_filing_structured_api_status", lambda: _runtime())

    class FakeFetcher:
        async def fetch_structured_api_documents(self, **_kwargs):
            return [], [{"stage": "structured_api", "category": "timeout"}]

    report = asyncio.run(
        smoke.structured_company_filing_smoke_report(fetcher=FakeFetcher())
    )

    assert report["status"] == "failed"
    assert report["ready"] is False
    assert report["error_count"] == 1
    assert smoke.smoke_exit_code(report, strict=False) == 1


def test_structured_company_filing_smoke_main_prints_json(monkeypatch, capsys) -> None:
    async def fake_report(**_kwargs):
        return {"status": "ready", "ready": True}

    monkeypatch.setattr(smoke, "structured_company_filing_smoke_report", fake_report)

    assert smoke.main(["--json", "--ticker", "2330"]) == 0
    assert '"status": "ready"' in capsys.readouterr().out
