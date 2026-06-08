from __future__ import annotations

from collections import Counter

from app.models.schemas import RiskType


AI_INFRA_RISK_TERMS = {
    "CoWoS",
    "cowos",
    "HBM",
    "hbm",
    "先進封裝",
    "先進製程",
    "液冷",
    "水冷",
    "缺電",
}
AI_INFRA_CONTEXT_TERMS = {
    "AI 伺服器",
    "AI伺服器",
    "資料中心",
    "data center",
    "datacenter",
    "server",
    "伺服器",
    "晶圓",
    "半導體",
    "封裝",
    "CoWoS",
    "cowos",
    "HBM",
    "hbm",
    "PCB",
    "pcb",
    "載板",
    "ABF",
    "abf",
    "CCL",
    "ccl",
    "矽晶圓",
    "AI 晶片",
    "散熱",
    "液冷",
    "水冷",
    "CSP",
    "GPU",
}


def is_ai_infra_specific_risk_term(term: str) -> bool:
    lowered = term.lower()
    return any(marker.lower() == lowered or marker.lower() in lowered for marker in AI_INFRA_RISK_TERMS)


def company_allows_ai_infra_risk(ticker: str, whitelist) -> bool:
    companies = {company.ticker: company for company in whitelist.companies()}
    company = companies.get(ticker)
    segment = whitelist.segment_for_ticker(ticker)
    context = " ".join(
        [
            company.name if company else "",
            " ".join(company.evidence_keywords) if company else "",
            segment.name if segment else "",
            segment.notes or "" if segment else "",
        ]
    ).lower()
    return any(term.lower() in context for term in AI_INFRA_CONTEXT_TERMS)


def companies_allow_ai_infra_risk(tickers: list[str], whitelist) -> bool:
    if not tickers:
        return True
    return any(company_allows_ai_infra_risk(ticker, whitelist) for ticker in tickers)


def sanitize_risk_topic(topic: str, tickers: list[str] | None = None, *, whitelist=None) -> str:
    raw_parts = (
        str(topic or "")
        .replace("，", ",")
        .replace("、", ",")
        .replace("/", ",")
        .split(",")
    )
    parts = [part.strip() for part in raw_parts if part.strip()]
    if not parts:
        return "營運與供應鏈風險"
    allows_ai_infra = companies_allow_ai_infra_risk(tickers or [], whitelist) if whitelist is not None else True
    sanitized = [
        part
        for part in parts
        if allows_ai_infra or not is_ai_infra_specific_risk_term(part)
    ]
    if sanitized:
        return ", ".join(dict.fromkeys(sanitized))
    return "營運與供應鏈風險"


def finding_scope_companies(finding, scope_tickers: set[str] | None = None) -> list:
    companies = list(finding.related_companies)
    if not scope_tickers:
        return companies
    return [company for company in companies if company.ticker in scope_tickers]


def risk_findings_for_scope(findings, tickers: list[str] | None = None) -> list:
    scope_tickers = set(tickers or [])
    if not scope_tickers:
        return list(findings)
    scoped = []
    for finding in findings:
        if finding_scope_companies(finding, scope_tickers):
            scoped.append(finding)
    return scoped


def sanitized_risk_topic_for_finding(finding, whitelist) -> str:
    return sanitize_risk_topic(
        finding.topic,
        [company.ticker for company in finding.related_companies],
        whitelist=whitelist,
    )


def render_risk_overview(findings, tickers: list[str] | None = None, *, whitelist) -> str:
    scoped_findings = risk_findings_for_scope(findings, tickers)
    if not scoped_findings:
        return "目前無足夠數據判斷。"

    scope_tickers = set(tickers or [])
    topic_counts = Counter(sanitized_risk_topic_for_finding(finding, whitelist) for finding in scoped_findings)
    company_counts: Counter[str] = Counter()
    for finding in scoped_findings:
        for company in finding_scope_companies(finding, scope_tickers):
            company_counts[f"{company.ticker} {company.name}"] += 1

    lines = [
        f"- 結構性瓶頸：{sum(1 for finding in scoped_findings if finding.risk_type == RiskType.structural_bottleneck)} 筆",
        f"- 短期波動：{sum(1 for finding in scoped_findings if finding.risk_type == RiskType.short_term_volatility)} 筆",
        f"- 機會/成長：{sum(1 for finding in scoped_findings if finding.risk_type == RiskType.opportunity_or_growth)} 筆",
        "- 主要歸因主題："
        + ("、".join(f"{topic}({count})" for topic, count in topic_counts.most_common(5)) or "目前無足夠數據判斷"),
        "- 受影響公司："
        + ("、".join(f"{company}({count})" for company, count in company_counts.most_common(5)) or "未明確對應公司"),
        "",
        "### 代表性證據",
    ]
    for finding in scoped_findings[:8]:
        source_date = finding.source.published_at.isoformat() if finding.source.published_at else "日期不明"
        companies = (
            ", ".join(f"{company.ticker} {company.name}" for company in finding_scope_companies(finding, scope_tickers))
            or "未明確對應公司"
        )
        topic = sanitized_risk_topic_for_finding(finding, whitelist)
        lines.append(
            f"- {topic}：{companies}；來源：{source_date} "
            f"{finding.source.publisher or ''} {finding.source.title}"
        )
    if len(scoped_findings) > 8:
        lines.append(f"- 其餘 {len(scoped_findings) - 8} 筆歸因證據已保留於系統資料庫，不在主報告逐條展開。")
    return "\n".join(lines)
