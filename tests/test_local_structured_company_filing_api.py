from __future__ import annotations

import json
import threading
from urllib.parse import urlencode
from urllib.request import urlopen

from scripts import local_structured_company_filing_api as fixture


def _sample_payload() -> dict:
    return {
        "documents": [
            {
                "title": "2330 台積電 2026 法說會簡報",
                "text": "2330 台積電 法說會 investor presentation 揭露 AI/HPC 需求與資本支出。",
                "url": "https://api.example.test/documents/2330-presentation.pdf",
                "publisher": "Local fixture",
                "published_at": "2026-05-01",
                "document_type": "investor_presentation",
            },
            {
                "title": "2382 廣達 重大訊息",
                "text": "2382 廣達 重大訊息 material information。",
                "url": "https://api.example.test/documents/2382-material",
                "publisher": "Local fixture",
                "published_at": "2026-05-02",
                "document_type": "material_information",
            },
        ]
    }


def test_local_structured_company_filing_response_filters_company_and_document_type() -> None:
    response = fixture.local_structured_company_filing_response(
        _sample_payload(),
        ticker="2330",
        company_name="台積電",
        document_types=["investor_presentation"],
        limit=5,
        sample_json_path="examples/structured_company_filing_sample.json",
    )

    assert response["meta"]["mode"] == "local_structured_company_filing_fixture"
    assert response["meta"]["raw_row_count"] == 2
    assert response["meta"]["matched_row_count"] == 1
    assert response["meta"]["returned_row_count"] == 1
    assert response["documents"][0]["title"] == "2330 台積電 2026 法說會簡報"


def test_local_structured_company_filing_response_accepts_comma_document_types() -> None:
    response = fixture.local_structured_company_filing_response(
        _sample_payload(),
        ticker="2382",
        company_name="廣達",
        document_types=["annual_report,material_information"],
        limit=1,
    )

    assert response["meta"]["document_types"] == ["annual_report", "material_information"]
    assert response["documents"][0]["document_type"] == "material_information"


def test_local_structured_company_filing_http_handler_serves_health_and_filings(tmp_path) -> None:
    sample_path = tmp_path / "structured_api_sample.json"
    sample_path.write_text(json.dumps(_sample_payload(), ensure_ascii=False), encoding="utf-8")
    handler = fixture.make_handler(sample_json_path=sample_path, quiet=True)
    server = fixture.LocalStructuredCompanyFilingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with urlopen(f"http://{host}:{port}/health", timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
        query = urlencode(
            {
                "ticker": "2330",
                "company_name": "台積電",
                "document_type": "investor_presentation",
                "limit": "2",
            }
        )
        with urlopen(f"http://{host}:{port}/filings?{query}", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert health["ready"] is True
    assert health["api_path"] == "/filings"
    assert payload["meta"]["matched_row_count"] == 1
    assert payload["documents"][0]["publisher"] == "Local fixture"


def test_local_structured_company_filing_server_bind_skips_reverse_dns(tmp_path) -> None:
    sample_path = tmp_path / "structured_api_sample.json"
    sample_path.write_text(json.dumps(_sample_payload(), ensure_ascii=False), encoding="utf-8")
    handler = fixture.make_handler(sample_json_path=sample_path, quiet=True)
    server = fixture.LocalStructuredCompanyFilingHTTPServer(("127.0.0.1", 0), handler)
    try:
        assert server.server_name == "127.0.0.1"
        assert isinstance(server.server_port, int)
    finally:
        server.server_close()


def test_local_fixture_env_and_smoke_commands_point_to_custom_provider() -> None:
    env_lines = fixture.local_fixture_env_lines(host="127.0.0.1", port=8794, path="/filings")
    smoke_command = fixture.local_fixture_smoke_command(
        host="127.0.0.1",
        port=8794,
        path="/filings",
    )
    provider_profile_command = fixture.local_fixture_provider_profile_smoke_command(
        host="127.0.0.1",
        port=8794,
        path="/filings",
        provider_profile="tej",
    )

    assert env_lines == [
        "export COMPANY_FILING_STRUCTURED_API_PROVIDER=custom",
        "export COMPANY_FILING_STRUCTURED_API_URL=http://127.0.0.1:8794/filings",
        "unset COMPANY_FILING_STRUCTURED_API_TOKEN",
    ]
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom" in smoke_command
    assert "COMPANY_FILING_STRUCTURED_API_URL=http://127.0.0.1:8794/filings" in smoke_command
    assert "structured_company_filing_smoke.py" in smoke_command
    assert "structured_company_filing_fixture_smoke.py" in provider_profile_command
    assert "--provider-profile tej" in provider_profile_command
    assert "--host 127.0.0.1 --port 8794 --path /filings" in provider_profile_command
