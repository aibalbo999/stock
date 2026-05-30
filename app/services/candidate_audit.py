from __future__ import annotations

import re
from typing import Optional

from app.services.candidate_confidence import format_confidence_score, is_low_formal_confidence


STATUS_LABELS = {
    "evidence_supported": "正式分析",
    "weak_evidence": "弱證據觀察",
    "needs_evidence": "待補證據",
    "evidence_limited": "補查後未升格",
    "evidence_unavailable": "資料不足排除",
}


def candidate_audit_summary(candidates: list[dict], promoted_tickers: list[str] | None = None) -> dict:
    promoted = set(promoted_tickers or [])
    candidate_tickers = {str(candidate.get("ticker") or "") for candidate in candidates}
    supported = sum(1 for candidate in candidates if candidate.get("status") == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.get("status") == "weak_evidence")
    needs = sum(1 for candidate in candidates if candidate.get("status") == "needs_evidence")
    limited = sum(1 for candidate in candidates if candidate.get("status") == "evidence_limited")
    unavailable = sum(1 for candidate in candidates if candidate.get("status") == "evidence_unavailable")
    return {
        "total": len(candidates),
        "promoted_count": len(promoted & candidate_tickers) if promoted else supported,
        "supported_count": supported,
        "weak_count": weak,
        "needs_evidence_count": needs,
        "limited_count": limited,
        "unavailable_count": unavailable,
        "excluded_count": weak + needs + limited + unavailable,
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
        "本段保留 AI 初始候選到正式分析的完整軌跡；沒有升格不代表公司無關。官方文件缺口代表系統尚未成功取得或解析，不代表公司沒有公告資料。",
        "",
        "| 項目 | 數量 |",
        "|---|---:|",
        f"| AI 初始候選 | {summary['total']} |",
        f"| 正式分析 | {summary['promoted_count']} |",
        f"| 弱證據觀察 | {summary['weak_count']} |",
        f"| 待補證據 | {summary['needs_evidence_count']} |",
        f"| 補查後未升格 | {summary['limited_count']} |",
        f"| 資料不足排除 | {summary['unavailable_count']} |",
        "",
        "| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 | 信心 |",
        "|---|---|---|---:|---|---|---:|",
    ]
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or "")
        name = str(candidate.get("name") or "")
        status = str(candidate.get("status") or "")
        sources = candidate.get("evidence_sources") or []
        valid_sources = filter_candidate_evidence_sources(candidate, sources)
        invalid_sources_only = bool(sources and not valid_sources)
        evidence_count = int(candidate.get("evidence_count") or 0)
        source_count = int(candidate.get("evidence_source_count") or 0)
        if invalid_sources_only:
            evidence_count = 0
            source_count = 0
        confidence_score = candidate.get("evidence_confidence_score")
        reason = normalize_candidate_audit_text(
            dedupe_reason_fragments(
                "來源標題未直接指向公司實體，已排除為候選證據，需重新補抓公司層級來源。"
                if invalid_sources_only
                else candidate.get("validation_reason")
                or candidate_audit_reason(
                    evidence_count,
                    source_count,
                    confidence_score,
                )
            )
        )
        next_action = normalize_candidate_audit_text(
            candidate.get("next_action")
            or candidate_audit_next_action(
                evidence_count,
                source_count,
                confidence_score,
            )
        )
        confidence = candidate_confidence_text(candidate)
        if ticker in promoted and not invalid_sources_only:
            status = "evidence_supported"
        elif invalid_sources_only and status == "evidence_supported":
            status = "weak_evidence"
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
                    confidence,
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
        sources = filter_candidate_evidence_sources(candidate, candidate.get("evidence_sources") or [])
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


def filter_candidate_evidence_sources(candidate: dict, sources: list[dict]) -> list[dict]:
    ticker = str(candidate.get("ticker") or "")
    name = str(candidate.get("name") or "")
    entity_terms = [term for term in (ticker, name) if term]
    return [
        source
        for source in sources
        if not _looks_like_unrelated_release_source(source, entity_terms)
    ]


def _looks_like_unrelated_release_source(source: dict, entity_terms: list[str]) -> bool:
    haystack = " ".join(
        str(source.get(field) or "")
        for field in ("title", "publisher", "url")
    ).lower()
    release_markers = (
        "google cloud release notes",
        "release notes",
        "changelog",
        "版本資訊",
        "更新日誌",
    )
    if not any(marker in haystack for marker in release_markers):
        return False
    named_terms = [term for term in entity_terms if not term.isdigit()]
    return not any(_contains_entity_term(haystack, term) for term in named_terms)


def _contains_entity_term(haystack: str, term: str) -> bool:
    if not term:
        return False
    if term.isdigit():
        return bool(re.search(rf"(?<!\d){re.escape(term)}(?!\d)", haystack))
    return term.lower() in haystack


def dedupe_reason_fragments(reason: object) -> str:
    text = str(reason or "")
    fragments = [
        fragment.strip(" ；;。.!！?？")
        for fragment in re.split(r"[；;。.!！?？]+", text)
        if fragment.strip(" ；;。.!！?？")
    ]
    if not fragments:
        return text
    seen: set[str] = set()
    deduped = []
    for fragment in fragments:
        if fragment in seen:
            continue
        seen.add(fragment)
        deduped.append(fragment)
    return "；".join(deduped)


_dedupe_reason_fragments = dedupe_reason_fragments


def normalize_candidate_audit_text(value: object) -> str:
    text = str(value or "")
    replacements = {
        "但缺少可解析的高品質官方年報，先降回候選觀察": (
            "系統尚未取得或解析到可用官方年報/法說文字，先降回候選觀察；"
            "這是資料管線缺口，不代表公司沒有公開年報"
        ),
        "缺少可解析的高品質官方年報": (
            "系統尚未取得或解析到可用官方年報/法說文字；"
            "這是資料管線缺口，不代表公司沒有公開年報"
        ),
        "補官方年報、法說會或公司 IR 文字版後再升格為正式分析": (
            "補抓或匯入官方年報、法說會或公司 IR 文字版後再升格為正式分析"
        ),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def candidate_audit_reason(evidence_count: int, source_count: int, confidence_score: Optional[int] = None) -> str:
    if evidence_count >= 2 and source_count >= 2 and is_low_formal_confidence(confidence_score):
        return f"弱證據：篇數與來源數達標，但證據信心只有 {confidence_score} 分。"
    if evidence_count >= 2 and source_count >= 2:
        return "通過正式分析門檻。"
    if evidence_count > 0:
        return f"弱證據：目前只有 {evidence_count} 篇、{source_count} 個來源。"
    return "待補證據：缺少公司與主題同時成立的來源。"


def candidate_audit_next_action(evidence_count: int, source_count: int, confidence_score: Optional[int] = None) -> str:
    if evidence_count >= 2 and source_count >= 2 and is_low_formal_confidence(confidence_score):
        return "補抓有日期、近期且不同發布者的來源後再驗證。"
    if evidence_count >= 2 and source_count >= 2:
        return "納入正式分析。"
    if evidence_count > 0:
        return "補抓更多來源後再驗證。"
    return "重新補抓公司層級來源。"


def candidate_confidence_text(candidate: dict) -> str:
    score = candidate.get("evidence_confidence_score")
    label = candidate.get("evidence_confidence_label") or ""
    latest = candidate.get("latest_evidence_date")
    if score is None:
        return "未評分"
    date_text = f"，最新 {latest}" if latest else ""
    confidence = format_confidence_score(float(score))
    if label and not confidence.startswith(label):
        confidence = f"{label} {int(score)}"
    return f"{confidence}{date_text}"
