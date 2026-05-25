from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from app.core.time import now_taipei
from app.db.session import session_scope
from app.models.schemas import NewsDocument, ReportRequest, ReportResponse
from app.services.entity_mapping import EntityMapper
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
) -> dict:
    candidate_support = source_audit.get("candidate_support") or {}
    dynamic_sources = source_audit.get("dynamic_queries") or {}
    promoted_count = len(promoted_tickers)
    source_count = int(dynamic_sources.get("stored_count") or 0)
    source_quality = source_quality or {}
    plan_quality = plan_quality or source_audit.get("plan_quality") or {}
    supported_ratio = float(candidate_support.get("supported_ratio") or 0)
    market_coverage = market_count / promoted_count if promoted_count else 0
    monthly_coverage = monthly_revenue_count / promoted_count if promoted_count else 0
    valuation_coverage = valuation_count / promoted_count if promoted_count else 0

    blockers = []
    warnings = []
    if promoted_count == 0:
        blockers.append("沒有通過證據驗證的正式分析股票")
    if promoted_count == 0 and supported_ratio < 0.6:
        blockers.append("候選公司證據覆蓋率低於 60%")
    elif promoted_count and supported_ratio < 0.25:
        blockers.append("候選公司證據覆蓋率低於 25%，AI 候選清單過度發散")
    elif promoted_count and supported_ratio < 0.6:
        warnings.append("候選公司證據覆蓋率低於 60%，已由二次篩選收斂正式股票")
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
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "action_policy": {
            "policy": action_policy,
            "label": action_label,
            "max_deployable_multiplier": max_deployable_multiplier,
            "max_deployable_amount": deployable_amount,
        },
        "metrics": {
            "promoted_count": promoted_count,
            "candidate_supported_ratio": supported_ratio,
            "dynamic_source_count": source_count,
            "market_coverage": market_coverage,
            "monthly_revenue_coverage": monthly_coverage,
            "financial_metrics_count": financial_metrics_count,
            "valuation_coverage": valuation_coverage,
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


def build_quality_gate_for_request(
    request: ReportRequest,
    documents: list[NewsDocument] | None = None,
    source_count: int | None = None,
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
        valuation_count = len(ValuationMetricRepository(session).latest_by_tickers(tickers))
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
    )


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
        f"- AI 動態來源入庫：{metrics.get('dynamic_source_count', 0)} 篇",
        f"- 來源發布者數：{_format_optional_int(metrics.get('source_unique_publishers'))}",
        f"- 來源時間戳覆蓋率：{_format_optional_percent(metrics.get('source_timestamp_coverage'))}",
        f"- 近期資料比例：{_format_optional_percent(metrics.get('source_recent_coverage'))}",
        f"- 拆解任務品質：{_format_plan_quality(metrics)}",
        f"- 股價資料覆蓋率：{float(metrics.get('market_coverage') or 0):.0%}",
        f"- 月營收資料覆蓋率：{float(metrics.get('monthly_revenue_coverage') or 0):.0%}",
        f"- 估值資料覆蓋率：{float(metrics.get('valuation_coverage') or 0):.0%}",
    ]
    if action_policy.get("max_deployable_amount") is not None:
        lines.append(f"- 本輪品質門檻後可投入上限：約 {int(action_policy['max_deployable_amount']):,} 元")
    blockers = quality_gate.get("blockers") or []
    warnings = quality_gate.get("warnings") or []
    if blockers:
        lines.append("- 阻擋項：" + "；".join(blockers))
    if warnings:
        lines.append("- 警示項：" + "；".join(warnings))
    if not blockers and not warnings:
        lines.append("- 阻擋/警示：無")
    return "\n".join(lines)


def _format_optional_int(value: object) -> str:
    return "未評估" if value is None else str(value)


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
        "action_policy": {
            "label": action_label,
            "max_deployable_amount": _parse_amount(fields.get("本輪品質門檻後可投入上限")),
        },
        "metrics": {
            "promoted_count": _parse_int(fields.get("正式分析股票")),
            "candidate_supported_ratio": _parse_percent(fields.get("候選公司證據覆蓋率")),
            "dynamic_source_count": _parse_int(fields.get("AI 動態來源入庫")),
            "source_unique_publishers": _parse_optional_int(fields.get("來源發布者數")),
            "source_timestamp_coverage": _parse_optional_percent(fields.get("來源時間戳覆蓋率")),
            "source_recent_coverage": _parse_optional_percent(fields.get("近期資料比例")),
            "discovery_plan_status": _parse_plan_quality_status(fields.get("拆解任務品質")),
            "discovery_plan_score": _parse_plan_quality_score(fields.get("拆解任務品質")),
            "market_coverage": _parse_percent(fields.get("股價資料覆蓋率")),
            "monthly_revenue_coverage": _parse_percent(fields.get("月營收資料覆蓋率")),
            "valuation_coverage": _parse_percent(fields.get("估值資料覆蓋率")),
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


def _parse_amount(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def render_quality_action_guard_markdown(quality_gate: dict) -> str:
    status = quality_gate.get("status")
    if status == "ready":
        return ""
    if status == "insufficient":
        return "\n".join(
            [
                "## 投資行動限制",
                "- 本次報告品質狀態為「資料不足」。",
                "- 所有個股結論自動降級為「觀察 / 補資料」，不得視為買入清單。",
                "- 若報告其他章節出現升值情境或可研究字樣，僅代表研究線索，不代表可投入資金。",
                "- 下一步應先補齊阻擋項，再重新執行分析。",
            ]
        )
    return "\n".join(
        [
            "## 投資行動限制",
            "- 本次報告品質狀態為「需謹慎判讀」。",
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
