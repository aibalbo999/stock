from pathlib import Path


def test_upgrade_capability_matrix_delegates_to_domain_builders() -> None:
    service_status_source = Path("app/services/service_status.py").read_text()
    matrix_source = Path("app/services/status_capability_matrix.py").read_text()

    assert "from app.services.status_capability_matrix import (" in service_status_source
    assert "build_upgrade_capability_matrix(status)" in service_status_source
    assert "def _upgrade_capability_matrix(" not in service_status_source

    assert "def upgrade_capability_matrix(" in matrix_source
    assert "from app.services.status_api_architecture import api_controller_status" in matrix_source
    assert "from app.services.status_capability_ai_rag import ai_rag_capabilities" in matrix_source
    assert (
        "from app.services.status_capability_architecture import architecture_capabilities"
        in matrix_source
    )
    assert (
        "from app.services.status_capability_data_business import data_business_capabilities"
        in matrix_source
    )
    assert '"ai_rag": ai_rag_capabilities(' in matrix_source
    assert '"architecture": architecture_capabilities(' in matrix_source
    assert '"data_business_logic": data_business_capabilities(' in matrix_source


def test_upgrade_capability_matrix_keeps_domain_details_out_of_composition_root() -> None:
    service_status_source = Path("app/services/service_status.py").read_text()
    matrix_source = Path("app/services/status_capability_matrix.py").read_text()

    assert "def _api_controller_status(" not in service_status_source
    assert "def _api_controller_status(" not in matrix_source
    assert '"graphrag_live_cypher_query": _capability(' not in matrix_source
    assert '"streamlit_mpa_background_tasks": _capability(' not in matrix_source
    assert '"market_data_provider_fallback": _capability(' not in matrix_source
    assert "def _module_available(" not in matrix_source
    assert "def _capability(" not in matrix_source
    assert "from app.services.status_capability_helpers import" not in matrix_source


def test_upgrade_capability_domain_builders_own_their_detail_checks() -> None:
    api_architecture_source = Path("app/services/status_api_architecture.py").read_text()
    api_architecture_sources_source = Path(
        "app/services/status_api_architecture_sources.py"
    ).read_text()
    ai_rag_source = Path("app/services/status_capability_ai_rag.py").read_text()
    ai_rag_graphrag_source = Path(
        "app/services/status_capability_ai_rag_graphrag.py"
    ).read_text()
    architecture_source = Path("app/services/status_capability_architecture.py").read_text()
    data_business_source = Path("app/services/status_capability_data_business.py").read_text()
    data_business_filings_source = Path(
        "app/services/status_capability_data_business_filings.py"
    ).read_text()
    helpers_source = Path("app/services/status_capability_helpers.py").read_text()

    assert "def api_controller_status(" in api_architecture_source
    assert "api_architecture_source_context(" in api_architecture_source
    assert "def _read_source(" not in api_architecture_source
    assert api_architecture_source.count(".read_text(") == 0
    assert "def api_architecture_source_context(" in api_architecture_sources_source
    assert "def _literal_occurrence_locations(" in api_architecture_sources_source

    assert "def ai_rag_capabilities(" in ai_rag_source
    assert "graphrag_capabilities(graph_status=graph_status)" in ai_rag_source
    assert '"graphrag_live_cypher_query": _capability(' not in ai_rag_source
    assert "def graphrag_capabilities(" in ai_rag_graphrag_source
    assert '"graphrag_live_cypher_query": _capability(' in ai_rag_graphrag_source
    assert "from app.services.status_llm import _llm_fallback_readiness" in ai_rag_source
    assert "def _module_available(" in ai_rag_source

    assert "def architecture_capabilities(" in architecture_source
    assert '"streamlit_mpa_background_tasks": _capability(' in architecture_source

    assert "def data_business_capabilities(" in data_business_source
    assert '"market_data_provider_fallback": _capability(' in data_business_source
    assert "company_filing_capabilities(" in data_business_source
    assert '"company_filing_fetch_hardening": _capability(' not in data_business_source
    assert "def company_filing_capabilities(" in data_business_filings_source
    assert '"company_filing_fetch_hardening": _capability(' in data_business_filings_source
    assert (
        "from app.services.status_market_data import _market_data_provider_readiness"
        in data_business_source
    )

    assert "def capability(" in helpers_source


def test_status_capability_details_use_operator_language() -> None:
    source_by_path = {
        path: Path(path).read_text()
        for path in [
            "app/services/status_capability_ai_rag.py",
            "app/services/status_capability_ai_rag_graphrag.py",
            "app/services/status_capability_architecture.py",
            "app/services/status_capability_data_business_filings.py",
            "app/services/status_graphrag.py",
        ]
    }
    forbidden_phrases = [
        "Chroma uses an explicit multilingual/provider embedding function when enabled.",
        "LiteLLM / Google GenAI SDK path is selected",
        "Quota governance keeps the smartest configured report model first",
        "Ready only when a learned/API reranker is configured and available",
        "Local traces capture LLM latency",
        "Optional Visual RAG fallback/augmentation converts PDF pages to images",
        "GraphRAG context for structural upstream/downstream retrieval",
        "LLM-generated Cypher is supported through a guarded planner",
        "Ready means GraphRAG can produce parameterized Neo4j Cypher payloads",
        "External Neo4j import is ready only when URI, dependency, auth, and connection checks are available.",
        "FastAPI main is a thin app entry",
        "Background task implementation readiness covers Celery exports",
        "Streamlit uses a multi-page shell",
        "Secret scanning prefers external tools such as detect-secrets/gitleaks",
        "MOPS/TWSE/TPEx high-risk disclosure sources need an unlocker-grade",
        "Built-in TWSE/TPEx official OpenAPI fallback for daily material information rows.",
        "Optional paid/professional company filing source for investor presentations",
    ]

    combined_source = "\n".join(source_by_path.values())

    for phrase in forbidden_phrases:
        assert phrase not in combined_source
