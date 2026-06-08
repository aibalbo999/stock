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


def valuation_conclusion(
    snapshot: MarketSnapshot | None,
    valuation: ValuationMetric | None,
    peer_summary: dict[str, float | None] | None = None,
) -> str:
    market_summary = company_market_summary(snapshot)
    if not valuation:
        return f"{market_summary} 但缺 P/E、P/B、DCF 與同業估值資料，因此不能下低估/高估結論。"
    return (
        f"{market_summary} 已有單公司估值：{valuation_summary(valuation, peer_summary)}"
        "仍缺 DCF 與完整同業成長率，因此不能單靠倍數判斷低估/高估。"
    )


def trend_summary(related_documents: list[NewsDocument], related_findings) -> str:
    text = " ".join([document.title for document in related_documents] + [finding.evidence for finding in related_findings])
    if not text:
        return "目前無足夠數據判斷。"
    if any(term in text for term in ["AI", "伺服器", "CoWoS", "HBM", "液冷", "散熱", "成長", "擴產", "需求"]):
        return "現有文本顯示公司與本次主題需求有關，但仍需用訂單、營收與毛利率驗證。"
    return "現有文本不足以判斷明確產業趨勢。"


def near_term_outlook(
    revenue: MonthlyRevenue | None,
    related_documents: list[NewsDocument],
    related_findings,
) -> str:
    if related_findings:
        return "短期需優先追蹤風險證據是否擴大，以及月營收是否能支撐題材。"
    if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 0 and related_documents:
        return "短期具備觀察價值，但仍需確認成長是否延續到獲利與現金流。"
    if related_documents:
        return "短期已有題材文本，但缺少足夠財務驗證。"
    return "目前無足夠數據判斷。"


def growth_opportunity_text(
    related_documents: list[NewsDocument],
    related_findings,
    revenue: MonthlyRevenue | None,
) -> str:
    text = " ".join([document.title + " " + document.text[:300] for document in related_documents])
    signals = []
    for keyword in ["擴產", "新平台", "AI", "伺服器", "CoWoS", "HBM", "液冷", "訂單", "產能"]:
        if keyword in text:
            signals.append(keyword)
    if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
        signals.append(f"月營收年增 {revenue.yoy_pct:.2f}%")
    if related_findings:
        signals.append(f"{len(related_findings)} 筆主題/風險歸因證據")
    if not signals:
        return "目前沒有足夠可驗證訊號，需等待法說會、訂單或營收資料補強。"
    return "可追蹤 " + "、".join(list(dict.fromkeys(signals))[:5]) + " 是否延續到營收、毛利與現金流。"


def long_term_growth_text(
    financial_summary: dict[str, str],
    revenue: MonthlyRevenue | None,
    related_documents: list[NewsDocument],
) -> str:
    positives = []
    if "成長" in financial_summary.get("revenue_trend", ""):
        positives.append(financial_summary["revenue_trend"])
    if "體質改善" in financial_summary.get("strength", ""):
        positives.append("財務體質呈改善訊號")
    if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
        positives.append(f"近期月營收年增 {revenue.yoy_pct:.2f}%")
    if len(related_documents) >= 2:
        positives.append(f"{len(related_documents)} 筆公司層級文本支撐主題關聯")
    if not positives:
        return "目前缺少長期成長證據，需補產業規模、資本支出與競爭格局資料。"
    return "；".join(positives[:3]) + "；仍需用 5-10 年產業規模、毛利率與自由現金流假設做二次驗證。"


def dcf_proxy_text(financial_summary: dict[str, str], valuation: ValuationMetric | None) -> str:
    available = []
    if "自由現金流" in financial_summary.get("fcf_trend", "") and "目前無足夠" not in financial_summary["fcf_trend"]:
        available.append(financial_summary["fcf_trend"])
    if valuation and valuation.pe_ratio is not None:
        available.append(f"目前可用 P/E {valuation.pe_ratio:.2f} 作為相對估值交叉檢查")
    if not available:
        return "尚缺可驗證 FCF 序列、折現率與終值假設，不自動給目標價。"
    return "；".join(available) + "；系統暫不硬算目標價，避免用未驗證假設製造精準幻覺。"


def industry_average_text(peer_summary: dict[str, float | None]) -> str:
    count = int(peer_summary.get("count") or 0)
    pe_avg = peer_summary.get("pe_avg")
    pb_avg = peer_summary.get("pb_avg")
    if count < 2 or (pe_avg is None and pb_avg is None):
        return "同業樣本不足，需補更多可比公司後再判斷產業平均。"
    parts = [f"同業樣本 {count} 檔"]
    if pe_avg is not None:
        parts.append(f"平均 P/E {pe_avg:.2f}")
    if pb_avg is not None:
        parts.append(f"平均 P/B {pb_avg:.2f}")
    return "、".join(parts) + "。"


def bull_case(revenue: MonthlyRevenue | None, related_documents: list[NewsDocument]) -> str:
    points = []
    if related_documents:
        points.append(f"有 {len(related_documents)} 筆公司相關文本支持題材關聯")
    if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 0:
        points.append(f"月營收年增率 {revenue.yoy_pct:.2f}%")
    return "；".join(points) + "。" if points else "目前無足夠數據支持多頭論點。"


def bear_case(related_findings) -> str:
    if not related_findings:
        return "目前無明確風險證據，但缺少證據不等於沒有風險。"
    return f"已有 {len(related_findings)} 筆風險/機會歸因，需確認是否影響出貨、毛利或估值。"


def moat_score(
    related_documents: list[NewsDocument],
    related_findings,
    revenue: MonthlyRevenue | None,
    financial_summary: dict[str, str] | None = None,
) -> int:
    score = 3
    if len(related_documents) >= 2:
        score += 1
    if related_findings:
        score += 1
    if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
        score += 1
    if financial_summary and "體質改善" in financial_summary.get("strength", ""):
        score += 1
    return min(score, 6)


def moat_reason(
    score: int,
    related_documents: list[NewsDocument],
    related_findings,
    revenue: MonthlyRevenue | None,
    financial_summary: dict[str, str] | None = None,
) -> str:
    reasons = []
    if len(related_documents) >= 2:
        reasons.append(f"{len(related_documents)} 筆公司層級文本")
    if related_findings:
        reasons.append(f"{len(related_findings)} 筆主題/風險歸因證據")
    if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
        reasons.append(f"月營收年增 {revenue.yoy_pct:.2f}%")
    if financial_summary and "體質改善" in financial_summary.get("strength", ""):
        reasons.append("財務趨勢偏改善")
    if not reasons:
        reasons.append("目前缺少可量化護城河證據")
    caveat = "仍需補客戶集中度、市占、長約、認證週期與專利/技術資料。"
    return f"{'、'.join(reasons)}，因此暫評 {score}/10；{caveat}"


def moat_factor_text(
    factor: str,
    related_documents: list[NewsDocument],
    related_findings,
    revenue: MonthlyRevenue | None,
    financial_summary: dict[str, str],
) -> str:
    text = " ".join([document.title + " " + document.text[:500] for document in related_documents])
    if factor == "brand":
        if len(related_documents) >= 5:
            return f"公司在本主題下有 {len(related_documents)} 筆可追溯文本，顯示市場辨識度高；仍需市占與客戶結構驗證。"
        if related_documents:
            return f"已有 {len(related_documents)} 筆公司層級文本，但品牌/市占強度仍需更多來源交叉比對。"
    if factor == "network":
        return "硬體與供應鏈公司通常不是典型網路效應，系統不會把題材熱度誤判成網路效應。"
    if factor == "switching_cost":
        if any(keyword in text for keyword in ["認證", "導入", "長約", "客戶", "良率", "供應鏈"]):
            return "文本出現客戶認證、導入或供應鏈關鍵字，可能存在轉換成本；仍需客戶與合約資料確認。"
        return "尚未看到足夠客戶認證或導入週期證據，暫不加分。"
    if factor == "cost":
        if "負債權益比" in financial_summary.get("debt_trend", "") or "利率約" in financial_summary.get("margin_trend", ""):
            return f"可用財報顯示 {financial_summary.get('margin_trend')} {financial_summary.get('debt_trend')}，可作為成本優勢初步檢查。"
        if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 20:
            return f"月營收年增 {revenue.yoy_pct:.2f}% 顯示規模動能，但仍需毛利率驗證成本優勢。"
    if factor == "technology":
        keywords = [keyword for keyword in ["專利", "先進製程", "CoWoS", "HBM", "液冷", "導軌", "ASIC"] if keyword in text]
        if keywords:
            return f"文本出現 {', '.join(keywords[:4])} 等技術/產品關鍵字，可列為技術壁壘候選；仍需官方技術或專利來源驗證。"
    return "目前證據不足，系統保留為待補資料，不自動給護城河加分。"


def company_rating(
    snapshot: MarketSnapshot | None,
    revenue: MonthlyRevenue | None,
    related_documents: list[NewsDocument],
    related_findings,
) -> str:
    if not snapshot:
        return "避免"
    if related_findings:
        return "持有/觀察"
    if len(related_documents) >= 2 and revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
        return "持有"
    return "持有/觀察"


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
