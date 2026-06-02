from __future__ import annotations

import re
from datetime import date
from typing import Optional

from app.core.time import today_taipei
from app.services.candidate_confidence import format_confidence_score, is_low_formal_confidence
from app.services.entity_mapping import CONFUSING_ENTITY_PREFIXES, alias_matches_text
from app.services.source_quality import is_formal_evidence_source

STALE_CANDIDATE_EVIDENCE_DAYS = 180

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
    supported_tickers = {
        str(candidate.get("ticker") or "")
        for candidate in candidates
        if candidate.get("status") == "evidence_supported"
    }
    supported = sum(1 for candidate in candidates if candidate.get("status") == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.get("status") == "weak_evidence")
    needs = sum(1 for candidate in candidates if candidate.get("status") == "needs_evidence")
    limited = sum(1 for candidate in candidates if candidate.get("status") == "evidence_limited")
    unavailable = sum(1 for candidate in candidates if candidate.get("status") == "evidence_unavailable")
    return {
        "total": len(candidates),
        "promoted_count": len(promoted & candidate_tickers & supported_tickers) if promoted else supported,
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
        "本段保留 AI 初始候選到正式分析的完整軌跡；沒有升格不代表公司無關。官方文件缺口代表系統尚未成功取得或解析，不代表公司沒有公告資料。入選支持度只表示候選公司與主題的來源支持度，不等於前段正式報告的分析可信度或投資建議強度；分析可信度仍需另看風險/機會歸因、財報、估值、公司文件與近況資料。",
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
        "| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 | 入選支持度 |",
        "|---|---|---|---:|---|---|---:|",
    ]
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or "")
        name = str(candidate.get("name") or "")
        status = str(candidate.get("status") or "")
        sources = candidate.get("evidence_sources") or []
        valid_sources = filter_candidate_evidence_sources(candidate, sources)
        invalid_sources_only = bool(sources and not valid_sources)
        filtered_source_count = max(0, len(sources) - len(valid_sources))
        evidence_count = int(candidate.get("evidence_count") or 0)
        source_count = int(candidate.get("evidence_source_count") or 0)
        if invalid_sources_only:
            evidence_count = 0
            source_count = 0
        confidence_score = candidate.get("evidence_confidence_score")
        reason = normalize_candidate_audit_text(
            append_stale_evidence_note(
                candidate,
                dedupe_reason_fragments(
                    "來源標題未直接指向公司實體，已排除為候選證據，需重新補抓公司層級來源。"
                    if invalid_sources_only
                    else candidate.get("validation_reason")
                    or candidate_audit_reason(
                        evidence_count,
                        source_count,
                        confidence_score,
                    )
                ),
            )
        )
        if filtered_source_count and not invalid_sources_only:
            reason = dedupe_reason_fragments(
                f"{reason}；已排除 {filtered_source_count} 筆疑似同名或非本公司的來源"
            )
        next_action = normalize_candidate_audit_text(
            append_stale_next_action(
                candidate,
                "重新補抓公司層級來源。"
                if invalid_sources_only
                else candidate.get("next_action")
                or candidate_audit_next_action(
                    evidence_count,
                    source_count,
                    confidence_score,
                ),
            )
        )
        confidence = candidate_confidence_text(candidate)
        if ticker in promoted and status == "evidence_supported" and not invalid_sources_only:
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
        sources = sort_candidate_evidence_sources(
            dedupe_candidate_evidence_sources(
                filter_candidate_evidence_sources(candidate, candidate.get("evidence_sources") or [])
            )
        )
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


def dedupe_candidate_evidence_sources(sources: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for source in sources:
        key = (
            str(source.get("title") or ""),
            str(source.get("publisher") or ""),
            str(source.get("published_at") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def sort_candidate_evidence_sources(sources: list[dict]) -> list[dict]:
    return sorted(
        sources,
        key=lambda source: (
            parse_candidate_source_date(source.get("published_at")) or date.min,
            str(source.get("publisher") or ""),
            str(source.get("title") or ""),
        ),
        reverse=True,
    )


def parse_candidate_source_date(value: object) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def filter_candidate_evidence_sources(candidate: dict, sources: list[dict]) -> list[dict]:
    ticker = str(candidate.get("ticker") or "")
    name = str(candidate.get("name") or "")
    entity_terms = [term for term in (ticker, name) if term]
    return [
        source
        for source in sources
        if _source_matches_candidate_entity(source, entity_terms)
        and not _looks_like_unrelated_release_source(source, entity_terms)
        and _looks_like_formal_evidence_source(source)
    ]


def _source_matches_candidate_entity(source: dict, entity_terms: list[str]) -> bool:
    haystack = " ".join(
        str(source.get(field) or "")
        for field in ("title", "publisher", "url")
    ).lower()
    if any(_contains_entity_term(haystack, term) for term in entity_terms):
        return True
    return not _mentions_confusing_entity_alias(haystack, entity_terms)


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


def _looks_like_formal_evidence_source(source: dict) -> bool:
    return is_formal_evidence_source(
        title=source.get("title"),
        publisher=source.get("publisher"),
        url=source.get("url"),
    )


def _contains_entity_term(haystack: str, term: str) -> bool:
    return alias_matches_text(haystack, term) if term else False


def _mentions_confusing_entity_alias(haystack: str, entity_terms: list[str]) -> bool:
    for term in entity_terms:
        normalized = (term or "").lower()
        if not normalized or normalized.isdigit():
            continue
        for confusing_alias in CONFUSING_ENTITY_PREFIXES.get(normalized, ()):
            if confusing_alias.lower() in haystack:
                return True
    return False


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


def append_stale_evidence_note(candidate: dict, text: str) -> str:
    age_days = candidate_evidence_age_days(candidate)
    if age_days is None or age_days <= STALE_CANDIDATE_EVIDENCE_DAYS:
        return text
    latest = candidate.get("latest_evidence_date")
    note = f"最新候選來源為 {latest}，距今約 {age_days} 天，已超過 180 天新鮮度門檻"
    if note in text or "新鮮度門檻" in text:
        return text
    return dedupe_reason_fragments(f"{text}；{note}。")


def append_stale_next_action(candidate: dict, text: str) -> str:
    age_days = candidate_evidence_age_days(candidate)
    if age_days is None or age_days <= STALE_CANDIDATE_EVIDENCE_DAYS:
        return text
    if "最近 180 天" in text:
        return text
    return dedupe_reason_fragments(f"{text}；優先補抓最近 180 天內官方公告、法說會、月營收與公司新聞後再驗證。")


def candidate_evidence_age_days(candidate: dict) -> Optional[int]:
    raw_age = candidate.get("evidence_age_days")
    if raw_age is not None:
        try:
            return int(raw_age)
        except (TypeError, ValueError):
            pass
    latest = candidate.get("latest_evidence_date")
    if not latest:
        return None
    try:
        latest_date = date.fromisoformat(str(latest)[:10])
    except ValueError:
        return None
    return (today_taipei() - latest_date).days


def candidate_audit_reason(evidence_count: int, source_count: int, confidence_score: Optional[int] = None) -> str:
    if evidence_count >= 2 and source_count >= 2 and is_low_formal_confidence(confidence_score):
        return f"弱證據：篇數與來源數達標，但入選支持度只有 {confidence_score} 分。"
    if evidence_count >= 2 and source_count >= 2:
        return "通過候選入選門檻；正式分析可信度仍需另看風險/機會歸因、財報、估值與公司文件。"
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
    age_days = candidate_evidence_age_days(candidate)
    if age_days is not None and age_days > STALE_CANDIDATE_EVIDENCE_DAYS:
        date_text += f"（距今約 {age_days} 天，超過 180 天）"
    confidence = format_confidence_score(float(score))
    if label and not confidence.startswith(label):
        confidence = f"{label} {int(score)}"
    source_credibility = candidate.get("source_credibility_label")
    source_text = f"，來源品質 {source_credibility}" if source_credibility else ""
    return f"{confidence}{source_text}{date_text}"
