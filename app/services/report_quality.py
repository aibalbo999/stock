from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from app.core.time import now_taipei
from app.db.session import session_scope
from app.models.schemas import NewsDocument, ReportRequest, ReportResponse
from app.services.candidate_confidence import format_confidence_score
from app.services.entity_mapping import EntityMapper
from app.services.leading_signals import LeadingSignalAnalyzer
from app.services.persistence import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)


def build_report_quality_gate(
    source_audit: dict,
    promoted_tickers: list[str],
    market_count: int,
    monthly_revenue_count: int,
    financial_metrics_count: int,
    valuation_count: int,
    investor_capital: int | None = None,
    cash_reserve_pct: float | None = None,
    source_quality: dict | None = None,
    plan_quality: dict | None = None,
    leading_signal_count: int | None = None,
    llm_status: dict | None = None,
    company_filing_sufficient_count: int | None = None,
) -> dict:
    candidate_support = source_audit.get("candidate_support") or {}
    dynamic_sources = source_audit.get("dynamic_queries") or {}
    promoted_count = len(promoted_tickers)
    source_count = int(dynamic_sources.get("stored_count") or 0)
    source_quality = source_quality or {}
    plan_quality = plan_quality or source_audit.get("plan_quality") or {}
    exploration_supported_ratio = float(
        candidate_support.get("exploration_supported_ratio", candidate_support.get("supported_ratio")) or 0
    )
    formal_supported_ratio = float(
        candidate_support.get(
            "formal_supported_ratio",
            1.0 if promoted_count else exploration_supported_ratio,
        )
        or 0
    )
    formal_confidence_avg = candidate_support.get("formal_confidence_avg")
    formal_confidence_min = candidate_support.get("formal_confidence_min")
    formal_low_confidence_count = int(candidate_support.get("formal_low_confidence_count") or 0)
    market_coverage = market_count / promoted_count if promoted_count else 0
    monthly_coverage = monthly_revenue_count / promoted_count if promoted_count else 0
    valuation_coverage = valuation_count / promoted_count if promoted_count else 0
    leading_signal_coverage = leading_signal_count / promoted_count if promoted_count and leading_signal_count is not None else None
    company_filing_coverage = (
        company_filing_sufficient_count / promoted_count
        if promoted_count and company_filing_sufficient_count is not None
        else None
    )
    llm_status = llm_status or {}
    llm_fallback = bool(llm_status.get("fallback")) if llm_status else None

    blockers = []
    warnings = []
    observations = []
    if promoted_count == 0:
        blockers.append("沒有通過證據驗證的正式分析股票")
    if promoted_count == 0 and exploration_supported_ratio < 0.6:
        blockers.append("候選公司證據覆蓋率低於 60%")
    elif promoted_count and formal_supported_ratio < 1:
        blockers.append("正式分析股票仍含弱證據公司")
    elif promoted_count and formal_low_confidence_count:
        blockers.append("正式分析股票含低信心證據公司")
    elif promoted_count and exploration_supported_ratio < 0.6:
        observations.append("AI 初始候選清單較廣，已由二次篩選收斂為正式分析股票")
    if source_count < 8:
        blockers.append("AI 動態資料來源入庫篇數過少")
    elif source_count < 12:
        warnings.append("AI 動態資料來源偏少")
    if source_quality:
        timestamp_coverage = float(source_quality.get("timestamp_coverage") or 0)
        unique_publishers = int(source_quality.get("unique_publisher_count") or 0)
        recent_coverage = float(source_quality.get("recent_coverage") or 0)
        if timestamp_coverage < 0.5:
            blockers.append("來源時間戳覆蓋率低於 50%")
        elif timestamp_coverage < 0.8:
            warnings.append("部分來源缺少發布日期，事實核查信心需下修")
        if source_count >= 8 and unique_publishers < 2:
            blockers.append("資料來源發布者過於單一")
        elif source_count >= 8 and unique_publishers < 3:
            warnings.append("資料來源多樣性偏低")
        if source_count >= 8 and recent_coverage < 0.4:
            warnings.append("近期資料比例偏低，可能混入過舊產業假設")
    if plan_quality:
        plan_status = str(plan_quality.get("status") or "unknown")
        plan_score = int(plan_quality.get("score") or 0)
        missing = plan_quality.get("missing") or []
        missing_summary = "、".join(str(item) for item in missing[:3])
        if plan_status == "insufficient" or plan_score < 55:
            detail = f"：{missing_summary}" if missing_summary else ""
            blockers.append(f"AI 拆解任務品質不足{detail}")
        elif plan_status == "caution" or plan_score < 80:
            detail = f"：{missing_summary}" if missing_summary else ""
            warnings.append(f"AI 拆解任務仍有缺口{detail}")
    if promoted_count and market_coverage < 0.5:
        blockers.append("股價資料覆蓋率低於 50%")
    elif promoted_count and market_coverage < 1:
        warnings.append("部分股票缺少最新股價資料")
    if promoted_count and monthly_coverage < 0.5:
        warnings.append("月營收資料覆蓋偏低")
    if promoted_count and financial_metrics_count < promoted_count * 8:
        warnings.append("五年財務資料不足，個股財務判斷信心需下修")
    if promoted_count and valuation_coverage < 0.5:
        warnings.append("估值資料覆蓋偏低")
    if promoted_count and leading_signal_coverage is not None:
        if leading_signal_coverage < 0.5:
            warnings.append("領先訊號覆蓋偏低，潛力/風險排序信心需下修")
        elif leading_signal_coverage < 1:
            observations.append("部分股票領先訊號不足，系統已降低排序信心")
    if promoted_count and company_filing_coverage is not None:
        if company_filing_coverage < 0.5:
            blockers.append("公司公開文件覆蓋率低於 50%")
        elif company_filing_coverage < 1:
            warnings.append("部分股票缺少高品質公司公開文件")
    if llm_status:
        if llm_fallback:
            warnings.append("LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿")
        else:
            observations.append("LLM 補充分析已完成，且仍受來源與白名單驗證約束")

    status = "ready"
    if blockers:
        status = "insufficient"
    elif warnings:
        status = "caution"
    if status == "insufficient":
        action_policy = "research_only"
        max_deployable_multiplier = 0.0
        action_label = "僅供研究，不允許投入資金"
    elif status == "caution":
        action_policy = "manual_review_required"
        max_deployable_multiplier = 0.25
        action_label = "需人工覆核，最多只可動用可投入資金的 25%"
    else:
        action_policy = "actionable"
        max_deployable_multiplier = 1.0
        action_label = "通過品質門檻，可依資金控管建議分批研究"
    deployable_amount = None
    if investor_capital is not None and cash_reserve_pct is not None:
        deployable_base = max(0, int(investor_capital * (1 - cash_reserve_pct)))
        deployable_amount = int(deployable_base * max_deployable_multiplier)
    remediation_actions = quality_remediation_actions(blockers, warnings)
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "observations": observations,
        "remediation_actions": remediation_actions,
        "action_policy": {
            "policy": action_policy,
            "label": action_label,
            "max_deployable_multiplier": max_deployable_multiplier,
            "max_deployable_amount": deployable_amount,
        },
        "metrics": {
            "promoted_count": promoted_count,
            "candidate_supported_ratio": formal_supported_ratio,
            "exploration_candidate_supported_ratio": exploration_supported_ratio,
            "formal_confidence_avg": formal_confidence_avg,
            "formal_confidence_min": formal_confidence_min,
            "formal_low_confidence_count": formal_low_confidence_count,
            "dynamic_source_count": source_count,
            "market_coverage": market_coverage,
            "monthly_revenue_coverage": monthly_coverage,
            "financial_metrics_count": financial_metrics_count,
            "valuation_coverage": valuation_coverage,
            "leading_signal_coverage": leading_signal_coverage,
            "company_filing_coverage": company_filing_coverage,
            "llm_analysis_status": "fallback" if llm_fallback else "enabled" if llm_status else None,
            "llm_model": llm_status.get("model"),
            "llm_key_index": llm_status.get("key_index"),
            "source_unique_publishers": source_quality.get("unique_publisher_count"),
            "source_timestamp_coverage": source_quality.get("timestamp_coverage"),
            "source_recent_coverage": source_quality.get("recent_coverage"),
            "discovery_plan_status": plan_quality.get("status") if plan_quality else None,
            "discovery_plan_score": plan_quality.get("score") if plan_quality else None,
        },
        "recommendation": (
            "資料品質不足，請先視為研究草稿，不應作為買賣依據。"
            if status == "insufficient"
            else "資料大致可用，但仍需人工確認警示項。"
            if status == "caution"
            else "資料品質達到本系統產出投資建議的基本門檻。"
        ),
    }


def quality_remediation_actions(blockers: list[str], warnings: list[str]) -> list[str]:
    issue_text = "；".join([*blockers, *warnings])
    actions = []
    rules = [
        (
            ("沒有通過證據驗證",),
            "重新執行主題拆解，要求 AI 補查公司與主題的直接證據後再產生正式股票。",
        ),
        (
            ("候選公司證據覆蓋率低於 25%", "候選公司證據覆蓋率低於 60%"),
            "保留已升格的正式股票，對弱證據候選補抓公司新聞、法說會與供應鏈資料後再做二次篩選。",
        ),
        (
            ("低信心證據公司",),
            "對低信心正式股票補抓近期、有日期且不同發布者的公司來源，未補齊前不得產生買入建議。",
        ),
        (
            ("AI 動態資料來源入庫篇數過少", "AI 動態資料來源偏少"),
            "增加查詢子題、拉長回溯天數或開啟深度分析，至少補足 12 篇以上可追溯來源。",
        ),
        (
            ("來源時間戳覆蓋率", "缺少發布日期"),
            "優先改用有發布日期的來源，無日期資料只作背景參考，不納入關鍵風險或估值推論。",
        ),
        (
            ("資料來源發布者過於單一", "資料來源多樣性偏低"),
            "補入不同發布者與國際資料源，避免單一媒體或單一市場觀點主導結論。",
        ),
        (
            ("近期資料比例偏低",),
            "補抓最近期間資料，確認產能、訂單、法規與估值假設仍然有效。",
        ),
        (
            ("AI 拆解任務品質",),
            "請 AI 重新拆解分析任務，補齊缺漏的產業子題、風險瓶頸、估值與個股研究任務。",
        ),
        (
            ("股價資料覆蓋率",),
            "刷新股價與市值資料，缺資料股票不得產生買入或加碼建議。",
        ),
        (
            ("月營收資料覆蓋",),
            "補齊月營收資料，並把缺資料股票的成長判斷降為低信心。",
        ),
        (
            ("五年財務資料不足",),
            "補齊近五年財務指標，未補齊前不得給出高信心財務體質結論。",
        ),
        (
            ("估值資料覆蓋",),
            "補齊同業估值、P/E 與 DCF 假設，估值缺口未補齊前只保留觀察結論。",
        ),
        (
            ("公司公開文件覆蓋", "高品質公司公開文件"),
            "補抓或人工匯入年報、法說會與官方 IR 文件；未補齊前不得把個股列為可投入資金標的。",
        ),
        (
            ("領先訊號覆蓋",),
            "補齊股價歷史、成交量、月營收與估值資料，避免只靠新聞排序潛力與風險標的。",
        ),
        (
            ("LLM 補充分析",),
            "檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。",
        ),
    ]
    for keywords, action in rules:
        if any(keyword in issue_text for keyword in keywords):
            actions.append(action)
    if issue_text and not actions:
        actions.append("先補齊品質警示所列資料缺口，再重新執行完整分析。")
    return _dedupe(actions)


def _dedupe(items: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def summarize_document_source_quality(documents: list[NewsDocument], lookback_days: int) -> dict:
    total = len(documents)
    if not total:
        return {
            "total_documents": 0,
            "unique_publisher_count": 0,
            "timestamped_count": 0,
            "timestamp_coverage": 0,
            "recent_count": 0,
            "recent_coverage": 0,
            "publisher_sample": [],
        }
    cutoff = now_taipei().date() - timedelta(days=max(1, lookback_days))
    publishers = {
        _normalize_publisher(document.source.publisher or document.source.url or document.source.title)
        for document in documents
        if _normalize_publisher(document.source.publisher or document.source.url or document.source.title)
    }
    published_dates = [
        _source_date(document.source.published_at)
        for document in documents
        if _source_date(document.source.published_at) is not None
    ]
    recent_count = sum(1 for published_at in published_dates if published_at >= cutoff)
    return {
        "total_documents": total,
        "unique_publisher_count": len(publishers),
        "timestamped_count": len(published_dates),
        "timestamp_coverage": len(published_dates) / total,
        "recent_count": recent_count,
        "recent_coverage": recent_count / total,
        "publisher_sample": sorted(publishers)[:5],
    }


def _source_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _normalize_publisher(value: str | None) -> str:
    return (value or "").strip()


def _peer_valuation_summary(valuations) -> dict[str, float | None]:
    pe_values = [valuation.pe_ratio for valuation in valuations if valuation.pe_ratio is not None and valuation.pe_ratio > 0]
    pb_values = [valuation.pb_ratio for valuation in valuations if valuation.pb_ratio is not None and valuation.pb_ratio > 0]
    return {
        "pe_avg": sum(pe_values) / len(pe_values) if pe_values else None,
        "pb_avg": sum(pb_values) / len(pb_values) if pb_values else None,
    }


def build_quality_gate_for_request(
    request: ReportRequest,
    documents: list[NewsDocument] | None = None,
    source_count: int | None = None,
    llm_result: object | None = None,
    company_filing_sufficient_count: int | None = None,
) -> dict:
    tickers = EntityMapper().filter_allowed_tickers(request.tickers)
    source_count = len(documents or []) if source_count is None else source_count
    source_quality = summarize_document_source_quality(documents or [], request.lookback_days) if documents else None
    source_audit = {
        "candidate_support": {
            "total": len(tickers),
            "supported": len(tickers),
            "unsupported": 0,
            "supported_ratio": 1.0 if tickers else 0.0,
        },
        "dynamic_queries": {"stored_count": source_count},
    }
    with session_scope() as session:
        market_count = len(MarketRepository(session).latest_by_tickers(tickers))
        monthly_revenue_count = len(MonthlyRevenueRepository(session).latest_by_tickers(tickers))
        financial_metrics_count = len(FinancialMetricRepository(session).by_tickers(tickers))
        valuations = ValuationMetricRepository(session).latest_by_tickers(tickers)
        valuation_count = len(valuations)
        price_histories = MarketRepository(session).history_by_tickers(tickers, limit=90)
        revenue_histories = MonthlyRevenueRepository(session).history_by_tickers(tickers, limit=18)
    valuation_map = {valuation.ticker: valuation for valuation in valuations}
    peer_summary = _peer_valuation_summary(valuations)
    leading_signals = LeadingSignalAnalyzer().build(tickers, price_histories, revenue_histories, valuation_map, peer_summary)
    leading_signal_count = sum(1 for signal in leading_signals.values() if signal.has_signal_data)
    return build_report_quality_gate(
        source_audit,
        tickers,
        market_count=market_count,
        monthly_revenue_count=monthly_revenue_count,
        financial_metrics_count=financial_metrics_count,
        valuation_count=valuation_count,
        investor_capital=request.investor_capital,
        cash_reserve_pct=request.cash_reserve_pct,
        source_quality=source_quality,
        leading_signal_count=leading_signal_count,
        llm_status=summarize_llm_status(llm_result),
        company_filing_sufficient_count=company_filing_sufficient_count,
    )


def summarize_llm_status(llm_result: object | None) -> dict | None:
    if llm_result is None:
        return None
    return {
        "fallback": bool(getattr(llm_result, "fallback", False)),
        "model": getattr(llm_result, "model", None),
        "key_index": getattr(llm_result, "key_index", None),
    }


def render_quality_gate_markdown(quality_gate: dict) -> str:
    labels = {
        "ready": "資料品質可用",
        "caution": "需謹慎判讀",
        "insufficient": "資料不足",
    }
    metrics = quality_gate.get("metrics") or {}
    action_policy = quality_gate.get("action_policy") or {}
    lines = [
        "## 報告品質門檻",
        f"- 狀態：{labels.get(quality_gate.get('status'), quality_gate.get('status', 'unknown'))}",
        f"- 系統判斷：{quality_gate.get('recommendation', '目前無足夠數據判斷。')}",
        f"- 投資行動狀態：{action_policy.get('label', '目前無足夠數據判斷。')}",
        f"- 正式分析股票：{metrics.get('promoted_count', 0)} 檔",
        f"- 候選公司證據覆蓋率：{float(metrics.get('candidate_supported_ratio') or 0):.0%}",
        f"- 探索候選覆蓋率：{float(metrics.get('exploration_candidate_supported_ratio') or 0):.0%}",
        f"- 正式股票證據信心：平均 {_format_confidence_score(metrics.get('formal_confidence_avg'))} / "
        f"最低 {_format_confidence_score(metrics.get('formal_confidence_min'))}",
        f"- AI 動態來源入庫：{metrics.get('dynamic_source_count', 0)} 篇",
        f"- 來源發布者數：{_format_optional_int(metrics.get('source_unique_publishers'))}",
        f"- 來源時間戳覆蓋率：{_format_optional_percent(metrics.get('source_timestamp_coverage'))}",
        f"- 近期資料比例：{_format_optional_percent(metrics.get('source_recent_coverage'))}",
        f"- 拆解任務品質：{_format_plan_quality(metrics)}",
        f"- LLM 補充分析：{_format_llm_status(metrics)}",
        f"- 股價資料覆蓋率：{float(metrics.get('market_coverage') or 0):.0%}",
        f"- 月營收資料覆蓋率：{float(metrics.get('monthly_revenue_coverage') or 0):.0%}",
        f"- 估值資料覆蓋率：{float(metrics.get('valuation_coverage') or 0):.0%}",
        f"- 領先訊號覆蓋率：{_format_optional_percent(metrics.get('leading_signal_coverage'))}",
        f"- 公司公開文件覆蓋率：{_format_optional_percent(metrics.get('company_filing_coverage'))}",
    ]
    if action_policy.get("max_deployable_amount") is not None:
        lines.append(f"- 本輪品質門檻後可投入上限：約 {int(action_policy['max_deployable_amount']):,} 元")
    blockers = quality_gate.get("blockers") or []
    warnings = quality_gate.get("warnings") or []
    observations = quality_gate.get("observations") or []
    if blockers:
        lines.append("- 阻擋項：" + "；".join(blockers))
    if warnings:
        lines.append("- 警示項：" + "；".join(warnings))
    if observations:
        lines.append("- 觀察項：" + "；".join(str(item) for item in observations))
    remediation_actions = quality_gate.get("remediation_actions") or []
    if remediation_actions:
        lines.append("- 建議補強：" + "；".join(str(action) for action in remediation_actions))
    if not blockers and not warnings:
        lines.append("- 阻擋/警示：無")
    return "\n".join(lines)


def _format_optional_int(value: object) -> str:
    return "未評估" if value is None else str(value)


def _format_optional_number(value: object) -> str:
    if value is None:
        return "未評估"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _format_confidence_score(value: object) -> str:
    return format_confidence_score(float(value)) if value is not None else "未評估"


def _format_optional_percent(value: object) -> str:
    return "未評估" if value is None else f"{float(value or 0):.0%}"


def _format_plan_quality(metrics: dict) -> str:
    status = metrics.get("discovery_plan_status")
    score = metrics.get("discovery_plan_score")
    if status is None and score is None:
        return "未評估"
    labels = {
        "ready": "完整",
        "caution": "需補強",
        "insufficient": "不足",
    }
    label = labels.get(str(status), str(status or "unknown"))
    return f"{label}（{int(score or 0)} 分）"


def _format_llm_status(metrics: dict) -> str:
    status = metrics.get("llm_analysis_status")
    if status == "enabled":
        model = metrics.get("llm_model") or "unknown"
        key_index = metrics.get("llm_key_index")
        key_note = f"，key_pool_index={key_index}" if key_index is not None else ""
        return f"已啟用（model={model}{key_note}）"
    if status == "fallback":
        return "未啟用或呼叫失敗，已退回規則引擎"
    return "未評估"


def parse_quality_gate_from_markdown(markdown: str) -> dict | None:
    section = _markdown_section(markdown, "報告品質門檻")
    if not section:
        return None
    fields: dict[str, str] = {}
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("- ") or "：" not in line:
            continue
        key, value = line[2:].split("：", 1)
        fields[key.strip()] = value.strip()

    status_map = {
        "資料品質可用": "ready",
        "需謹慎判讀": "caution",
        "資料不足": "insufficient",
    }
    action_label = fields.get("投資行動狀態", "目前無足夠數據判斷。")
    return {
        "status": status_map.get(fields.get("狀態", ""), "unknown"),
        "blockers": _split_issue_field(fields.get("阻擋項")),
        "warnings": _split_issue_field(fields.get("警示項")),
        "observations": _split_issue_field(fields.get("觀察項")),
        "remediation_actions": _split_issue_field(fields.get("建議補強")),
        "action_policy": {
            "label": action_label,
            "max_deployable_amount": _parse_amount(fields.get("本輪品質門檻後可投入上限")),
        },
        "metrics": {
            "promoted_count": _parse_int(fields.get("正式分析股票")),
            "candidate_supported_ratio": _parse_percent(fields.get("候選公司證據覆蓋率")),
            "exploration_candidate_supported_ratio": _parse_percent(fields.get("探索候選覆蓋率")),
            "formal_confidence_avg": _parse_confidence_value(fields.get("正式股票證據信心"), "平均"),
            "formal_confidence_min": _parse_confidence_value(fields.get("正式股票證據信心"), "最低"),
            "dynamic_source_count": _parse_int(fields.get("AI 動態來源入庫")),
            "source_unique_publishers": _parse_optional_int(fields.get("來源發布者數")),
            "source_timestamp_coverage": _parse_optional_percent(fields.get("來源時間戳覆蓋率")),
            "source_recent_coverage": _parse_optional_percent(fields.get("近期資料比例")),
            "discovery_plan_status": _parse_plan_quality_status(fields.get("拆解任務品質")),
            "discovery_plan_score": _parse_plan_quality_score(fields.get("拆解任務品質")),
            "llm_analysis_status": _parse_llm_status(fields.get("LLM 補充分析")),
            "market_coverage": _parse_percent(fields.get("股價資料覆蓋率")),
            "monthly_revenue_coverage": _parse_percent(fields.get("月營收資料覆蓋率")),
            "valuation_coverage": _parse_percent(fields.get("估值資料覆蓋率")),
            "leading_signal_coverage": _parse_optional_percent(fields.get("領先訊號覆蓋率")),
            "company_filing_coverage": _parse_optional_percent(fields.get("公司公開文件覆蓋率")),
        },
        "recommendation": fields.get("系統判斷", "目前無足夠數據判斷。"),
    }


def _markdown_section(markdown: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)", markdown, flags=re.S | re.M)
    return (match.group("body").strip() if match else "")


def _split_issue_field(value: str | None) -> list[str]:
    if not value or value == "無":
        return []
    return [item.strip() for item in value.split("；") if item.strip()]


def _parse_int(value: str | None) -> int:
    if not value:
        return 0
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def _parse_optional_int(value: str | None) -> int | None:
    if not value or value == "未評估":
        return None
    return _parse_int(value)


def _parse_percent(value: str | None) -> float:
    parsed = _parse_optional_percent(value)
    return parsed if parsed is not None else 0


def _parse_optional_percent(value: str | None) -> float | None:
    if not value or value == "未評估":
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)%", value)
    return float(match.group(1)) / 100 if match else None


def _parse_confidence_value(value: str | None, label: str) -> float | None:
    if not value or "未評估" in value:
        return None
    match = re.search(rf"{re.escape(label)}\s*(?:高|中|低)?\s*(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


def _parse_plan_quality_status(value: str | None) -> str | None:
    if not value or value == "未評估":
        return None
    if "完整" in value:
        return "ready"
    if "需補強" in value:
        return "caution"
    if "不足" in value:
        return "insufficient"
    return "unknown"


def _parse_plan_quality_score(value: str | None) -> int | None:
    if not value or value == "未評估":
        return None
    match = re.search(r"(\d+)\s*分", value)
    return int(match.group(1)) if match else None


def _parse_llm_status(value: str | None) -> str | None:
    if not value or value == "未評估":
        return None
    if "退回規則引擎" in value or "呼叫失敗" in value:
        return "fallback"
    if "已啟用" in value:
        return "enabled"
    return None


def _parse_amount(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def render_quality_action_guard_markdown(quality_gate: dict) -> str:
    status = quality_gate.get("status")
    if status == "ready":
        return ""
    action_policy = quality_gate.get("action_policy") or {}
    amount = action_policy.get("max_deployable_amount")
    amount_line = (
        f"- 品質門檻後本輪可投入上限：{int(amount):,} 元；此數字優先於後續摘要或表格中的一般資金上限。"
        if amount is not None
        else "- 品質門檻後本輪可投入上限以本段限制為準，優先於後續摘要或表格中的一般資金上限。"
    )
    if status == "insufficient":
        return "\n".join(
            [
                "## 投資行動限制",
                "- 本次報告品質狀態為「資料不足」。",
                amount_line,
                "- 所有個股結論自動降級為「觀察 / 補資料」，不得視為買入清單。",
                "- 若報告其他章節出現升值情境或可研究字樣，僅代表研究線索，不代表可投入資金。",
                "- 下一步應先補齊阻擋項，再重新執行分析。",
            ]
        )
    return "\n".join(
        [
            "## 投資行動限制",
            "- 本次報告品質狀態為「需謹慎判讀」。",
            amount_line,
            "- 可保留觀察名單，但不應直接轉成買入或加碼指令。",
            "- 需先人工覆核警示項，確認資料缺口不影響核心投資假設。",
        ]
    )


def remove_quality_gate_sections(markdown: str) -> str:
    return re.sub(
        r"\n*## (報告品質門檻|投資行動限制)\n.*?(?=\n## |\Z)",
        "",
        markdown,
        flags=re.S,
    ).strip()


def attach_quality_gate_to_report(response: ReportResponse, quality_gate: dict) -> ReportResponse:
    quality_section = render_quality_gate_markdown(quality_gate)
    action_guard = render_quality_action_guard_markdown(quality_gate)
    inserted_sections = quality_section if not action_guard else f"{quality_section}\n\n{action_guard}"
    markdown = remove_quality_gate_sections(response.markdown)
    first_section = markdown.find("\n## ")
    if first_section == -1:
        markdown = f"{markdown.rstrip()}\n\n{inserted_sections}"
    else:
        markdown = f"{markdown[:first_section].rstrip()}\n\n{inserted_sections}\n{markdown[first_section:]}"
    return response.model_copy(update={"markdown": markdown, "quality_gate": quality_gate})
