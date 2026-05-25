from __future__ import annotations


STATUS_LABELS = {
    "evidence_supported": "正式分析",
    "weak_evidence": "弱證據觀察",
    "needs_evidence": "待補證據",
}


def candidate_audit_summary(candidates: list[dict], promoted_tickers: list[str] | None = None) -> dict:
    promoted = set(promoted_tickers or [])
    candidate_tickers = {str(candidate.get("ticker") or "") for candidate in candidates}
    supported = sum(1 for candidate in candidates if candidate.get("status") == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.get("status") == "weak_evidence")
    needs = sum(1 for candidate in candidates if candidate.get("status") == "needs_evidence")
    return {
        "total": len(candidates),
        "promoted_count": len(promoted & candidate_tickers) if promoted else supported,
        "supported_count": supported,
        "weak_count": weak,
        "needs_evidence_count": needs,
        "excluded_count": weak + needs,
    }


def render_candidate_audit_markdown(candidates: list[dict], promoted_tickers: list[str] | None = None) -> str:
    if not candidates:
        return (
            "本次沒有 AI 候選公司審計資料；若是手動指定股票，系統只會分析指定白名單，"
            "不會顯示被排除公司。"
        )

    promoted = set(promoted_tickers or [])
    summary = candidate_audit_summary(candidates, list(promoted))
    lines = [
        "本段保留 AI 初始候選到正式分析的完整軌跡；沒有升格不代表公司無關，而是目前證據未達正式分析門檻。",
        "",
        "| 項目 | 數量 |",
        "|---|---:|",
        f"| AI 初始候選 | {summary['total']} |",
        f"| 正式分析 | {summary['promoted_count']} |",
        f"| 弱證據觀察 | {summary['weak_count']} |",
        f"| 待補證據 | {summary['needs_evidence_count']} |",
        "",
        "| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 |",
        "|---|---|---|---:|---|---|",
    ]
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or "")
        name = str(candidate.get("name") or "")
        status = str(candidate.get("status") or "")
        evidence_count = int(candidate.get("evidence_count") or 0)
        source_count = int(candidate.get("evidence_source_count") or 0)
        reason = candidate.get("validation_reason") or candidate_audit_reason(evidence_count, source_count)
        next_action = candidate.get("next_action") or candidate_audit_next_action(evidence_count, source_count)
        if ticker in promoted:
            status = "evidence_supported"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{ticker} {name}".strip(),
                    str(candidate.get("segment") or "未分類"),
                    STATUS_LABELS.get(status, status or "待補證據"),
                    f"{evidence_count} 篇 / {source_count} 來源",
                    str(reason),
                    str(next_action),
                ]
            )
            + " |"
        )
    evidence_lines = render_candidate_evidence_markdown(candidates)
    if evidence_lines:
        lines.extend(["", "### 候選公司代表來源", "", *evidence_lines])
    return "\n".join(lines)


def render_candidate_evidence_markdown(candidates: list[dict]) -> list[str]:
    lines = []
    for candidate in candidates:
        sources = candidate.get("evidence_sources") or []
        if not sources:
            continue
        ticker = str(candidate.get("ticker") or "")
        name = str(candidate.get("name") or "")
        lines.append(f"- {ticker} {name}".strip())
        for source in sources[:2]:
            title = str(source.get("title") or "未命名來源")
            publisher = str(source.get("publisher") or "未標示發布者")
            published_at = source.get("published_at") or "未標示日期"
            url = source.get("url") or ""
            suffix = f"（{publisher}，{published_at}）"
            if url:
                suffix += f" {url}"
            lines.append(f"  - {title}{suffix}")
    return lines


def candidate_audit_reason(evidence_count: int, source_count: int) -> str:
    if evidence_count >= 2 and source_count >= 2:
        return "通過正式分析門檻。"
    if evidence_count > 0:
        return f"弱證據：目前只有 {evidence_count} 篇、{source_count} 個來源。"
    return "待補證據：缺少公司與主題同時成立的來源。"


def candidate_audit_next_action(evidence_count: int, source_count: int) -> str:
    if evidence_count >= 2 and source_count >= 2:
        return "納入正式分析。"
    if evidence_count > 0:
        return "補抓更多來源後再驗證。"
    return "重新補抓公司層級來源。"
