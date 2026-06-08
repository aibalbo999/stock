from app.services import company_filing_results, ingestion


def test_ingestion_reexports_company_filing_result_helpers() -> None:
    helper_names = [
        "classify_company_filing_error",
        "company_filing_attempt_result",
        "company_filing_error_category_counts",
        "company_filing_error_is_retryable",
        "company_filing_gap_summary",
        "company_filing_next_action_type",
        "company_filing_next_actions",
        "company_filing_next_step",
        "company_filing_status",
        "company_filing_ticker_result",
        "enrich_company_filing_errors",
        "missing_company_filing_document_types",
        "normalize_company_filing_error_category",
        "should_broaden_company_filing_search",
        "should_retry_company_filing_fetch",
    ]

    for name in helper_names:
        assert getattr(ingestion, name) is getattr(company_filing_results, name)
