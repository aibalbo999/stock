from __future__ import annotations

import importlib
from io import BytesIO
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.data_sources.news import NewsFetcher


PDF_PARSER_PROVENANCE_PREFIX = "[PDF 解析資訊]"
PDF_IMPORT_MISSING_PYPDF_MESSAGE = "PDF 匯入需要安裝 pypdf，請先完成系統相依套件安裝後再重試。"
PDF_IMPORT_MISSING_PDFPLUMBER_MESSAGE = "PDF 匯入設定為 pdfplumber，但尚未安裝 pdfplumber；請安裝 PDF 額外相依套件後再重試。"
PDF_IMPORT_MISSING_UNSTRUCTURED_MESSAGE = "PDF 匯入設定為 unstructured，但尚未安裝 unstructured[pdf]；請安裝 PDF 額外相依套件後再重試。"
PDF_IMPORT_MISSING_PYMUPDF_MESSAGE = "PDF 匯入設定為 pymupdf，但尚未安裝 PyMuPDF；請安裝 PDF/Visual RAG 額外相依套件後再重試。"
PDF_IMPORT_PARSE_ERROR_MESSAGE = "PDF 公司文件無法解析，可能是檔案加密、損毀或格式不支援；請改用官方 HTML 頁面，或人工貼上文字版內容。"
PDF_IMPORT_NO_TEXT_MESSAGE = "PDF 公司文件沒有可抽取文字，可能是掃描圖檔；請先 OCR 成文字後再貼上，或改用官方 HTML/文字版文件。"
MAX_PDF_TABLES_PER_DOCUMENT = 80
MAX_HTML_TABLES_PER_DOCUMENT = 80
MAX_PDF_TABLE_ROWS = 120
MAX_PDF_TABLE_COLUMNS = 14
MAX_PDF_TABLE_CELL_CHARS = 160


def is_pdf_response(url: str, content_type: str) -> bool:
    return "application/pdf" in content_type or urlparse(url).path.lower().endswith(".pdf")


def extract_company_filing_html_text(soup: BeautifulSoup) -> str:
    article_text = NewsFetcher._article_text(soup).strip()
    if not get_settings().company_filing_html_extract_tables:
        return article_text
    table_blocks = _format_html_tables(soup)
    if not table_blocks:
        return article_text
    parts = [article_text] if article_text else []
    parts.extend(table_blocks)
    return "\n\n".join(parts)


def pdf_title_from_url(url: str) -> str:
    name = urlparse(url).path.rsplit("/", 1)[-1]
    return name or url


def extract_pdf_text(content: bytes) -> str:
    parser = get_settings().company_filing_pdf_parser.strip().lower() or "auto"
    try:
        if parser == "auto":
            text = _extract_pdf_text_auto(content)
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
        if parser == "pdfplumber":
            text = _with_pdf_parser_provenance(
                _extract_pdf_text_with_pdfplumber(content),
                parser="pdfplumber",
            )
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
        if parser == "unstructured":
            text = _with_pdf_parser_provenance(
                _extract_pdf_text_with_unstructured(content),
                parser="unstructured",
            )
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
        if parser == "pymupdf":
            text = _with_pdf_parser_provenance(
                _extract_pdf_text_with_pymupdf(content),
                parser="pymupdf",
            )
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
        if parser == "pypdf":
            text = _with_pdf_parser_provenance(
                _extract_pdf_text_with_pypdf(content),
                parser="pypdf",
            )
            return _maybe_augment_pdf_text_with_visual_rag(content, text)
    except ImportError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError as exc:
        visual_text = _extract_pdf_text_with_visual_rag_fallback(content, exc)
        if visual_text:
            return visual_text
        raise
    raise ValueError(f"unsupported company filing PDF parser: {parser}")


def _extract_pdf_text_auto(content: bytes) -> str:
    last_error: ValueError | None = None
    for parser_name, extractor in (
        ("pdfplumber", _extract_pdf_text_with_pdfplumber),
        ("unstructured", _extract_pdf_text_with_unstructured),
        ("pymupdf", _extract_pdf_text_with_pymupdf),
        ("pypdf", _extract_pdf_text_with_pypdf),
    ):
        try:
            return _with_pdf_parser_provenance(
                extractor(content),
                parser=parser_name,
                auto=True,
            )
        except ImportError:
            continue
        except ValueError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise ValueError(PDF_IMPORT_MISSING_PYPDF_MESSAGE)


def _extract_pdf_text_with_visual_rag_fallback(content: bytes, error: ValueError) -> str:
    if not _should_try_visual_rag_pdf_fallback(error):
        return ""
    from app.services.visual_rag import extract_visual_pdf_text

    try:
        return extract_visual_pdf_text(content, reason=str(error))
    except Exception as exc:
        raise ValueError(f"{error}；Visual RAG 後援失敗：{exc}") from exc


def _maybe_augment_pdf_text_with_visual_rag(content: bytes, text: str) -> str:
    from app.services.visual_rag import maybe_augment_pdf_text_with_visual_rag

    return maybe_augment_pdf_text_with_visual_rag(content, text)


def _should_try_visual_rag_pdf_fallback(error: ValueError) -> bool:
    from app.services.visual_rag import visual_rag_fallback_enabled

    if not visual_rag_fallback_enabled():
        return False
    message = str(error)
    return (
        PDF_IMPORT_NO_TEXT_MESSAGE in message
        or PDF_IMPORT_PARSE_ERROR_MESSAGE in message
        or "沒有可抽取文字" in message
        or "掃描" in message
    )


def _with_pdf_parser_provenance(text: str, parser: str, auto: bool = False) -> str:
    extract_tables = get_settings().company_filing_pdf_extract_tables
    mode = "auto" if auto else "configured"
    marker = (
        f"{PDF_PARSER_PROVENANCE_PREFIX} parser={parser}; mode={mode}; "
        f"extract_tables={str(bool(extract_tables)).lower()}"
    )
    if text.startswith(PDF_PARSER_PROVENANCE_PREFIX):
        return text
    return f"{marker}\n{text}"


def _extract_pdf_text_with_pypdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import DependencyError
    except ImportError as exc:
        raise ValueError(PDF_IMPORT_MISSING_PYPDF_MESSAGE) from exc
    try:
        reader = PdfReader(BytesIO(content))
        if getattr(reader, "is_encrypted", False):
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
    except DependencyError as exc:
        raise ValueError("PDF 公司文件使用加密格式，請安裝 cryptography 後再重試解析。") from exc
    except Exception as exc:
        raise ValueError(PDF_IMPORT_PARSE_ERROR_MESSAGE) from exc
    text = "\n".join(page.strip() for page in pages if page.strip())
    if not text.strip():
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)
    return text


def _extract_pdf_text_with_pdfplumber(content: bytes) -> str:
    try:
        pdfplumber = importlib.import_module("pdfplumber")
    except ImportError as exc:
        raise ImportError(PDF_IMPORT_MISSING_PDFPLUMBER_MESSAGE) from exc

    try:
        parts: list[str] = []
        table_count = 0
        table_limit_reached = False
        with pdfplumber.open(BytesIO(content)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    parts.append(page_text)
                if get_settings().company_filing_pdf_extract_tables:
                    for table_index, table in enumerate(page.extract_tables() or [], start=1):
                        if table_count >= MAX_PDF_TABLES_PER_DOCUMENT:
                            table_limit_reached = True
                            continue
                        table_text = _format_pdf_table(table, page_index, table_index)
                        if table_text:
                            table_count += 1
                            parts.append(table_text)
        if table_limit_reached:
            parts.append(
                f"[PDF 表格抽取限制] 表格超過 {MAX_PDF_TABLES_PER_DOCUMENT} 個，"
                "僅保留前段可檢索表格文字。"
            )
    except Exception as exc:
        raise ValueError(PDF_IMPORT_PARSE_ERROR_MESSAGE) from exc

    return _validated_pdf_text("\n\n".join(parts))


def _extract_pdf_text_with_unstructured(content: bytes) -> str:
    try:
        partition_pdf = importlib.import_module("unstructured.partition.pdf").partition_pdf
    except ImportError as exc:
        raise ImportError(PDF_IMPORT_MISSING_UNSTRUCTURED_MESSAGE) from exc

    extract_tables = get_settings().company_filing_pdf_extract_tables
    try:
        elements = partition_pdf(file=BytesIO(content), infer_table_structure=extract_tables)
    except Exception as exc:
        raise ValueError(PDF_IMPORT_PARSE_ERROR_MESSAGE) from exc

    parts = []
    table_count = 0
    table_limit_reached = False
    for element in elements:
        text = str(element).strip()
        category = str(getattr(element, "category", "") or element.__class__.__name__).lower()
        metadata = getattr(element, "metadata", None)
        table_html = str(getattr(metadata, "text_as_html", "") or "")
        if "table" in category:
            if extract_tables:
                if table_count >= MAX_PDF_TABLES_PER_DOCUMENT:
                    table_limit_reached = True
                    continue
                table_text = _format_unstructured_pdf_table(text, table_html, metadata, table_count + 1)
                if table_text:
                    table_count += 1
                    parts.append(table_text)
                    continue
            elif text:
                parts.append(text)
                continue
        if text:
            parts.append(text)
    if table_limit_reached:
        parts.append(
            f"[PDF 表格抽取限制] 表格超過 {MAX_PDF_TABLES_PER_DOCUMENT} 個，"
            "僅保留前段可檢索表格文字。"
        )
    return _validated_pdf_text("\n\n".join(parts))


def _extract_pdf_text_with_pymupdf(content: bytes) -> str:
    try:
        fitz = _import_pymupdf()
    except ImportError as exc:
        raise ImportError(PDF_IMPORT_MISSING_PYMUPDF_MESSAGE) from exc

    document = None
    try:
        document = fitz.open(stream=content, filetype="pdf")
        pages = []
        for page in document:
            page_text = (page.get_text("text") or "").strip()
            if page_text:
                pages.append(page_text)
    except Exception as exc:
        raise ValueError(PDF_IMPORT_PARSE_ERROR_MESSAGE) from exc
    finally:
        close = getattr(document, "close", None)
        if callable(close):
            close()
    return _validated_pdf_text("\n\n".join(pages))


def _import_pymupdf():
    try:
        return importlib.import_module("fitz")
    except ImportError:
        return importlib.import_module("pymupdf")


def _validated_pdf_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError(PDF_IMPORT_NO_TEXT_MESSAGE)
    return text


def _format_pdf_table(table: list[list[object]], page_index: int, table_index: int) -> str:
    rows = []
    for row in table or []:
        cells = [_clean_pdf_table_cell(cell) for cell in (row or [])]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    raw_row_count = len(rows)
    raw_column_count = max(len(row) for row in rows)
    max_columns = min(raw_column_count, MAX_PDF_TABLE_COLUMNS)
    truncated_rows = rows[:MAX_PDF_TABLE_ROWS]
    normalized = [
        (row[:max_columns] + [""] * (max_columns - len(row[:max_columns])))
        for row in truncated_rows
    ]
    lines = [f"[PDF 表格抽取 p.{page_index} #{table_index}]"]
    lines.append(f"表格尺寸：{raw_row_count} 列 x {raw_column_count} 欄")
    if raw_row_count > MAX_PDF_TABLE_ROWS or raw_column_count > MAX_PDF_TABLE_COLUMNS:
        lines.append(
            f"表格已截斷：保留前 {min(raw_row_count, MAX_PDF_TABLE_ROWS)} 列、"
            f"前 {min(raw_column_count, MAX_PDF_TABLE_COLUMNS)} 欄。"
        )
    lines.extend(" | ".join(row).strip() for row in normalized)
    return "\n".join(line for line in lines if line.strip())


def _format_unstructured_pdf_table(
    text: str,
    table_html: str,
    metadata: object,
    table_index: int,
) -> str:
    table_text = _html_table_to_text(table_html) if table_html else text.strip()
    if not table_text:
        return ""
    page_number = getattr(metadata, "page_number", None)
    page_label = f" p.{page_number}" if page_number else ""
    return f"[PDF 表格抽取{page_label} #{table_index}]\n{table_text}"


def _html_table_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    for table_row in soup.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in table_row.find_all(["th", "td"])
        ]
        if any(cells):
            rows.append(" | ".join(cells))
    if rows:
        return "\n".join(rows)
    return soup.get_text(" ", strip=True)


def _format_html_tables(soup: BeautifulSoup) -> list[str]:
    blocks = []
    limit_reached = False
    for table in soup.find_all("table"):
        if len(blocks) >= MAX_HTML_TABLES_PER_DOCUMENT:
            limit_reached = True
            break
        block = _format_html_table(table, len(blocks) + 1)
        if block:
            blocks.append(block)
    if limit_reached:
        blocks.append(
            f"[HTML 表格抽取限制] 表格超過 {MAX_HTML_TABLES_PER_DOCUMENT} 個，"
            "僅保留前段可檢索表格文字。"
        )
    return blocks


def _format_html_table(table: object, table_index: int) -> str:
    rows = []
    for table_row in table.find_all("tr"):
        cells = [
            _clean_pdf_table_cell(cell.get_text(" ", strip=True))
            for cell in table_row.find_all(["th", "td"])
        ]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    raw_row_count = len(rows)
    raw_column_count = max(len(row) for row in rows)
    max_columns = min(raw_column_count, MAX_PDF_TABLE_COLUMNS)
    truncated_rows = rows[:MAX_PDF_TABLE_ROWS]
    normalized = [
        row[:max_columns] + [""] * (max_columns - len(row[:max_columns]))
        for row in truncated_rows
    ]
    lines = [f"[HTML 表格抽取 #{table_index}]"]
    lines.append(f"表格尺寸：{raw_row_count} 列 x {raw_column_count} 欄")
    if raw_row_count > MAX_PDF_TABLE_ROWS or raw_column_count > MAX_PDF_TABLE_COLUMNS:
        lines.append(
            f"表格已截斷：保留前 {min(raw_row_count, MAX_PDF_TABLE_ROWS)} 列、"
            f"前 {min(raw_column_count, MAX_PDF_TABLE_COLUMNS)} 欄。"
        )
    lines.extend(" | ".join(row).strip() for row in normalized)
    return "\n".join(line for line in lines if line.strip())


def _clean_pdf_table_cell(value: object) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()
    if len(cleaned) > MAX_PDF_TABLE_CELL_CHARS:
        return cleaned[: MAX_PDF_TABLE_CELL_CHARS - 3] + "..."
    return cleaned
