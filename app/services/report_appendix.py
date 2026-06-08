from __future__ import annotations

from collections.abc import Callable

from app.models.schemas import MarketSnapshot, NewsDocument
from app.services.llm_analysis import LLMSupplementValidator
from app.services.llm_client import LLMResult
from app.services.report_source_references import ordered_source_documents, source_reference_line


SOURCE_APPENDIX_LIMIT = 80


def render_appendix(
    llm_result: LLMResult,
    documents: list[NewsDocument],
    market_snapshots: list[MarketSnapshot],
    *,
    tickers: list[str] | None = None,
    document_match_resolver: Callable[[NewsDocument], list],
    claim_ticker_resolver: Callable[[str], list],
    source_limit: int = SOURCE_APPENDIX_LIMIT,
) -> str:
    lines = ["### AI 補充分析"]
    if llm_result.fallback:
        lines.append("模型補充分析未啟用；本報告目前改用可追溯來源與資料規則生成，需人工覆核。")
    else:
        lines.append(
            LLMSupplementValidator.render_markdown(
                llm_result.text,
                documents,
                market_snapshots,
                news_ticker_resolver=lambda document: [
                    match.ticker for match in document_match_resolver(document)
                ],
                claim_ticker_resolver=lambda claim: [
                    match.ticker for match in claim_ticker_resolver(claim)
                ],
            )
        )

    lines.extend(["", "### 資料來源與時間戳記"])
    if documents:
        ordered_documents = ordered_source_documents(
            appendix_documents_for_tickers(
                documents,
                tickers,
                document_match_resolver=document_match_resolver,
            )
        )
        for document in ordered_documents[:source_limit]:
            lines.append(source_reference_line(document))
        if len(ordered_documents) > source_limit:
            lines.append(
                f"- 其餘 {len(ordered_documents) - source_limit} 筆來源已存入資料庫，"
                f"本報告僅列前 {source_limit} 筆。"
            )
    else:
        lines.append("- 目前無足夠數據判斷。")

    lines.extend(["", "### 模型狀態", model_status(llm_result)])
    return "\n".join(lines)


def appendix_documents_for_tickers(
    documents: list[NewsDocument],
    tickers: list[str] | None,
    *,
    document_match_resolver: Callable[[NewsDocument], list],
) -> list[NewsDocument]:
    target_tickers = {str(ticker) for ticker in tickers or [] if ticker}
    if not target_tickers:
        return documents
    matched_documents = []
    for document in documents:
        metadata_tickers = {ticker for ticker in document.entity_tickers if ticker}
        mapped_tickers = {match.ticker for match in document_match_resolver(document)}
        known_tickers = metadata_tickers or mapped_tickers
        if known_tickers and not known_tickers.isdisjoint(target_tickers):
            matched_documents.append(document)
    return matched_documents or documents


def model_status(result: LLMResult) -> str:
    if result.fallback:
        return result.text
    return f"Gemini 已啟用；model={result.model}；key_pool_index={result.key_index}"
