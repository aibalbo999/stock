from __future__ import annotations

import asyncio
from datetime import date
import json

import pytest

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


def test_structured_company_filing_smoke_validates_sample_json_without_live_config(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        smoke,
        "company_filing_structured_api_status",
        lambda: _runtime(configured=False, fallback_reason="missing_structured_api_provider_or_url"),
    )
    sample_path = tmp_path / "structured_api_sample.json"
    sample_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "title": "2330 台積電 2026 法說會簡報",
                        "text": "2330 台積電 法說會 investor presentation 揭露 AI/HPC 需求與資本支出。",
                        "url": "https://api.tej.example/documents/2330-presentation.pdf",
                        "publisher": "TEJ",
                        "published_at": "2026-05-01",
                        "document_type": "investor_presentation",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = asyncio.run(
        smoke.structured_company_filing_smoke_report(
            ticker="2330",
            company_name="台積電",
            document_types=["investor_presentation"],
            sample_json_path=sample_path,
        )
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["mode"] == "sample_json_contract"
    assert report["runtime"]["configured"] is False
    assert report["sample_path"] == str(sample_path)
    assert report["raw_row_count"] == 1
    assert report["document_count"] == 1
    assert report["contract_diagnostics"]["row_container"] == "documents"
    assert report["contract_diagnostics"]["conversion_ratio"] == 1.0
    assert report["contract_diagnostics"]["field_coverage"]["title"] == 1
    assert report["contract_diagnostics"]["field_coverage"]["text"] == 1
    assert report["documents"][0]["publisher"] == "TEJ"
    assert report["documents"][0]["published_at"] == "2026-05-01"
    assert f"--sample-json {sample_path}" in report["smoke_command"]
    formatted = smoke.format_structured_company_filing_smoke(report)
    assert "sample_json_contract" in formatted
    assert "原始列數: 1" in formatted
    assert "資料列容器: documents" in formatted
    assert "轉換比例: 1.0" in formatted
    assert "驗證指令:" in formatted
    assert "raw rows:" not in formatted
    assert "row container:" not in formatted
    assert "conversion ratio:" not in formatted
    assert "- command:" not in formatted
    assert smoke.smoke_exit_code(report, strict=True) == 0


def test_structured_company_filing_smoke_reports_degraded_for_bad_sample_json(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(smoke, "company_filing_structured_api_status", lambda: _runtime())
    sample_path = tmp_path / "bad_structured_api_sample.json"
    sample_path.write_text(
        json.dumps({"documents": [{"title": "2330 台積電 法說會"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = asyncio.run(
        smoke.structured_company_filing_smoke_report(
            ticker="2330",
            company_name="台積電",
            document_types=["investor_presentation"],
            sample_json_path=sample_path,
        )
    )

    assert report["status"] == "degraded"
    assert report["ready"] is False
    assert report["raw_row_count"] == 1
    assert report["document_count"] == 0
    assert report["contract_diagnostics"]["row_container"] == "documents"
    assert report["contract_diagnostics"]["conversion_ratio"] == 0.0
    assert report["errors"][0]["category"] == "row_not_convertible"
    assert "無法轉成公司文件" in report["remediation"]
    assert f"--sample-json {sample_path}" in report["smoke_command"]
    assert smoke.smoke_exit_code(report, strict=False) == 1


def test_structured_company_filing_smoke_reports_ready(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "company_filing_structured_api_status", lambda: _runtime())

    class FakeFetcher:
        last_structured_api_contract_diagnostics = {
            "row_container": "documents",
            "conversion_ratio": 1.0,
        }

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
    assert report["contract_diagnostics"] == {
        "row_container": "documents",
        "conversion_ratio": 1.0,
    }
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
    assert "沒有可轉成公司文件的資料" in report["remediation"]
    assert smoke.smoke_exit_code(report, strict=False) == 1


def test_structured_company_filing_smoke_help_uses_operator_language(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        smoke.main(["--help"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "檢查已設定的公司文件結構化 API 回應格式" in output
    assert "要查詢的股票代號" in output
    assert "可重複指定" in output
    assert "未就緒時回傳非 0 結束碼" in output
    assert "輸出 JSON，方便工具讀取" in output
    assert "Print machine-readable JSON" not in output
    assert "Return non-zero when not ready" not in output


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
