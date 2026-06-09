import asyncio
from datetime import date

import httpx

from app.core.config import get_settings
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    company_filing_structured_api_configured,
    company_filing_structured_api_status,
    structured_api_document_rows,
    structured_api_payload_contract_diagnostics,
    structured_api_provider_decision_matrix,
    structured_api_provider_profile,
    structured_api_provider_setup_preview,
    structured_api_request_contract,
)


def test_company_filing_structured_api_status_requires_provider_and_url(monkeypatch) -> None:
    token = "tej-" + "token"
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_TOKEN", token)
    get_settings.cache_clear()
    try:
        assert company_filing_structured_api_configured() is True
        status = company_filing_structured_api_status()
    finally:
        get_settings.cache_clear()

    assert status["configured"] is True
    assert status["configuration_ready"] is True
    assert status["provider"] == "tej"
    assert status["url_configured"] is True
    assert status["token_configured"] is True
    assert status["token_required"] is True
    assert status["configuration_check"] == {
        "ready": True,
        "status": "ready",
        "fallback_reason": None,
        "required_env_keys": [
            "COMPANY_FILING_STRUCTURED_API_PROVIDER",
            "COMPANY_FILING_STRUCTURED_API_URL",
            "COMPANY_FILING_STRUCTURED_API_TOKEN",
        ],
        "configured_env_keys": [
            "COMPANY_FILING_STRUCTURED_API_PROVIDER",
            "COMPANY_FILING_STRUCTURED_API_URL",
            "COMPANY_FILING_STRUCTURED_API_TOKEN",
        ],
        "missing_env_keys": [],
        "token_required": True,
        "token_configured": True,
        "endpoint_configured": True,
        "endpoint_valid": True,
        "endpoint_scheme": "https",
        "endpoint_host_configured": True,
        "provider_profile_key": "tej",
        "auth_mode": "bearer",
        "token_location": "authorization_header",
    }
    assert status["provider_profile_key"] == "tej"
    assert status["provider_profile"]["auth_mode"] == "bearer"
    assert status["request_contract"]["token_location"] == "authorization_header"
    assert status["request_contract"]["document_type_param"] == "document_type"
    setup_preview = status["provider_setup_preview"]
    assert setup_preview["profile_key"] == "tej"
    assert setup_preview["endpoint"] == "https://api.tej.example/filings"
    assert setup_preview["headers"]["Authorization"] == "Bearer <redacted>"
    assert setup_preview["params"] == {
        "ticker": "2330",
        "company_name": "台積電",
        "limit": 3,
        "document_type": "investor_presentation",
    }
    assert setup_preview["token_redacted"] is True
    assert token not in str(setup_preview)
    assert setup_preview["env_template"] == [
        "COMPANY_FILING_STRUCTURED_API_PROVIDER=tej",
        "COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>",
        "COMPANY_FILING_STRUCTURED_API_TOKEN=<token>",
    ]
    assert status["request_contract"]["response_rows"] == [
        "documents",
        "data",
        "results",
        "items",
        "records",
        "list",
    ]
    assert "ticker_or_company_mention" in status["request_contract"]["required_document_fields"]
    assert status["response_row_aliases"] == status["request_contract"]["response_rows"]
    assert status["retry_policy"]["attempts"] == 2
    assert status["retry_policy"]["retryable_http_statuses"] == [403, 429, 500, 502, 503, 504]
    assert "tej" in status["supported_provider_profiles"]
    assert (
        status["supported_provider_profiles"]["scrapingbee_dataset"]["token_location"]
        == "query_param"
    )
    matrix = {row["provider"]: row for row in status["provider_decision_matrix"]}
    assert set(matrix) == {"tej", "scrapingbee_dataset", "brightdata_dataset", "custom"}
    assert matrix["tej"]["token_required"] is True
    assert matrix["tej"]["document_type_param"] == "document_type"
    assert "COMPANY_FILING_STRUCTURED_API_TOKEN" in matrix["tej"]["env_keys"]
    assert matrix["custom"]["token_required"] is False
    assert "COMPANY_FILING_STRUCTURED_API_TOKEN" not in matrix["custom"]["env_keys"]
    assert "TEJ" in status["provider_selection_hint"]
    assert status["smoke_cli"].endswith(
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
    )
    assert status["sample_contract_cli"].endswith(
        "--sample-json examples/structured_company_filing_sample.json "
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
    )
    assert status["local_fixture_api"]["provider"] == "custom"
    assert status["local_fixture_api"]["token_required"] is False
    assert status["local_fixture_api"]["url"] == "http://127.0.0.1:8794/filings"
    assert "structured_company_filing_fixture_smoke.py" in (
        status["local_fixture_api"]["http_smoke_cli"]
    )
    assert status["local_fixture_api"]["provider_profile"] == "tej"
    assert "--provider-profile tej" in status["local_fixture_api"]["provider_profile_smoke_cli"]
    assert "local_structured_company_filing_api.py" in status["local_fixture_start_cli"]
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom" in status["local_fixture_smoke_cli"]
    assert "structured_company_filing_smoke.py" in status["local_fixture_smoke_cli"]
    assert "structured_company_filing_fixture_smoke.py" in (
        status["local_fixture_http_smoke_cli"]
    )
    assert "--provider-profile tej" in status["local_fixture_provider_profile_smoke_cli"]
    assert status["free_validation"]["status"] == "ready"
    assert status["free_validation"]["sample_contract_ready"] is True
    assert status["free_validation"]["local_fixture_available"] is True
    assert status["free_validation"]["provider_profile_fixture_available"] is True
    assert status["free_validation"]["provider_profile"] == "tej"
    assert status["free_validation"]["live_paid_provider_configured"] is True
    assert status["free_validation"]["local_fixture_url"] == "http://127.0.0.1:8794/filings"
    assert "local_structured_company_filing_api.py" in (
        status["free_validation"]["local_fixture_start_cli"]
    )
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom" in (
        status["free_validation"]["local_fixture_smoke_cli"]
    )
    assert "structured_company_filing_fixture_smoke.py" in (
        status["free_validation"]["local_fixture_http_smoke_cli"]
    )
    assert "--provider-profile tej" in (
        status["free_validation"]["local_fixture_provider_profile_smoke_cli"]
    )
    assert status["sample_contract_ready"] is True
    assert status["sample_contract"]["status"] == "ready"
    assert status["sample_contract"]["raw_row_count"] >= 1
    assert status["sample_contract"]["document_count"] >= 1
    assert status["sample_contract"]["mode"] == "sample_json_contract"
    sample_diagnostics = status["sample_contract"]["contract_diagnostics"]
    assert sample_diagnostics["row_container"] == "items"
    assert sample_diagnostics["conversion_ratio"] == 1.0
    assert sample_diagnostics["field_coverage"]["title"] >= 1
    assert sample_diagnostics["field_coverage"]["ticker_or_company_mention"] >= 1
    assert status["fallback_reason"] is None


def test_company_filing_structured_api_status_flags_missing_required_token(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.delenv("COMPANY_FILING_STRUCTURED_API_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        assert company_filing_structured_api_configured() is True
        status = company_filing_structured_api_status()
    finally:
        get_settings.cache_clear()

    assert status["configured"] is True
    assert status["configuration_ready"] is False
    assert status["token_required"] is True
    assert status["token_configured"] is False
    assert status["fallback_reason"] == "missing_structured_api_token"
    assert status["configuration_check"]["status"] == "missing_required_env"
    assert status["configuration_check"]["missing_env_keys"] == [
        "COMPANY_FILING_STRUCTURED_API_TOKEN"
    ]


def test_fetch_structured_api_documents_requires_complete_configuration(monkeypatch) -> None:
    async def fail_fetch_response(*_args, **_kwargs):
        raise AssertionError("live structured API fetch should wait for complete configuration")

    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.delenv("COMPANY_FILING_STRUCTURED_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "app.data_sources.company_filings.company_filing_fetch_response_with_retries",
        fail_fetch_response,
    )
    get_settings.cache_clear()
    try:
        documents, errors = asyncio.run(
            CompanyFilingFetcher().fetch_structured_api_documents("2330", "台積電")
        )
    finally:
        get_settings.cache_clear()

    assert documents == []
    assert errors == [
        {
            "source": "https://api.tej.example/filings",
            "error": "missing_structured_api_token",
            "category": "structured_api_not_configured",
            "retryable": False,
            "stage": "structured_api_configuration",
        }
    ]


def test_structured_api_provider_profiles_and_request_contracts() -> None:
    tej_profile = structured_api_provider_profile("tej")
    scrapingbee_profile = structured_api_provider_profile("scrapingbee_dataset")
    custom_profile = structured_api_provider_profile("unknown_provider")
    tej_token = "tej-" + "token"
    bee_token = "bee-" + "token"

    assert tej_profile["profile_key"] == "tej"
    assert tej_profile["document_type_param"] == "document_type"
    assert scrapingbee_profile["token_location"] == "query_param"
    assert custom_profile["profile_key"] == "custom"
    assert custom_profile["provider"] == "unknown_provider"

    tej_contract = structured_api_request_contract(
        provider="tej",
        endpoint="https://api.tej.example/filings",
        token=tej_token,
        ticker="2330",
        company_name="台積電",
        limit=2,
        document_types=["investor_presentation"],
    )
    scrapingbee_contract = structured_api_request_contract(
        provider="scrapingbee_dataset",
        endpoint="https://app.scrapingbee.example/dataset",
        token=bee_token,
        ticker="2330",
        company_name="台積電",
        document_types=["investor_presentation"],
    )

    assert tej_contract["headers"]["Authorization"] == f"Bearer {tej_token}"
    assert tej_contract["params"]["document_type"] == "investor_presentation"
    assert "api_key" not in tej_contract["params"]
    assert scrapingbee_contract["headers"] == {"Accept": "application/json"}
    assert scrapingbee_contract["params"]["api_key"] == bee_token
    assert scrapingbee_contract["params"]["document_types"] == "investor_presentation"

    scrapingbee_preview = structured_api_provider_setup_preview(
        provider="scrapingbee_dataset",
        endpoint="https://app.scrapingbee.example/dataset",
        token=bee_token,
        ticker="2330",
        company_name="台積電",
        document_types=["investor_presentation"],
    )

    assert scrapingbee_preview["headers"] == {"Accept": "application/json"}
    assert scrapingbee_preview["params"]["api_key"] == "<redacted>"
    assert scrapingbee_preview["params"]["document_types"] == "investor_presentation"
    assert scrapingbee_preview["token_location"] == "query_param"
    assert scrapingbee_preview["token_redacted"] is True
    assert bee_token not in str(scrapingbee_preview)


def test_structured_api_provider_decision_matrix_summarizes_vendor_contracts() -> None:
    matrix = {row["provider"]: row for row in structured_api_provider_decision_matrix()}

    assert matrix["tej"]["recommended_when"].startswith("正式穩定取得台灣法說會")
    assert matrix["tej"]["token_location"] == "authorization_header"
    assert matrix["scrapingbee_dataset"]["token_location"] == "query_param"
    assert matrix["scrapingbee_dataset"]["request_param_keys"][-1] == "api_key"
    assert matrix["brightdata_dataset"]["token_required"] is True
    assert matrix["custom"]["token_required"] is False
    assert matrix["custom"]["env_keys"] == [
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
    ]
    assert "documents" in matrix["custom"]["response_row_aliases"]
    assert "document_type_match" in matrix["custom"]["required_document_fields"]


def test_structured_api_document_rows_accepts_common_payload_shapes() -> None:
    assert structured_api_document_rows({"documents": [{"title": "A"}, "bad"]}) == [{"title": "A"}]
    assert structured_api_document_rows({"data": [{"title": "B"}]}) == [{"title": "B"}]
    assert structured_api_document_rows({"items": [{"title": "C"}]}) == [{"title": "C"}]
    assert structured_api_document_rows({"records": [{"title": "D"}]}) == [{"title": "D"}]
    assert structured_api_document_rows({"list": [{"title": "E"}]}) == [{"title": "E"}]
    assert structured_api_document_rows([{"title": "C"}]) == [{"title": "C"}]


def test_structured_api_payload_contract_diagnostics_summarizes_field_coverage() -> None:
    payload = {
        "documents": [
            {
                "headline": "2330 台積電 2026 法說會簡報",
                "abstract": "2330 台積電 investor presentation 說明 AI/HPC 需求。",
                "document_type": "investor_presentation",
                "report_date": "2026-05-01",
                "source": {"publisher": "TEJ"},
                "file": {"url": "https://api.tej.example/2330.pdf"},
            },
            "bad-row",
        ]
    }

    diagnostics = structured_api_payload_contract_diagnostics(
        payload,
        ticker="2330",
        company_name="台積電",
        document_types=["investor_presentation"],
        documents=[object()],
        row_errors=[],
    )

    assert diagnostics["row_container"] == "documents"
    assert diagnostics["raw_row_count"] == 2
    assert diagnostics["object_row_count"] == 1
    assert diagnostics["non_object_row_count"] == 1
    assert diagnostics["convertible_document_count"] == 1
    assert diagnostics["conversion_ratio"] == 1.0
    assert diagnostics["field_coverage"] == {
        "title": 1,
        "text": 1,
        "url": 1,
        "publisher": 1,
        "published_at": 1,
        "ticker_or_company_mention": 1,
        "requested_document_type_match": 1,
    }


def test_fetch_structured_api_documents_uses_provider_request_contract(monkeypatch) -> None:
    captured = {}
    token = "tej-" + "token"

    class FakeResponse:
        def json(self):
            return {
                "documents": [
                    {
                        "title": "2330 台積電 法說會簡報",
                        "text": "2330 台積電 investor presentation 說明 AI/HPC 需求。",
                        "url": "https://api.tej.example/documents/2330.pdf",
                        "publisher": "TEJ",
                        "published_at": "2026-05-01",
                        "document_type": "investor_presentation",
                    }
                ]
            }

    async def fake_fetch_response(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_TOKEN", token)
    monkeypatch.setattr(
        "app.data_sources.company_filings.company_filing_fetch_response_with_retries",
        fake_fetch_response,
    )
    get_settings.cache_clear()
    try:
        fetcher = CompanyFilingFetcher()
        documents, errors = asyncio.run(
            fetcher.fetch_structured_api_documents(
                "2330",
                "台積電",
                limit=2,
                document_types=["investor_presentation"],
            )
        )
    finally:
        get_settings.cache_clear()

    assert errors == []
    assert len(documents) == 1
    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.tej.example/filings"
    assert captured["kwargs"]["headers"]["Authorization"] == f"Bearer {token}"
    assert captured["kwargs"]["params"] == {
        "ticker": "2330",
        "company_name": "台積電",
        "limit": 2,
        "document_type": "investor_presentation",
    }
    diagnostics = fetcher.last_structured_api_contract_diagnostics
    assert diagnostics["row_container"] == "documents"
    assert diagnostics["convertible_document_count"] == 1
    assert diagnostics["field_coverage"]["ticker_or_company_mention"] == 1


def test_fetch_structured_api_documents_reports_contract_error_when_response_has_no_rows(
    monkeypatch,
) -> None:
    token = "tej-" + "token"

    class FakeResponse:
        def json(self):
            return {"meta": {"count": 0}}

    async def fake_fetch_response(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_TOKEN", token)
    monkeypatch.setattr(
        "app.data_sources.company_filings.company_filing_fetch_response_with_retries",
        fake_fetch_response,
    )
    get_settings.cache_clear()
    try:
        fetcher = CompanyFilingFetcher()
        documents, errors = asyncio.run(
            fetcher.fetch_structured_api_documents("2330", "台積電")
        )
    finally:
        get_settings.cache_clear()

    assert documents == []
    assert errors[0]["stage"] == "structured_api"
    assert errors[0]["category"] == "structured_api_no_rows"
    assert errors[0]["retryable"] is False
    assert "documents, data, results" in errors[0]["error"]
    assert fetcher.last_structured_api_contract_diagnostics["row_container"] is None
    assert fetcher.last_structured_api_contract_diagnostics["raw_row_count"] == 0


def test_fetch_structured_api_documents_reports_contract_error_when_rows_do_not_convert(
    monkeypatch,
) -> None:
    token = "tej-" + "token"

    class FakeResponse:
        def json(self):
            return {"documents": [{"title": "2330 台積電 法說會簡報"}]}

    async def fake_fetch_response(*_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_TOKEN", token)
    monkeypatch.setattr(
        "app.data_sources.company_filings.company_filing_fetch_response_with_retries",
        fake_fetch_response,
    )
    get_settings.cache_clear()
    try:
        fetcher = CompanyFilingFetcher()
        documents, errors = asyncio.run(
            fetcher.fetch_structured_api_documents(
                "2330",
                "台積電",
                document_types=["investor_presentation"],
            )
        )
    finally:
        get_settings.cache_clear()

    assert documents == []
    assert errors[0]["category"] == "structured_api_no_convertible_rows"
    assert "ticker_or_company_mention" in errors[0]["error"]
    diagnostics = fetcher.last_structured_api_contract_diagnostics
    assert diagnostics["row_container"] == "documents"
    assert diagnostics["object_row_count"] == 1
    assert diagnostics["convertible_document_count"] == 0
    assert diagnostics["row_error_count"] == 1


def test_structured_api_row_to_document_accepts_provider_alias_fields() -> None:
    row = {
        "headline": "2026 Q2 earnings materials",
        "abstract": "AI/HPC demand, capital expenditure, and supply chain capacity planning update.",
        "stock_id": "2330",
        "companyName": "台積電",
        "doc_type": "法說會簡報",
        "file": {"url": "https://api.tej.example/download/2330-q2.pdf"},
        "source": {"publisher": "TEJ"},
        "report_date": "2026-05-01T09:30:00+08:00",
    }

    document = CompanyFilingFetcher()._structured_api_row_to_document(
        row,
        ticker="2330",
        company_name="台積電",
        provider="tej",
        document_types=["investor_presentation"],
    )

    assert document is not None
    assert document.document_type == "investor_presentation"
    assert document.source.url == "https://api.tej.example/download/2330-q2.pdf"
    assert document.source.publisher == "TEJ"
    assert document.source.published_at == date(2026, 5, 1)
    assert "Structured API metadata" in document.text
    assert "2330" in document.text
    assert "investor presentation" in document.text


def test_company_filing_discovery_uses_structured_api_fallback(monkeypatch) -> None:
    captured = {}
    token = "tej-" + "token"

    class FakeAsyncClient:
        def __init__(self, **options) -> None:
            captured["options"] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                request=request,
                json={
                    "documents": [
                        {
                            "title": "台積電 2026 法說會簡報",
                            "text": "2330 台積電 法說會 investor presentation 揭露 AI/HPC 需求與資本支出。"
                            * 4,
                            "url": "https://api.tej.example/documents/2330-presentation",
                            "publisher": "TEJ",
                            "published_at": "2026-05-01",
                            "document_type": "investor_presentation",
                        }
                    ]
                },
            )

    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_TOKEN", token)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        CompanyFilingFetcher, "google_news_urls", classmethod(lambda cls, *args, **kwargs: [])
    )
    get_settings.cache_clear()
    try:
        documents, errors = asyncio.run(
            CompanyFilingFetcher().fetch_discovery_documents(
                "2330",
                "台積電",
                document_types=["investor_presentation"],
            )
        )
    finally:
        get_settings.cache_clear()

    assert errors == []
    assert documents[0].document_type == "investor_presentation"
    assert documents[0].source.publisher == "TEJ"
    assert documents[0].source.published_at == date(2026, 5, 1)
    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.tej.example/filings"
    assert captured["kwargs"]["params"]["ticker"] == "2330"
    assert captured["kwargs"]["params"]["document_type"] == "investor_presentation"
    assert captured["kwargs"]["headers"]["Authorization"] == f"Bearer {token}"
