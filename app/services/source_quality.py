from __future__ import annotations

import re

from app.models.schemas import NewsDocument


LOW_QUALITY_INVESTOR_FORUM_MARKERS = (
    "股市爆料同學會",
    "爆料同學會",
    "散戶閒聊",
    "網友抱怨",
    "住套房",
    "一堆看新聞做股票",
    "討論區",
    "forum",
    "stock forum",
    "ptt",
    "dcard",
    "mobile01",
)

LOW_QUALITY_INVESTOR_FORUM_URL_MARKERS = (
    "cmoney.tw/forum",
    "/forum/",
    "/bbs/",
    "ptt.cc",
    "dcard.tw",
    "mobile01.com",
)

SOURCE_CREDIBILITY_WEIGHTS = {
    "official": 1.00,
    "established_news": 0.90,
    "market_data": 0.85,
    "industry_analysis": 0.75,
    "investment_blog": 0.55,
    "community": 0.35,
    "low_quality_forum": 0.0,
    "unknown": 0.65,
}

SOURCE_CREDIBILITY_LABELS = {
    "official": "官方/交易所",
    "established_news": "主流財經新聞",
    "market_data": "市場資料",
    "industry_analysis": "產業研究",
    "investment_blog": "投資網誌/自媒體",
    "community": "社群討論",
    "low_quality_forum": "低品質論壇",
    "unknown": "來源未分級",
}

NON_FORMAL_EVIDENCE_TIERS = {
    "investment_blog",
    "community",
    "low_quality_forum",
}

OFFICIAL_SOURCE_MARKERS = (
    "公開資訊觀測站",
    "mops",
    "twse",
    "tpex",
    "臺灣證券交易所",
    "台灣證券交易所",
    "證交所",
    "櫃買中心",
    "公司公告",
    "法人說明會",
    "investor relations",
    "ir.",
)

ESTABLISHED_NEWS_MARKERS = (
    "中央社",
    "cna",
    "經濟日報",
    "工商時報",
    "moneydj",
    "udn",
    "聯合新聞網",
    "自由財經",
    "自由時報",
    "鉅亨網",
    "cnyes",
    "news.cnyes.com",
    "nikkei",
    "reuters",
    "bloomberg",
    "trendforce",
    "digitimes",
    "商周",
    "今周刊",
    "財訊",
    "富聯網",
    "ftnn",
)

MARKET_DATA_SOURCE_MARKERS = (
    "finmind",
    "fugle",
    "taiwanstockprice",
    "taiwanstockmonthrevenue",
)

INDUSTRY_ANALYSIS_SOURCE_MARKERS = (
    "sinotrade",
    "豐雲學堂",
    "理財周刊",
    "優分析",
    "uanalyze",
    "moneydj理財網",
)

INVESTMENT_BLOG_SOURCE_MARKERS = (
    "cmoney投資網誌",
    "cmoney 投資網誌",
    "cmoney",
    "旺得富",
    "鉅亨號",
    "蕃新聞",
)


def is_low_quality_investor_forum_text(text: str) -> bool:
    normalized = (text or "").lower()
    return any(marker.lower() in normalized for marker in LOW_QUALITY_INVESTOR_FORUM_MARKERS)


def is_low_quality_investor_forum_source(
    *,
    title: object = "",
    publisher: object = "",
    url: object = "",
    source_title: object = "",
    text: object = "",
) -> bool:
    haystack = " ".join(str(part or "") for part in (title, publisher, url, source_title, text))
    if is_low_quality_investor_forum_text(haystack):
        return True
    normalized_url = str(url or "").lower()
    return any(marker in normalized_url for marker in LOW_QUALITY_INVESTOR_FORUM_URL_MARKERS)


def is_low_quality_investor_forum_document(document: NewsDocument) -> bool:
    return is_low_quality_investor_forum_source(
        title=document.title,
        publisher=document.source.publisher,
        url=document.source.url,
        source_title=document.source.title,
        text=document.text,
    )


def is_formal_evidence_source(
    *,
    title: object = "",
    publisher: object = "",
    url: object = "",
    source_title: object = "",
    text: object = "",
) -> bool:
    return (
        source_credibility_tier(
            title=title,
            publisher=publisher,
            url=url,
            source_title=source_title,
            text=text,
        )
        not in NON_FORMAL_EVIDENCE_TIERS
    )


def is_formal_evidence_document(document: NewsDocument) -> bool:
    return is_formal_evidence_source(
        title=document.title,
        publisher=document.source.publisher,
        url=document.source.url,
        source_title=document.source.title,
        text=document.text,
    )


def filter_formal_evidence_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
    return [
        document
        for document in documents
        if is_formal_evidence_document(document)
    ]


def source_credibility_tier_for_document(document: NewsDocument) -> str:
    return source_credibility_tier(
        title=document.title,
        publisher=document.source.publisher,
        url=document.source.url,
        source_title=document.source.title,
        text=document.text,
    )


def source_credibility_tier(
    *,
    title: object = "",
    publisher: object = "",
    url: object = "",
    source_title: object = "",
    text: object = "",
) -> str:
    if is_low_quality_investor_forum_source(
        title=title,
        publisher=publisher,
        url=url,
        source_title=source_title,
        text=text,
    ):
        return "low_quality_forum"
    haystack = " ".join(str(part or "") for part in (title, publisher, url, source_title, text)).lower()
    if any(marker.lower() in haystack for marker in INVESTMENT_BLOG_SOURCE_MARKERS):
        return "investment_blog"
    if any(marker.lower() in haystack for marker in ("forum", "bbs", "討論區")):
        return "community"
    if any(marker.lower() in haystack for marker in OFFICIAL_SOURCE_MARKERS):
        return "official"
    if any(marker.lower() in haystack for marker in MARKET_DATA_SOURCE_MARKERS):
        return "market_data"
    if any(marker.lower() in haystack for marker in ESTABLISHED_NEWS_MARKERS):
        return "established_news"
    if any(marker.lower() in haystack for marker in INDUSTRY_ANALYSIS_SOURCE_MARKERS):
        return "industry_analysis"
    return "unknown"


def source_credibility_weight_for_document(document: NewsDocument) -> float:
    return SOURCE_CREDIBILITY_WEIGHTS[source_credibility_tier_for_document(document)]


def summarize_source_credibility(documents: list[NewsDocument]) -> dict:
    if not documents:
        return {
            "average_weight": None,
            "high_credibility_count": 0,
            "low_credibility_count": 0,
            "high_credibility_ratio": None,
            "low_credibility_ratio": None,
            "tier_counts": {},
        }
    tier_counts: dict[str, int] = {}
    weights = []
    for document in documents:
        tier = source_credibility_tier_for_document(document)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        weights.append(SOURCE_CREDIBILITY_WEIGHTS[tier])
    high_tiers = {"official", "established_news", "market_data"}
    low_tiers = {"investment_blog", "community", "low_quality_forum"}
    high_count = sum(count for tier, count in tier_counts.items() if tier in high_tiers)
    low_count = sum(count for tier, count in tier_counts.items() if tier in low_tiers)
    total = len(documents)
    return {
        "average_weight": sum(weights) / total,
        "high_credibility_count": high_count,
        "low_credibility_count": low_count,
        "high_credibility_ratio": high_count / total,
        "low_credibility_ratio": low_count / total,
        "tier_counts": tier_counts,
    }


def remove_low_quality_investor_forum_lines(text: str) -> str:
    return "\n".join(
        cleaned
        for line in str(text or "").splitlines()
        if (cleaned := remove_low_quality_investor_forum_fragments(line)).strip()
    )


def remove_low_quality_investor_forum_fragments(line: str) -> str:
    if is_formal_evidence_source(text=line, url=line):
        return line
    if _is_markdown_table_row(line):
        return _sanitize_markdown_table_row(line)
    return ""


def _is_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _sanitize_markdown_table_row(line: str) -> str:
    parts = line.split("|")
    inner = parts[1:-1]
    if not inner:
        return ""

    removed_any = False
    sanitized = []
    for cell in inner:
        cleaned_cell, removed = _sanitize_source_fragments(cell)
        sanitized.append(cleaned_cell)
        removed_any = removed_any or removed

    if removed_any and len(sanitized) >= 5:
        latest_from_sources = _latest_date_from_text(sanitized[-1])
        if latest_from_sources:
            sanitized[-2] = f" {latest_from_sources} "
        if not sanitized[-1].strip():
            sanitized[-1] = " 低品質散戶論壇來源已移除；目前無足夠正式代表來源。 "

    return "|".join([parts[0], *sanitized, parts[-1]])


def _sanitize_source_fragments(cell: str) -> tuple[str, bool]:
    if is_formal_evidence_source(text=cell, url=cell):
        return cell, False
    leading = re.match(r"^\s*", cell).group(0)
    trailing = re.search(r"\s*$", cell).group(0)
    fragments = _source_fragments(cell)
    kept = [
        fragment
        for fragment in fragments
        if fragment and is_formal_evidence_source(text=fragment, url=fragment)
    ]
    return leading + "；".join(kept) + trailing, len(kept) != len([fragment for fragment in fragments if fragment])


def _source_fragments(cell: str) -> list[str]:
    stripped = cell.strip()
    fragments = [fragment.strip() for fragment in re.split(r"\s*[；;]\s*", stripped)]
    if len([fragment for fragment in fragments if fragment]) > 1:
        return fragments
    if "、" in stripped and _looks_like_compact_source_summary(stripped):
        return [fragment.strip() for fragment in re.split(r"\s*、\s*", stripped)]
    return fragments


def _looks_like_compact_source_summary(text: str) -> bool:
    source_markers = [
        *OFFICIAL_SOURCE_MARKERS,
        *ESTABLISHED_NEWS_MARKERS,
        *INDUSTRY_ANALYSIS_SOURCE_MARKERS,
        *INVESTMENT_BLOG_SOURCE_MARKERS,
        "CMoney",
    ]
    normalized = text.lower()
    return sum(1 for marker in source_markers if marker.lower() in normalized) >= 2


def _latest_date_from_text(text: str) -> str | None:
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text or "")
    return max(dates) if dates else None
