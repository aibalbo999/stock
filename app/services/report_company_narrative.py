from __future__ import annotations

from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, NewsDocument, ValuationMetric
from app.services.leading_signals import LeadingSignal
from app.services.report_quality import is_stale_market_data_source


def company_evidence_summary(related_documents: list[NewsDocument], related_findings) -> str:
    if not related_documents and not related_findings:
        return "目前沒有足夠公司層級文本或主題/風險歸因證據。"
    return f"目前有 {len(related_documents)} 筆公司相關文本、{len(related_findings)} 筆主題/風險歸因證據。"


def company_filing_evidence_summary(related_documents: list[NewsDocument]) -> str:
    filing_documents = [document for document in related_documents if document.id.startswith("filing-")]
    if not filing_documents:
        return "尚未取得足夠官方公開文件，因此收入拆分仍以外部資料與財報科目輔助判斷。"
    types = sorted({news_document_filing_type(document) or "company_disclosure" for document in filing_documents})
    publishers = sorted({document.source.publisher or "公開文件" for document in filing_documents})
    return (
        f"已納入 {len(filing_documents)} 份官方/公司公開文件"
        f"（{', '.join(types[:3])}；來源：{', '.join(publishers[:2])}），"
        "可用來校正商業模式、風險與財務敘述。"
    )


def company_revenue_summary(revenue: MonthlyRevenue | None) -> str:
    if not revenue:
        return "目前無月營收資料，無法判斷近期營收動能。"
    yoy = f"{revenue.yoy_pct:.2f}%" if revenue.yoy_pct is not None else "無去年同期可比資料"
    return f"{revenue.revenue_year}-{revenue.revenue_month:02d} 月營收 {revenue.revenue:,}，年增率 {yoy}。"


def company_quick_take(
    snapshot: MarketSnapshot | None,
    revenue: MonthlyRevenue | None,
    financial_metrics: list[FinancialMetric],
    valuation: ValuationMetric | None,
    related_documents: list[NewsDocument],
    related_findings,
) -> str:
    strengths = []
    cautions = []
    if related_documents:
        strengths.append(f"有 {len(related_documents)} 筆公司相關文本")
    else:
        cautions.append("缺公司層級新聞/研究證據")
    if revenue and revenue.yoy_pct is not None:
        if revenue.yoy_pct >= 20:
            strengths.append(f"月營收年增 {revenue.yoy_pct:.2f}%")
        elif revenue.yoy_pct < 0:
            cautions.append(f"月營收年減 {abs(revenue.yoy_pct):.2f}%")
    else:
        cautions.append("缺月營收年增率")
    if valuation and valuation.pe_ratio is not None:
        strengths.append(f"P/E {valuation.pe_ratio:.2f}")
    else:
        cautions.append("缺估值倍數")
    if not financial_metrics:
        cautions.append("缺已揭露年度財報資料")
    if related_findings:
        cautions.append(f"需追蹤 {len(related_findings)} 筆風險/機會歸因")
    if not snapshot:
        cautions.append("缺最新股價")
    strength_text = "、".join(strengths[:3]) if strengths else "目前無明確加分訊號"
    caution_text = "、".join(cautions[:3]) if cautions else "暫無重大資料缺口"
    return f"{strength_text}；主要檢查點：{caution_text}。"


def group_financial_metrics(metrics: list[FinancialMetric]) -> dict[str, list[FinancialMetric]]:
    grouped: dict[str, list[FinancialMetric]] = {}
    for metric in metrics:
        grouped.setdefault(metric.ticker, []).append(metric)
    return grouped


def valuation_summary(
    valuation: ValuationMetric | None,
    peer_summary: dict[str, float | None] | None = None,
) -> str:
    if not valuation:
        return "目前無足夠數據判斷；缺 P/E、P/B 與殖利率資料。"
    pe = f"P/E {valuation.pe_ratio:.2f}" if valuation.pe_ratio is not None else "P/E NA"
    pb = f"P/B {valuation.pb_ratio:.2f}" if valuation.pb_ratio is not None else "P/B NA"
    dividend = (
        f"殖利率 {valuation.dividend_yield:.2f}%"
        if valuation.dividend_yield is not None
        else "殖利率 NA"
    )
    comparison = valuation_peer_comparison(valuation, peer_summary or {})
    return f"{valuation.trade_date.isoformat()} {pe}、{pb}、{dividend}。{comparison}"


def valuation_peer_comparison(
    valuation: ValuationMetric,
    peer_summary: dict[str, float | None],
) -> str:
    pe_avg = peer_summary.get("pe_avg")
    pb_avg = peer_summary.get("pb_avg")
    count = int(peer_summary.get("count") or 0)
    if count < 2 or (pe_avg is None and pb_avg is None):
        return "同業樣本不足，無法做相對估值比較。"
    parts = []
    if valuation.pe_ratio is not None and pe_avg:
        level = "高於" if valuation.pe_ratio > pe_avg * 1.1 else "低於" if valuation.pe_ratio < pe_avg * 0.9 else "接近"
        parts.append(f"P/E {level}同業平均 {pe_avg:.2f}")
    if valuation.pb_ratio is not None and pb_avg:
        level = "高於" if valuation.pb_ratio > pb_avg * 1.1 else "低於" if valuation.pb_ratio < pb_avg * 0.9 else "接近"
        parts.append(f"P/B {level}同業平均 {pb_avg:.2f}")
    return "目前相對估值：" + "；".join(parts) + "。"


def sanitize_leading_signal_for_profitability(
    signal: LeadingSignal,
    has_negative_profitability: bool,
) -> LeadingSignal:
    if not has_negative_profitability or signal.valuation_label != "目前估值低於同業":
        return signal
    bullish_factors = [factor for factor in signal.bullish_factors if factor != "目前估值低於同業"]
    upside_bonus = max(0, signal.upside_bonus - 2)
    return LeadingSignal(
        ticker=signal.ticker,
        score=upside_bonus - signal.downside_penalty,
        upside_bonus=upside_bonus,
        downside_penalty=signal.downside_penalty,
        price_20d_pct=signal.price_20d_pct,
        price_60d_pct=signal.price_60d_pct,
        volume_ratio_20d=signal.volume_ratio_20d,
        revenue_yoy_pct=signal.revenue_yoy_pct,
        revenue_acceleration_pct=signal.revenue_acceleration_pct,
        valuation_label="獲利為負，不判低估",
        bullish_factors=bullish_factors,
        bearish_factors=signal.bearish_factors,
        neutral_factors=signal.neutral_factors,
    )


def financial_confidence_label(
    financial_metrics: list[FinancialMetric],
    valuation: ValuationMetric | None,
    revenue: MonthlyRevenue | None,
) -> str:
    score = 0
    has_stale_inputs = any(is_stale_market_data_source(metric.source) for metric in financial_metrics)
    if len(financial_metrics) >= 8:
        score += 1
    if len(financial_metrics) >= 40:
        score += 1
    if valuation:
        score += 1
        has_stale_inputs = has_stale_inputs or is_stale_market_data_source(valuation.source)
    if revenue:
        score += 1
        has_stale_inputs = has_stale_inputs or is_stale_market_data_source(revenue.source)
    if has_stale_inputs:
        score = max(0, score - 1)
    if score >= 4:
        return "高"
    if score >= 2:
        return "中"
    return "低"


def company_market_summary(snapshot: MarketSnapshot | None) -> str:
    if not snapshot:
        return "目前無可驗證股價資料。"
    close = snapshot.close if snapshot.close is not None else "NA"
    return f"{snapshot.trade_date.isoformat()} 收盤價 {close}。"


def filing_type_label(document_type: str) -> str:
    labels = {
        "annual_report": "年報",
        "investor_presentation": "法說會簡報",
        "prospectus": "公開說明書",
        "material_information": "重大訊息",
        "company_disclosure": "公司公告",
    }
    return labels.get(document_type, document_type)


def news_document_filing_type(document: NewsDocument) -> str | None:
    for line in document.text.splitlines():
        if line.startswith("文件類型："):
            return line.split("：", 1)[1].strip()
    return None
