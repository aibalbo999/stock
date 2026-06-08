from __future__ import annotations

import re
from collections.abc import Callable

from app.services.followup_evidence import needs_company_filing_sources


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
    if int(metrics.get("market_stale_count") or 0) > 0:
        actions.append(
            action_factory("refresh_market", "快取救援資料：刷新股價歷史、成交量與近況訊號。", tickers, "high", "weekly")
        )
    if int(metrics.get("monthly_revenue_stale_count") or 0) > 0:
        actions.append(
            action_factory("refresh_monthly_revenue", "快取救援資料：刷新月營收與成長加速資料。", tickers, "high", "monthly")
        )
    if int(metrics.get("financial_metrics_stale_ticker_count") or 0) > 0:
        actions.append(
            action_factory("refresh_financial_metrics", "快取救援資料：刷新近五年財務資料。", tickers, "high", "monthly")
        )
    if int(metrics.get("valuation_stale_count") or 0) > 0:
        actions.append(
            action_factory("refresh_valuations", "快取救援資料：刷新估值與同業比較資料。", tickers, "high", "weekly")
        )
    issue_text = "；".join(
        [
            *[str(item) for item in quality_gate.get("blockers") or []],
            *[str(item) for item in quality_gate.get("warnings") or []],
            *[str(item) for item in quality_gate.get("remediation_actions") or []],
        ]
    )
    if not issue_text:
        return actions
    if has_keywords(issue_text, "股價", "成交量", "領先訊號", "近況訊號"):
        actions.append(
            action_factory("refresh_market", "補齊股價歷史、成交量與近況訊號。", tickers, "high", "weekly")
        )
    if has_keywords(issue_text, "月營收", "營收"):
        actions.append(action_factory("refresh_monthly_revenue", "補齊月營收與成長加速資料。", tickers, "high", "monthly"))
    if has_keywords(issue_text, "五年財務", "財務指標", "財務資料"):
        actions.append(action_factory("refresh_financial_metrics", "補齊近五年財務資料。", tickers, "medium", "monthly"))
    if has_keywords(issue_text, "估值", "P/E", "DCF", "同業"):
        actions.append(action_factory("refresh_valuations", "補齊估值與同業比較資料。", tickers, "medium", "weekly"))
    if has_keywords(issue_text, "資料來源", "來源", "新聞", "國際", "發布者", "時間戳", "近期資料"):
        target_tickers = () if has_keywords(issue_text, "主題拆解子題", "來源覆蓋子題") else tickers
        actions.append(
            action_factory(
                "ingest_news",
                "補抓近期與國際資料源，提高 RAG 證據覆蓋。",
                target_tickers,
                "high",
                "weekly",
            )
        )
    if has_keywords(issue_text, "AI 拆解任務", "候選公司", "證據驗證", "正式分析股票"):
        actions.append(action_factory("rerun_discovery", "重新執行 AI 主題拆解與候選白名單驗證。", tickers, "high", "once"))
    if has_keywords(issue_text, "LLM 補充分析", "模型恢復"):
        actions.append(
            action_factory(
                "rerun_analysis",
                "LLM 供應商或 API key 恢復後，重新產生報告並保留來源核查。",
                tickers,
                "high",
                "once",
            )
        )
    return actions


def from_company_data_audit(audit: dict, fallback_tickers: tuple[str, ...], action_factory: ActionFactory) -> list:
    actions = []
    for row in audit.get("rows") or []:
        if row.get("status") == "sufficient":
            continue
        ticker = str(row.get("ticker") or "")
        tickers = (ticker,) if ticker else fallback_tickers
        missing_text = "；".join(str(item) for item in row.get("missing") or [])
        if has_keywords(missing_text, "股價", "成交量"):
            actions.append(action_factory("refresh_market", f"個股資料審計缺口：{missing_text}", tickers, "high"))
        if has_keywords(missing_text, "月營收"):
            actions.append(action_factory("refresh_monthly_revenue", f"個股資料審計缺口：{missing_text}", tickers, "high"))
        if has_keywords(missing_text, "五年財報", "核心財報", "財報"):
            actions.append(action_factory("refresh_financial_metrics", f"個股資料審計缺口：{missing_text}", tickers, "medium"))
        if has_keywords(missing_text, "估值"):
            actions.append(action_factory("refresh_valuations", f"個股資料審計缺口：{missing_text}", tickers, "medium"))
        if has_keywords(missing_text, "公司原始公開文件", "公開文件"):
            actions.append(
                action_factory(
                    "ingest_company_filings",
                    f"個股資料審計缺口：{missing_text}",
                    tickers,
                    "high",
                    "monthly",
                    "required",
                )
            )
        if has_keywords(missing_text, "公司文本", "公司層級文本", "文本證據", "AI 歸因", "入庫"):
            actions.append(
                action_factory(
                    "ingest_news",
                    f"個股資料審計缺口：{missing_text}",
                    tickers,
                    "high",
                    "weekly",
                    "required",
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


def actions_from_trigger(trigger: str, tickers: tuple[str, ...], action_factory: ActionFactory) -> list:
    actions = []
    if has_keywords(trigger, "股價歷史", "股價", "成交量", "領先訊號", "近況訊號"):
        actions.append(action_factory("refresh_market", f"監控條件觸發：{trigger}", tickers, "high", "weekly", "tracking"))
    if has_keywords(trigger, "月營收", "營收"):
        actions.append(action_factory("refresh_monthly_revenue", f"監控條件觸發：{trigger}", tickers, "high", "monthly", "tracking"))
    if has_keywords(trigger, "估值", "同業", "P/E", "DCF"):
        actions.append(action_factory("refresh_valuations", f"監控條件觸發：{trigger}", tickers, "medium", "weekly", "tracking"))
    if has_keywords(trigger, "五年財報", "財報", "財務"):
        actions.append(action_factory("refresh_financial_metrics", f"監控條件觸發：{trigger}", tickers, "medium", "monthly", "tracking"))
    if has_keywords(trigger, "新來源", "公司文本", "AI 歸因", "證據", "來源"):
        actions.append(action_factory("ingest_news", f"監控條件觸發：{trigger}", tickers, "medium", "weekly", "tracking"))
    return actions


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
