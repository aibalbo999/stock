from __future__ import annotations

from collections.abc import Callable

from app.services.followup_evidence_queries import needs_company_filing_sources


ActionFactory = Callable[..., object]


def source_audit_actions(
    missing: list[str],
    weak: list[str],
    action_factory: ActionFactory,
) -> list:
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


def candidate_audit_reason(row: dict[str, str], confidence: str) -> str:
    return "；".join(
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


def candidate_audit_actions(
    reason: str,
    tickers: tuple[str, ...],
    priority: str,
    purpose: str,
    action_factory: ActionFactory,
) -> list:
    actions = [
        action_factory(
            "ingest_news",
            f"候選公司未升格，需補齊公司層級證據：{reason}",
            tickers,
            priority,
            "weekly",
            purpose,
        )
    ]
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
    return actions


def candidate_rerun_discovery_action(
    fallback_tickers: tuple[str, ...],
    priority: str,
    purpose: str,
    action_factory: ActionFactory,
) -> object:
    return action_factory(
        "rerun_discovery",
        "補齊弱證據與待補候選後，重新執行主題拆解與候選升格驗證。",
        fallback_tickers,
        priority,
        "once",
        purpose,
    )
