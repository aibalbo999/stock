from __future__ import annotations

import re
from html import escape
from typing import Optional

from app.services.candidate_confidence import format_confidence_score


def decision_badge_class(value: str) -> str:
    if "可小額" in value or "可研究" in value:
        return "decision-action"
    if "避開" in value or "降低曝險" in value:
        return "decision-risk"
    return "decision-watch"


def valuation_badge_class(value: str) -> str:
    if "偏高" in value or "略高" in value:
        return "valuation-high"
    if "低於" in value or "略低" in value:
        return "valuation-low"
    return "valuation-neutral"


def current_price_badge_class(value: str) -> str:
    if "可小額" in value or "可研究" in value:
        return "price-action"
    if "不適合" in value or "等止跌" in value or "風險" in value:
        return "price-risk"
    if "等回檔" in value or "觀察" in value or "勿追高" in value:
        return "price-watch"
    return "price-neutral"


def downside_badge_class(value: str) -> str:
    digits = re.sub(r"[^\d.]", "", value)
    if not digits:
        return ""
    return "risk-high" if float(digits) > 5 else "risk-low"


def investor_friendly_quality_text(item: object) -> str:
    text = str(item)
    replacements = {
        "LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿": (
            "模型補充分析未啟用或呼叫失敗，個股結論主要由資料規則產生，需人工覆核"
        ),
        "LLM 補充分析已完成，且仍受來源與白名單驗證約束": (
            "模型補充分析已完成，仍只採用可追溯來源與白名單公司"
        ),
        "AI 動態資料來源": "自動搜尋資料來源",
        "AI 拆解": "主題拆解",
        "LLM 補充分析": "模型補充分析",
        "檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。": (
            "請系統管理者恢復模型補充分析，恢復後重新產生報告並保留事實核查。"
        ),
        "LLM API key": "模型連線設定",
        "官方 IR 文件": "官方投資人關係文件",
        "規則引擎草稿": "資料規則草稿",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def quality_issue_html(gate: dict) -> str:
    blockers = gate.get("blockers") or []
    warnings = gate.get("warnings") or []
    observations = gate.get("observations") or []
    actions = gate.get("remediation_actions") or []
    if not blockers and not warnings and not observations and not actions:
        return ""
    items = []
    for blocker in blockers:
        items.append(f"<li><strong>阻擋：</strong>{escape(investor_friendly_quality_text(blocker))}</li>")
    for warning in warnings:
        items.append(f"<li><strong>警示：</strong>{escape(investor_friendly_quality_text(warning))}</li>")
    for observation in observations:
        items.append(f"<li><strong>觀察：</strong>{escape(investor_friendly_quality_text(observation))}</li>")
    action_items = "".join(f"<li>{escape(investor_friendly_quality_text(action))}</li>" for action in actions)
    action_html = (
        "<div class='quality-actions'><strong>建議補強</strong><ul>" + action_items + "</ul></div>"
        if action_items
        else ""
    )
    issue_html = "<ul>" + "".join(items) + "</ul>" if items else ""
    if blockers:
        title = "品質阻擋"
        severity_class = "quality-blockers"
    elif warnings:
        title = "品質警示"
        severity_class = "quality-warnings"
    elif actions:
        title = "建議補強"
        severity_class = "quality-actions-only"
    else:
        title = "品質觀察"
        severity_class = "quality-observations"
    return f"<section class='panel quality-issues {severity_class}'><h2>{title}</h2>{issue_html}{action_html}</section>"


def auto_follow_up_status_html(
    auto_follow_up: Optional[dict],
    current_report_id: object = None,
    current_topic: object = None,
    current_tickers: Optional[list] = None,
) -> str:
    if not isinstance(auto_follow_up, dict) or not auto_follow_up:
        return ""
    status = auto_follow_up.get("status")
    if status in {None, "not_needed", "disabled"}:
        return ""
    summary = auto_follow_up.get("summary") or {}
    selected = summary.get("selected") or {}
    execution = summary.get("execution") or {}
    rerun_raw = auto_follow_up.get("rerun_report")
    rerun = rerun_raw if isinstance(rerun_raw, dict) else {}
    next_report = rerun.get("report_id")
    source_report_id = auto_follow_up.get("source_report_id")
    source_topic = auto_follow_up.get("source_report_topic")
    source_tickers = auto_follow_up.get("source_report_tickers") or []
    rerun_request = rerun.get("request") if isinstance(rerun.get("request"), dict) else {}
    rerun_topic = rerun_request.get("topic") or rerun.get("topic")
    next_report_is_newer = bool(next_report and current_report_id and str(next_report) != str(current_report_id))
    if source_report_id and current_report_id and str(source_report_id) != str(current_report_id):
        return ""
    if next_report_is_newer and not source_topic:
        return ""
    if current_topic and source_topic and str(current_topic) != str(source_topic):
        return ""
    if current_topic and rerun_topic and str(current_topic) != str(rerun_topic):
        return ""
    if source_topic and rerun_topic and str(source_topic) != str(rerun_topic):
        return ""
    if next_report_is_newer and not rerun_topic:
        return ""
    if current_tickers and isinstance(source_tickers, list) and source_tickers:
        if [str(ticker) for ticker in source_tickers] != [str(ticker) for ticker in current_tickers]:
            return ""
    if next_report_is_newer and not source_tickers:
        return ""
    skipped_reason = rerun.get("reason")
    if status == "failed":
        title = "自動補強未完成"
        body = escape(str(auto_follow_up.get("reason") or "補強流程執行失敗，請稍後重試。"))
        tone = "auto-failed"
    elif status == "unavailable":
        title = "自動補強暫時無法啟動"
        body = escape(str(auto_follow_up.get("reason") or "後端補強服務暫時無法連線。"))
        tone = "auto-paused"
    elif status == "running":
        title = "自動補強執行中"
        body = (
            f"系統正在處理 {len(auto_follow_up.get('planned_actions') or [])} 項補強任務；"
            "完成後會更新補強紀錄，必要時產生新版報告。"
        )
        tone = "auto-started"
    elif status == "queued":
        title = "已排入自動補強"
        body = (
            f"系統已偵測到必要資料缺口，排入 {int(selected.get('required_count') or selected.get('total_count') or 0)} "
            "項補強任務；完成後會依完成檢查決定是否重跑報告。"
        )
        tone = "auto-started"
    elif next_report_is_newer:
        if not source_report_id or str(source_report_id) != str(current_report_id):
            return ""
        title = "已有新版報告可查看"
        body = (
            f"目前畫面是報告 #{escape(str(current_report_id))}；"
            f"自動補強已另產生新版報告 #{escape(str(next_report))}。"
            "請切換到新版檢視補強後結論，避免把舊版內容誤認為已更新。"
        )
        tone = "auto-paused"
    elif next_report:
        title = "已自動補強並產生新版報告"
        body = (
            f"系統偵測到資料缺口後已啟動 {int(selected.get('total_count') or 0)} 項補強，"
            f"補入/更新 {int(execution.get('stored_count') or 0)} 筆資料，並產生報告 #{escape(str(next_report))}。"
        )
        tone = "auto-started"
    elif skipped_reason:
        title = "已自動補強，重跑暫停"
        body = escape(str(skipped_reason))
        tone = "auto-paused"
    else:
        title = "已自動啟動補強"
        body = (
            f"系統偵測到資料缺口後已啟動 {int(selected.get('total_count') or 0)} 項補強，"
            f"補入/更新 {int(execution.get('stored_count') or 0)} 筆資料。"
        )
        tone = "auto-started"
    return f"""
    <section class="auto-follow-up {tone}">
      <div>
        <strong>{escape(title)}</strong>
        <p>{body}</p>
      </div>
    </section>
    """


def metric_percent(value: object) -> str:
    return "未評估" if value is None else f"{float(value or 0):.0%}"


def metric_int(value: object) -> str:
    return "未評估" if value is None else str(value)


def metric_number(value: object) -> str:
    if value is None:
        return "未評估"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def metric_count_from_payload(
    result: Optional[dict],
    list_key: str,
    metrics: dict,
    metric_key: str,
    default: object = "-",
) -> object:
    if result and list_key in result and isinstance(result.get(list_key), list):
        return len(result.get(list_key) or [])
    value = metrics.get(metric_key)
    return value if value is not None else default


def confidence_label(value: object) -> str:
    return format_confidence_score(float(value)) if value is not None else "未匯入"


def plan_quality_label(metrics: dict) -> str:
    status = metrics.get("discovery_plan_status")
    score = metrics.get("discovery_plan_score")
    if status is None and score is None:
        return "未評估"
    labels = {
        "ready": "完整",
        "caution": "可用",
        "insufficient": "不足",
        "unknown": "未評估",
    }
    label = labels.get(str(status or "unknown"), str(status or "未評估"))
    if score is None:
        return label
    return f"{label}（{int(float(score))} 分）"
