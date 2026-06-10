from __future__ import annotations

from typing import Any


RUNNING_STATUSES = {"queued", "started", "running", "pending", "processing"}
BLOCKED_QUALITY_STATUSES = {"failed", "blocked", "error", "insufficient"}
ATTENTION_QUALITY_STATUSES = {"caution", "warning", "attention", "needs_follow_up"}


def latest_report_lifecycle(
    report_result: dict | None,
    follow_up_plan: dict | None = None,
) -> dict[str, Any]:
    report = _dict_value(report_result)
    plan = _dict_value(follow_up_plan)
    if not report:
        return {
            "overall_state": "attention",
            "trust_label": "尚未有最新版報告",
            "trust_explanation": "先建立分析報告，系統才有可閱讀版本。",
            "primary_action": "建立分析",
            "route_hint": "analysis",
            "report_id": None,
            "stage_cards": [
                _stage("data", "資料", "unknown", "尚無報告", "目前沒有可判讀的最新版報告。"),
                _stage("quality", "品質", "unknown", "尚無 Gate", "建立報告後才會有品質門檻結果。"),
                _stage("follow_up", "補強", "unknown", "尚無狀態", "目前沒有補強計畫。"),
                _stage("rerun", "重跑", "unknown", "尚無狀態", "目前沒有重跑建議。"),
                _stage("readable", "可讀", "unknown", "待建立", "建立報告後才會出現可讀版本。"),
            ],
        }

    report_id = report.get("report_id") or report.get("id")
    topic = _text(report.get("topic"), default="未命名報告")
    quality_gate = _dict_value(report.get("quality_gate"))
    quality_status = _text(quality_gate.get("status"), default="-").casefold()
    metrics = _dict_value(quality_gate.get("metrics"))
    promoted_count = _promoted_count(report, metrics)
    candidate_count = _candidate_count(report)
    required_count = _required_count(plan)
    follow_up_status = _follow_up_status(report, plan)
    running = follow_up_status in RUNNING_STATUSES
    has_rerun_report = _has_rerun_report(report)
    has_incomplete_rerun_report = _has_incomplete_rerun_report(report)

    data_state = "attention" if required_count > 0 else "done"
    data_label = f"缺口 {required_count} 項" if required_count > 0 else "資料可用"
    data_detail = (
        "最新版報告仍有必補資料缺口，先補資料再重跑。"
        if required_count > 0
        else "未發現必補資料缺口。"
    )

    if promoted_count <= 0:
        quality_state = "blocked"
        quality_label = "正式分析 0 檔"
        quality_detail = "品質門檻沒有產生正式分析股票，報告不可直接採信。"
    elif quality_status in BLOCKED_QUALITY_STATUSES:
        quality_state = "blocked"
        quality_label = quality_status
        quality_detail = "品質門檻失敗，先處理阻塞原因。"
    elif quality_status in ATTENTION_QUALITY_STATUSES:
        quality_state = "attention"
        quality_label = "需留意"
        quality_detail = f"品質門檻為 {quality_status}，閱讀時需要保留警示。"
    else:
        quality_state = "done"
        quality_label = "品質可讀"
        quality_detail = "品質門檻可支援閱讀最新版報告。"

    if running:
        follow_up_state = "running"
        follow_up_label = "補強執行中"
        follow_up_detail = "補強任務已送出或正在執行，先到維護頁追蹤任務。"
    elif required_count > 0:
        follow_up_state = "attention"
        follow_up_label = "需補強"
        follow_up_detail = "有必補缺口，建議先完成資料補強。"
    else:
        follow_up_state = "done"
        follow_up_label = "無必補缺口"
        follow_up_detail = "目前沒有必要補強項目。"

    if running:
        rerun_state = "running"
        rerun_label = "等待補強完成"
        rerun_detail = "補強完成後再確認是否已有重跑報告。"
    elif required_count > 0:
        rerun_state = "attention"
        rerun_label = "補強後重跑"
        rerun_detail = "資料補完後建議重跑，讓最新版只保留最新結論。"
    elif has_rerun_report:
        rerun_state = "done"
        rerun_label = "已有重跑"
        rerun_detail = "補強後的重跑報告已記錄在最新版流程中。"
    elif has_incomplete_rerun_report:
        rerun_state = "attention"
        rerun_label = "重跑未完成"
        rerun_detail = "補強流程已有重跑紀錄，但尚未產生可讀的重跑報告。"
    else:
        rerun_state = "done"
        rerun_label = "不需重跑"
        rerun_detail = "目前沒有因必補缺口而需要重跑。"

    if quality_state == "blocked":
        readable_state = "blocked"
        readable_label = "不可採信"
        readable_detail = "先處理品質或資料問題，再閱讀投資結論。"
    elif required_count > 0 or quality_state == "attention":
        readable_state = "attention"
        readable_label = "可讀但需註記"
        readable_detail = "可先閱讀脈絡，但投資判讀需標示資料限制。"
    else:
        readable_state = "done"
        readable_label = "可閱讀"
        readable_detail = "這份報告可作為目前最新版閱讀。"

    stage_cards = [
        _stage("data", "資料", data_state, data_label, data_detail),
        _stage("quality", "品質", quality_state, quality_label, quality_detail),
        _stage("follow_up", "補強", follow_up_state, follow_up_label, follow_up_detail),
        _stage("rerun", "重跑", rerun_state, rerun_label, rerun_detail),
        _stage("readable", "可讀", readable_state, readable_label, readable_detail),
    ]
    overall_state = _overall_state(stage_cards)
    trust_label = _trust_label(overall_state)
    primary_action, route_hint = _primary_action(
        overall_state=overall_state,
        report_id=report_id,
        required_count=required_count,
        running=running,
    )
    return {
        "overall_state": overall_state,
        "trust_label": trust_label,
        "trust_explanation": _trust_explanation(
            overall_state,
            topic=topic,
            candidate_count=candidate_count,
            promoted_count=promoted_count,
            required_count=required_count,
            stage_cards=stage_cards,
        ),
        "primary_action": primary_action,
        "route_hint": route_hint,
        "report_id": report_id,
        "stage_cards": stage_cards,
    }


def stage_by_key(lifecycle: dict, key: str) -> dict:
    for stage in lifecycle.get("stage_cards") or []:
        if isinstance(stage, dict) and stage.get("key") == key:
            return stage
    return {}


def _stage(key: str, title: str, state: str, label: str, detail: str) -> dict[str, str]:
    return {
        "key": key,
        "title": title,
        "state": state,
        "label": label,
        "detail": detail,
    }


def _overall_state(stage_cards: list[dict[str, str]]) -> str:
    states = [stage["state"] for stage in stage_cards]
    if "blocked" in states:
        return "blocked"
    if "running" in states:
        return "running"
    if "attention" in states:
        return "attention"
    return "ready"


def _trust_label(overall_state: str) -> str:
    return {
        "ready": "可閱讀",
        "running": "補強中",
        "attention": "可閱讀但需註記",
        "blocked": "不可直接採信",
    }.get(overall_state, "需人工確認")


def _trust_explanation(
    overall_state: str,
    *,
    topic: str,
    candidate_count: int,
    promoted_count: int,
    required_count: int,
    stage_cards: list[dict[str, str]],
) -> str:
    if overall_state == "blocked":
        return f"{topic} 報告目前正式分析 {promoted_count} 檔，需先補強資料或品質門檻。"
    if overall_state == "running":
        return f"{topic} 報告正在補強，等待背景任務完成後再閱讀最新版。"
    if overall_state == "attention":
        if required_count > 0:
            return (
                f"{topic} 報告候選 {candidate_count} 檔、正式分析 {promoted_count} 檔，"
                f"仍有 {required_count} 項必補缺口。"
            )
        attention_stages = [
            stage
            for stage in stage_cards
            if stage.get("state") == "attention" and stage.get("key") != "readable"
        ]
        if attention_stages:
            details = "；".join(stage["detail"] for stage in attention_stages if stage.get("detail"))
            return (
                f"{topic} 報告候選 {candidate_count} 檔、正式分析 {promoted_count} 檔，"
                f"{details}"
            )
        return (
            f"{topic} 報告候選 {candidate_count} 檔、正式分析 {promoted_count} 檔，"
            "需人工確認生命週期狀態。"
        )
    return f"{topic} 報告候選 {candidate_count} 檔、正式分析 {promoted_count} 檔，可作為最新版閱讀。"


def _primary_action(
    *,
    overall_state: str,
    report_id: Any,
    required_count: int,
    running: bool,
) -> tuple[str, str]:
    if running or overall_state == "running":
        return "查看補強任務", "settings:maintenance"
    if overall_state == "blocked" or required_count > 0:
        return "補強資料", "data_enrichment"
    if report_id is not None:
        return "閱讀最新版", f"report:{report_id}"
    return "建立分析", "analysis"


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _promoted_count(report: dict, metrics: dict) -> int:
    if "promoted_count" in metrics:
        return _int_value(metrics.get("promoted_count"))
    promoted = report.get("promoted_tickers")
    if isinstance(promoted, list):
        return len(promoted)
    tickers = report.get("tickers")
    if isinstance(tickers, list):
        return len(tickers)
    return 0


def _candidate_count(report: dict) -> int:
    candidates = report.get("candidate_whitelist")
    if isinstance(candidates, list):
        return len(candidates)
    tickers = report.get("tickers")
    if isinstance(tickers, list):
        return len(tickers)
    return 0


def _required_count(plan: dict) -> int:
    summary = _dict_value(plan.get("summary"))
    selected = _dict_value(summary.get("selected"))
    if "required_count" in selected:
        return _int_value(selected.get("required_count"))
    return _int_value(summary.get("required_count"))


def _follow_up_status(report: dict, plan: dict) -> str:
    plan_status = _text(plan.get("status")).casefold()
    if plan_status:
        return plan_status
    auto_follow_up = _dict_value(report.get("auto_follow_up"))
    return _text(auto_follow_up.get("status")).casefold()


def _has_rerun_report(report: dict) -> bool:
    auto_follow_up = _dict_value(report.get("auto_follow_up"))
    rerun_report = _dict_value(auto_follow_up.get("rerun_report"))
    return bool(rerun_report.get("report_id"))


def _has_incomplete_rerun_report(report: dict) -> bool:
    auto_follow_up = _dict_value(report.get("auto_follow_up"))
    rerun_report = auto_follow_up.get("rerun_report")
    return isinstance(rerun_report, dict) and not bool(rerun_report.get("report_id"))
