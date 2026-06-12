from __future__ import annotations

from html import escape
from typing import Optional

from app.services.candidate_confidence import format_confidence_score
from app.services.source_quality import is_low_quality_investor_forum_source
from app.ui.report_markdown import markdown_table_rows_by_header


def normalize_candidate_audit_display_text(value: object) -> str:
    text = str(value or "")
    replacements = {
        "通過正式分析門檻：至少 2 篇公司主題證據、2 個以上來源，且證據信心達高分": (
            "通過候選入選門檻：至少 2 篇公司主題證據、2 個以上來源，且入選支持度達高分；"
            "正式分析可信度仍需另看風險/機會歸因、財報、估值與公司文件"
        ),
        "通過正式分析門檻": "通過候選入選門檻",
        "證據信心": "入選支持度",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def candidate_payload_confidence_text(candidate: dict) -> str:
    score = candidate.get("evidence_confidence_score")
    label = candidate.get("evidence_confidence_label") or "未評分"
    latest = candidate.get("latest_evidence_date")
    if score is None:
        confidence = label
    else:
        confidence = format_confidence_score(float(score))
        if label and not confidence.startswith(str(label)):
            confidence = f"{label} {int(float(score))}"
    if latest:
        confidence += f"，最新 {latest}"
    age = candidate.get("evidence_age_days")
    if candidate.get("evidence_stale") and age is not None:
        confidence += f"（距今約 {int(age)} 天，超過 180 天）"
    return confidence


def candidate_payload_stale_note(candidate: dict) -> str:
    if not candidate.get("evidence_stale"):
        return ""
    latest = candidate.get("latest_evidence_date") or "未標示日期"
    age = candidate.get("evidence_age_days")
    age_text = f"距今約 {int(age)} 天，" if age is not None else ""
    return f"最新候選來源為 {latest}，{age_text}已超過 180 天新鮮度門檻。"


def candidate_source_matches_display_entity(candidate: dict, source: dict) -> bool:
    haystack = " ".join(
        str(source.get(field) or "")
        for field in ("title", "publisher", "url")
    ).lower()
    if is_low_quality_investor_forum_source(
        title=source.get("title"),
        publisher=source.get("publisher"),
        url=source.get("url"),
    ):
        return False
    ticker = str(candidate.get("ticker") or "")
    name = str(candidate.get("name") or "")
    if name == "南亞" and "南亞科" in haystack and ticker not in haystack:
        return False
    return True


def candidate_audit_priority_key(card: str) -> int:
    if "audit-weak" in card:
        return 0
    if "audit-needs" in card:
        return 1
    if "audit-limited" in card:
        return 2
    if "audit-unavailable" in card:
        return 3
    return 4


def candidate_audit_summary_and_cards(markdown: str, result: Optional[dict] = None) -> tuple[str, list[str]]:
    candidates = result.get("candidate_whitelist", []) if result else []
    rows = []
    if candidates:
        status_labels = {
            "evidence_supported": "正式分析",
            "weak_evidence": "弱證據觀察",
            "needs_evidence": "待補證據",
            "evidence_limited": "補查後未升格",
            "evidence_unavailable": "資料不足排除",
        }
        for candidate in candidates:
            raw_sources = candidate.get("evidence_sources") or []
            evidence_sources = [
                source
                for source in raw_sources
                if candidate_source_matches_display_entity(candidate, source)
            ]
            filtered_source_count = max(0, len(raw_sources) - len(evidence_sources))
            filtered_note = (
                f"已排除 {filtered_source_count} 筆疑似同名或非本公司的來源。"
                if filtered_source_count
                else ""
            )
            source_summary = "；".join(
                " / ".join(
                    part
                    for part in [
                        str(source.get("title") or ""),
                        str(source.get("publisher") or ""),
                        str(source.get("published_at") or ""),
                    ]
                    if part
                )
                for source in evidence_sources[:2]
            )
            rows.append(
                [
                    f"{candidate.get('ticker')} {candidate.get('name')}",
                    candidate.get("segment") or "未分類",
                    status_labels.get(candidate.get("status"), "待補證據"),
                    (
                        f"{int(candidate.get('evidence_count') or 0)} 篇 / "
                        f"{int(candidate.get('evidence_source_count') or 0)} 來源"
                        + (f"（排除 {filtered_source_count}）" if filtered_source_count else "")
                    ),
                    normalize_candidate_audit_display_text(
                        f"{candidate_payload_stale_note(candidate)}"
                        f"{filtered_note}"
                        f"{candidate.get('validation_reason') or ''}"
                    ),
                    normalize_candidate_audit_display_text(candidate.get("next_action") or ""),
                    source_summary,
                    candidate_payload_confidence_text(candidate),
                ]
            )
    else:
        rows = markdown_table_rows_by_header(markdown, "候選公司審計", "股票", limit=30)
    if not rows:
        return "", []

    supported = [row for row in rows if len(row) > 2 and "正式分析" in row[2]]
    weak = [row for row in rows if len(row) > 2 and "弱證據" in row[2]]
    needs = [row for row in rows if len(row) > 2 and "待補" in row[2]]
    limited = [row for row in rows if len(row) > 2 and "補查後未升格" in row[2]]
    unavailable = [row for row in rows if len(row) > 2 and "資料不足排除" in row[2]]
    cards = []
    for row in rows:
        stock = escape(row[0]) if len(row) > 0 else "-"
        segment = escape(row[1]) if len(row) > 1 else "-"
        status_raw = row[2] if len(row) > 2 else "待補證據"
        status = escape(status_raw)
        evidence = escape(row[3]) if len(row) > 3 else "-"
        reason = escape(row[4]) if len(row) > 4 else ""
        next_action = escape(row[5]) if len(row) > 5 else ""
        source_summary = escape(row[6]) if candidates and len(row) > 6 else ""
        confidence = escape(row[7] if candidates and len(row) > 7 else row[6] if not candidates and len(row) > 6 else "")
        status_class = (
            "audit-supported"
            if "正式分析" in status_raw
            else "audit-weak"
            if "弱證據" in status_raw
            else "audit-limited"
            if "補查後未升格" in status_raw
            else "audit-unavailable"
            if "資料不足排除" in status_raw
            else "audit-needs"
        )
        cards.append(
            f"""
            <article class="audit-card {status_class}">
              <div>
                <div class="ticker">{stock}</div>
                <div class="reason">{segment}</div>
                <div class="audit-reason">{reason}</div>
                <div class="audit-next">{next_action}</div>
                {"<div class='audit-source'>" + source_summary + "</div>" if source_summary else ""}
              </div>
              <div class="audit-meta">
                <span>{status}</span>
                <span>{evidence}</span>
                {"<span>" + confidence + "</span>" if confidence else ""}
              </div>
            </article>
            """
        )
    summary = (
        "<div class='audit-summary'>"
        f"<span>候選卡片 {len(rows)}</span>"
        f"<span>正式分析 {len(supported)}</span>"
        f"<span>弱證據 {len(weak)}</span>"
        f"<span>待補證據 {len(needs)}</span>"
        f"<span>補查後未升格 {len(limited)}</span>"
        f"<span>資料不足排除 {len(unavailable)}</span>"
        "</div>"
    )
    return summary, cards


def candidate_audit_html(markdown: str, result: Optional[dict] = None) -> str:
    summary, cards = candidate_audit_summary_and_cards(markdown, result)
    return summary + "".join(cards) if cards else ""
