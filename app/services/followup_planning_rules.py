from __future__ import annotations

import re
from collections.abc import Callable

from app.services.followup_evidence_queries import needs_company_filing_sources
from app.services.followup_planning_rule_sets import (
    COMPANY_DATA_AUDIT_RULES,
    MONITORING_TRIGGER_RULES,
    QUALITY_METRIC_RULES,
    QUALITY_TEXT_RULES,
    KeywordActionRule,
)


ActionFactory = Callable[..., object]


def from_source_audit(source_audit: dict, tickers: tuple[str, ...], action_factory: ActionFactory) -> list:
    source_relevance = source_audit.get("source_relevance") or {}
    readiness = source_relevance.get("subtopic_readiness") or {}
    missing = [
        name
        for name, detail in readiness.items()
        if isinstance(detail, dict) and detail.get("status") == "missing"
    ]
    weak = [
        name
        for name, detail in readiness.items()
        if isinstance(detail, dict) and detail.get("status") == "weak"
    ]
    actions = []
    if missing:
        actions.append(
            action_factory(
                "ingest_news",
                "來源覆蓋審計缺口：缺少來源覆蓋子題：" + "、".join(missing[:6]),
                (),
                "high",
                "weekly",
                "required",
            )
        )
        actions.append(
            action_factory(
                "rerun_discovery",
                "補齊缺來源子題後，重新驗證主題拆解、候選白名單與來源覆蓋。",
                (),
                "high",
                "once",
                "required",
            )
        )
    elif weak:
        actions.append(
            action_factory(
                "ingest_news",
                "來源覆蓋審計缺口：弱來源子題需補不同發布者或缺少的資料意圖：" + "、".join(weak[:6]),
                (),
                "medium",
                "weekly",
                "required",
            )
        )
    return actions


def from_quality_gate(quality_gate: dict, tickers: tuple[str, ...], action_factory: ActionFactory) -> list:
    actions = []
    metrics = quality_gate.get("metrics") or {}
    for rule in QUALITY_METRIC_RULES:
        if int(metrics.get(rule.metric_key) or 0) > 0:
            actions.append(action_factory(rule.action_type, rule.reason, tickers, rule.priority, rule.frequency))
    issue_text = "；".join(
        [
            *[str(item) for item in quality_gate.get("blockers") or []],
            *[str(item) for item in quality_gate.get("warnings") or []],
            *[str(item) for item in quality_gate.get("remediation_actions") or []],
        ]
    )
    if not issue_text:
        return actions
    actions.extend(actions_from_keyword_rules(issue_text, tickers, action_factory, QUALITY_TEXT_RULES))
    return actions


def from_company_data_audit(audit: dict, fallback_tickers: tuple[str, ...], action_factory: ActionFactory) -> list:
    actions = []
    for row in audit.get("rows") or []:
        if row.get("status") == "sufficient":
            continue
        ticker = str(row.get("ticker") or "")
        tickers = (ticker,) if ticker else fallback_tickers
        missing_text = "；".join(str(item) for item in row.get("missing") or [])
        actions.extend(
            actions_from_keyword_rules(
                missing_text,
                tickers,
                action_factory,
                COMPANY_DATA_AUDIT_RULES,
                reason_prefix="個股資料審計缺口：",
            )
        )
    return actions


def from_monitoring_contexts(contexts: list[dict], fallback_tickers: tuple[str, ...], action_factory: ActionFactory) -> list:
    actions = []
    for context in contexts:
        label = str(context.get("label") or "")
        ticker = extract_ticker(label)
        tickers = (ticker,) if ticker else fallback_tickers
        trigger = "；".join(
            [
                str(context.get("recheck_trigger") or ""),
                str(context.get("avoid_trigger") or ""),
                str(context.get("decision") or ""),
            ]
        )
        actions.extend(actions_from_trigger(trigger, tickers, action_factory))
    return actions


def from_monitoring_markdown(markdown: str, fallback_tickers: tuple[str, ...], action_factory: ActionFactory) -> list:
    rows = markdown_table_rows(markdown, "監控清單", required_headers=("股票", "重新研究條件"))
    actions = []
    for row in rows:
        ticker = extract_ticker(row.get("股票", ""))
        tickers = (ticker,) if ticker else fallback_tickers
        trigger = "；".join([row.get("重新研究條件", ""), row.get("繼續避開/觀察條件", "")])
        actions.extend(actions_from_trigger(trigger, tickers, action_factory))
    return actions


def from_candidate_audit_markdown(
    markdown: str,
    fallback_tickers: tuple[str, ...],
    action_factory: ActionFactory,
    *,
    required: bool = True,
    candidate_limit: int = 5,
) -> list:
    rows = markdown_table_rows(markdown, "候選公司審計", required_headers=("股票", "狀態"))
    if not required:
        rows = top_tracking_candidate_rows(rows, candidate_limit)
    actions = []
    weak_or_missing = []
    purpose = "required" if required else "tracking"
    priority = "high" if required else "medium"
    for row in rows:
        status = row.get("狀態", "")
        if "正式分析" in status:
            continue
        if "補查後未升格" in status:
            continue
        ticker = extract_ticker(row.get("股票", ""))
        tickers = (ticker,) if ticker else fallback_tickers
        confidence = candidate_confidence_field(row)
        reason = "；".join(
            item
            for item in [
                f"股票：{row.get('股票', '')}",
                f"產業位置：{row.get('產業位置', '')}",
                row.get("狀態", ""),
                row.get("證據", ""),
                row.get("排除 / 升格原因", ""),
                row.get("下一步", ""),
                f"信心：{confidence}" if confidence else "",
            ]
            if item
        )
        actions.append(
            action_factory(
                "ingest_news",
                f"候選公司未升格，需補齊公司層級證據：{reason}",
                tickers,
                priority,
                "weekly",
                purpose,
            )
        )
        if needs_company_filing_sources(reason):
            actions.append(
                action_factory(
                    "ingest_company_filings",
                    f"候選公司公開文件不足，需補官方年報、法說會或 IR 文字來源：{reason}",
                    tickers,
                    priority,
                    "monthly",
                    purpose,
                )
            )
        weak_or_missing.append(ticker)
    if weak_or_missing:
        actions.append(
            action_factory(
                "rerun_discovery",
                "補齊弱證據與待補候選後，重新執行主題拆解與候選升格驗證。",
                fallback_tickers,
                priority,
                "once",
                purpose,
            )
        )
    return actions


def top_tracking_candidate_rows(rows: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    candidates = [row for row in rows if "正式分析" not in row.get("狀態", "")]
    return sorted(candidates, key=tracking_candidate_rank)[:limit]


def tracking_candidate_rank(row: dict[str, str]) -> tuple[int, int, int, str]:
    status = row.get("狀態", "")
    evidence_count, source_count = parse_evidence_counts(row.get("證據", ""))
    confidence = parse_confidence_score(candidate_confidence_field(row))
    status_rank = 0 if "弱證據" in status else 1
    return (status_rank, -evidence_count, -source_count, -confidence, row.get("股票", ""))


def candidate_confidence_field(row: dict[str, str]) -> str:
    return row.get("入選支持度") or row.get("入選證據信心") or row.get("信心", "")


def parse_evidence_counts(value: str) -> tuple[int, int]:
    numbers = [int(match) for match in re.findall(r"\d+", value)]
    if not numbers:
        return 0, 0
    if len(numbers) == 1:
        return numbers[0], 0
    return numbers[0], numbers[1]


def parse_confidence_score(value: str) -> int:
    numbers = [int(match) for match in re.findall(r"\d+", value)]
    return numbers[-1] if numbers else 0


def actions_from_keyword_rules(
    text: str,
    tickers: tuple[str, ...],
    action_factory: ActionFactory,
    rules: tuple[KeywordActionRule, ...],
    *,
    reason_prefix: str = "",
) -> list:
    actions = []
    for rule in rules:
        if not has_keywords(text, *rule.keywords):
            continue
        action_tickers = (
            ()
            if rule.topic_level_keywords and has_keywords(text, *rule.topic_level_keywords)
            else tickers
        )
        reason = rule.reason if rule.reason is not None else f"{reason_prefix}{text}"
        actions.append(
            action_factory(
                rule.action_type,
                reason,
                action_tickers,
                rule.priority,
                rule.frequency,
                rule.purpose,
            )
        )
    return actions


def actions_from_trigger(trigger: str, tickers: tuple[str, ...], action_factory: ActionFactory) -> list:
    return actions_from_keyword_rules(
        trigger,
        tickers,
        action_factory,
        MONITORING_TRIGGER_RULES,
        reason_prefix="監控條件觸發：",
    )


def markdown_table_rows(
    markdown: str,
    heading: str,
    required_headers: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    try:
        start = lines.index(f"## {heading}")
    except ValueError:
        return []
    table_lines: list[str] = []
    tables: list[list[str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.strip().startswith("|"):
            table_lines.append(line.strip())
        elif table_lines:
            tables.append(table_lines)
            table_lines = []
    if table_lines:
        tables.append(table_lines)
    for table_lines in tables:
        rows = parse_markdown_table(table_lines, required_headers)
        if rows:
            return rows
    return []


def parse_markdown_table(table_lines: list[str], required_headers: tuple[str, ...] = ()) -> list[dict[str, str]]:
    if len(table_lines) < 3:
        return []
    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    if required_headers and not all(header in headers for header in required_headers):
        return []
    rows = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def extract_ticker(text: str) -> str | None:
    match = re.search(r"\b\d{4}\b", text)
    return match.group(0) if match else None


def has_keywords(text: str, *keywords: str) -> bool:
    return any(keyword in text for keyword in keywords)
