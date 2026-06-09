from __future__ import annotations

import json
import re

from app.models.schemas import NewsDocument
from app.rag.keyword_reranker import document_text


def llm_rerank_prompt(query: str, documents: list[NewsDocument], *, text_limit: int) -> str:
    rows = []
    for index, document in enumerate(documents):
        source = document.source
        rows.append(
            {
                "index": index,
                "title": document.title,
                "publisher": source.publisher,
                "date": source.published_at.isoformat() if source.published_at else None,
                "text": document_text(document, text_limit),
            }
        )
    return (
        "你是 RAG 檢索重排序器。請依照查詢與文件內容的直接相關性、公司/股票代號精準命中、"
        "來源品質與日期新鮮度，將文件由最相關排到最不相關。\n"
        "只輸出 JSON 陣列，內容是文件 index，例如 [2,0,1]；不要輸出解釋文字。\n"
        f"查詢：{query}\n"
        f"文件：{json.dumps(rows, ensure_ascii=False)}"
    )


def parse_llm_ranked_indexes(text: str, document_count: int) -> list[int]:
    match = re.search(r"\[[\s\d,]+\]", str(text or ""))
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    indexes: list[int] = []
    for value in parsed:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= index < document_count:
            indexes.append(index)
    return indexes


def apply_llm_ranked_indexes(
    candidates: list[NewsDocument],
    remainder: list[NewsDocument],
    indexes: list[int],
    n_results: int,
) -> list[NewsDocument]:
    seen = set()
    ordered: list[NewsDocument] = []
    for index in indexes:
        if index in seen or not 0 <= index < len(candidates):
            continue
        seen.add(index)
        ordered.append(candidates[index])
    ordered.extend(document for index, document in enumerate(candidates) if index not in seen)
    ordered.extend(remainder)
    return ordered[:n_results]
