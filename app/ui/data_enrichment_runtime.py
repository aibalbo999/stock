from __future__ import annotations

from app.services.company_filing_runtime_rows import (
    company_filing_runtime_rows as _company_filing_runtime_rows,
    company_filing_visual_rag_model_chain_rows as _company_filing_visual_rag_model_chain_rows,
)


def company_filing_runtime_rows(service_snapshot: dict) -> list[dict]:
    return _company_filing_runtime_rows(service_snapshot)


def company_filing_visual_rag_model_chain_rows(service_snapshot: dict) -> list[dict]:
    return _company_filing_visual_rag_model_chain_rows(service_snapshot)
