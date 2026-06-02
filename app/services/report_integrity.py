from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.source_quality import is_low_quality_investor_forum_text


@dataclass(frozen=True)
class ReportIntegrityIssue:
    code: str
    severity: str
    message: str
    evidence: str


class ReportIntegrityError(ValueError):
    def __init__(self, issues: list[ReportIntegrityIssue]) -> None:
        self.issues = issues
        message = "報告完整性檢查未通過：" + "；".join(issue.message for issue in issues)
        super().__init__(message)


COMPANY_HEADING_RE = re.compile(r"^\s*###\s+(\d{4})\s+(.+?)\s*$", re.MULTILINE)
SECTION_BOUNDARY_RE = re.compile(r"^\s*##\s+|^\s*###\s+\d{4}\s+", re.MULTILINE)
GENERIC_SECTION_BOUNDARY_RE = re.compile(r"^\s*##+\s+", re.MULTILINE)
ZERO_DEBT_RE = re.compile(r"(負債權益比[^。\n|]{0,60}0\.0+\s*倍|0\.0+\s*倍[^。\n|]{0,60}負債權益比)")
FUTURE_FULL_YEAR_RE = re.compile(r"(2022\s*至\s*2026|2022\s*-\s*2026|2026\s*全年完整)")
UNIPCB_ATTENTION_LOW_RE = re.compile(r"(3037[^。\n|]{0,120}(報導偏少|attention-low)|(報導偏少|attention-low)[^。\n|]{0,120}3037)", re.IGNORECASE)
POSITIVE_BOTTLENECK_RE = re.compile(
    r"瓶頸/限制證據：[^。\n|]{0,180}(領先廠商|助力|低能耗|高效能|實機展示|受惠)"
)
LOSS_TERMS_RE = re.compile(r"(淨利為負|接近虧損|淨利率為負|ROE\s*為負|ROE 為負)")
LOW_VALUATION_RE = re.compile(r"(目前估值略低|目前估值低於同業)")
NON_FORMAL_SOURCE_RE = re.compile(
    r"(CMoney投資網誌|股市爆料同學會|爆料同學會|PTT|Dcard|Mobile01|cmoney\.tw/forum|旺得富|鉅亨號)",
    re.IGNORECASE,
)
NANYA_TECH_RE = re.compile(r"(南亞科|南亞科技|2408)")
ALLOCATION_TOTAL_RE = re.compile(r"本輪首筆配置合計約\s*([\d,]+)\s*元")
ALLOCATION_ITEM_RE = re.compile(r"^\s*-\s+(.+?)：首筆配置約\s*([\d,]+)\s*元", re.MULTILINE)
SUMMARY_RESEARCH_COUNT_RE = re.compile(r"^\s*\|\s*可小額研究\s*\|\s*(\d+)\s*檔\s*\|", re.MULTILINE)
RESEARCH_ITEM_RE = re.compile(r"^\s*-\s+(.+?)：可列小額分批研究", re.MULTILINE)
IMMEDIATE_RESEARCH_ITEM_RE = re.compile(
    r"^\s*-\s+(.+?)：可看資金控管建議中的首筆配置",
    re.MULTILINE,
)

OWNER_PHRASES = {
    "光寶為全球次世代 AI 關鍵基礎設施中的領先廠商": "2301",
    "感謝各位股東長期以來對直得科技": "1597",
}


def audit_report_integrity(markdown: str) -> dict:
    issues = _find_integrity_issues(markdown or "")
    blockers = [issue for issue in issues if issue.severity == "blocker"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    return {
        "status": "fail" if blockers else "pass",
        "blockers": [issue.__dict__ for issue in blockers],
        "warnings": [issue.__dict__ for issue in warnings],
        "issue_count": len(issues),
    }


def assert_report_integrity(markdown: str) -> None:
    issues = _find_integrity_issues(markdown or "")
    blockers = [issue for issue in issues if issue.severity == "blocker"]
    if blockers:
        raise ReportIntegrityError(blockers)


def _find_integrity_issues(markdown: str) -> list[ReportIntegrityIssue]:
    issues: list[ReportIntegrityIssue] = []
    issues.extend(_regex_issues(markdown))
    issues.extend(_low_quality_source_issues(markdown))
    issues.extend(_non_formal_source_issues(markdown))
    issues.extend(_allocation_consistency_issues(markdown))
    issues.extend(_owner_phrase_issues(markdown))
    issues.extend(_confusing_entity_section_issues(markdown))
    issues.extend(_loss_misvaluation_issues(markdown))
    return issues


def _regex_issues(markdown: str) -> list[ReportIntegrityIssue]:
    checks = [
        (
            "suspicious_zero_debt_ratio",
            ZERO_DEBT_RE,
            "負債權益比出現 0.00 倍，需回到財務資料層確認是否為缺值或計算錯誤。",
        ),
        (
            "future_full_year_financials",
            FUTURE_FULL_YEAR_RE,
            "報告疑似把尚未完整結束的年度寫成完整年度財務結論。",
        ),
        (
            "unipcb_attention_low",
            UNIPCB_ATTENTION_LOW_RE,
            "3037 欣興不可被標成報導偏少；需檢查熱度與早期潛力分類。",
        ),
        (
            "positive_capability_as_bottleneck",
            POSITIVE_BOTTLENECK_RE,
            "正向能力描述被放入瓶頸/限制證據，需修正風險分類或證據句選取。",
        ),
    ]
    issues = []
    for code, pattern, message in checks:
        match = pattern.search(markdown)
        if match:
            issues.append(
                ReportIntegrityIssue(
                    code=code,
                    severity="blocker",
                    message=message,
                    evidence=_compact(match.group(0)),
                )
            )
    return issues


def _low_quality_source_issues(markdown: str) -> list[ReportIntegrityIssue]:
    if not is_low_quality_investor_forum_text(markdown):
        return []
    return [
        ReportIntegrityIssue(
            code="low_quality_forum_source_in_report",
            severity="blocker",
            message="正式報告不可列入股市爆料同學會、PTT、Dcard 等散戶論壇文本作為來源或附錄證據。",
            evidence=_compact(_line_containing_low_quality_source(markdown)),
        )
    ]


def _non_formal_source_issues(markdown: str) -> list[ReportIntegrityIssue]:
    match = NON_FORMAL_SOURCE_RE.search(markdown)
    if not match:
        return []
    return [
        ReportIntegrityIssue(
            code="non_formal_source_in_report",
            severity="blocker",
            message="正式報告不可把投資網誌、社群或散戶論壇來源列為投資理由或代表來源。",
            evidence=_compact(_line_containing_pattern(markdown, NON_FORMAL_SOURCE_RE)),
        )
    ]


def _allocation_consistency_issues(markdown: str) -> list[ReportIntegrityIssue]:
    issues: list[ReportIntegrityIssue] = []
    allocation_section = _named_section(markdown, "首筆配置草案")
    if not allocation_section:
        return issues

    total_match = ALLOCATION_TOTAL_RE.search(allocation_section)
    allocation_rows = [
        (match.group(1).strip(), _parse_amount(match.group(2)))
        for match in ALLOCATION_ITEM_RE.finditer(allocation_section)
    ]
    if total_match and allocation_rows:
        declared_total = _parse_amount(total_match.group(1))
        row_total = sum(amount for _label, amount in allocation_rows)
        if declared_total != row_total:
            issues.append(
                ReportIntegrityIssue(
                    code="allocation_total_mismatch",
                    severity="blocker",
                    message="首筆配置草案的合計金額與逐檔配置明細加總不一致。",
                    evidence=f"宣告 {declared_total:,} 元；明細加總 {row_total:,} 元",
                )
            )

    allocation_labels = {label for label, _amount in allocation_rows}
    summary_research_count = _summary_research_count(markdown)
    if summary_research_count is not None and summary_research_count != len(allocation_rows):
        issues.append(
            ReportIntegrityIssue(
                code="allocation_count_mismatch",
                severity="blocker",
                message="一頁摘要的可小額研究檔數與首筆配置明細檔數不一致。",
                evidence=f"摘要 {summary_research_count} 檔；配置明細 {len(allocation_rows)} 檔",
            )
        )
    research_labels = set(_section_labels(markdown, "可小額分批研究", RESEARCH_ITEM_RE))
    immediate_labels = set(_section_labels(markdown, "可立即研究", IMMEDIATE_RESEARCH_ITEM_RE))
    expected_labels = research_labels | immediate_labels
    if expected_labels:
        missing = sorted(expected_labels - allocation_labels)
        extra = sorted(allocation_labels - expected_labels)
        if missing:
            issues.append(
                ReportIntegrityIssue(
                    code="allocation_missing_research_candidate",
                    severity="blocker",
                    message="可立即研究或可小額分批研究名單中的股票沒有出現在首筆配置草案。",
                    evidence="缺少：" + "、".join(missing[:8]),
                )
            )
        if extra:
            issues.append(
                ReportIntegrityIssue(
                    code="allocation_extra_candidate",
                    severity="blocker",
                    message="首筆配置草案列入了未出現在可研究名單中的股票。",
                    evidence="多出：" + "、".join(extra[:8]),
                )
            )
    return issues


def _owner_phrase_issues(markdown: str) -> list[ReportIntegrityIssue]:
    issues = []
    current_ticker = ""
    for line in markdown.splitlines():
        heading = COMPANY_HEADING_RE.match(line)
        if heading:
            current_ticker = heading.group(1)
        for phrase, owner_ticker in OWNER_PHRASES.items():
            if phrase not in line:
                continue
            if current_ticker == owner_ticker or owner_ticker in line:
                continue
            issues.append(
                ReportIntegrityIssue(
                    code="company_text_owner_mismatch",
                    severity="blocker",
                    message=f"公司專屬文本疑似被放到非 {owner_ticker} 公司段落。",
                    evidence=_compact(line),
                )
            )
    return issues


def _confusing_entity_section_issues(markdown: str) -> list[ReportIntegrityIssue]:
    issues = []
    for ticker, name, body in _company_sections(markdown):
        if ticker == "1303" and NANYA_TECH_RE.search(body):
            issues.append(
                ReportIntegrityIssue(
                    code="confusing_entity_in_company_section",
                    severity="blocker",
                    message=f"{ticker} {name} 段落疑似混入南亞科/2408 的來源或敘述。",
                    evidence=_compact(NANYA_TECH_RE.search(body).group(0)),
                )
            )
    return issues


def _loss_misvaluation_issues(markdown: str) -> list[ReportIntegrityIssue]:
    issues = []
    for ticker, _name, body in _company_sections(markdown):
        if ticker != "4540":
            continue
        if LOSS_TERMS_RE.search(body) and LOW_VALUATION_RE.search(body):
            issues.append(
                ReportIntegrityIssue(
                    code="loss_making_company_marked_low_valuation",
                    severity="blocker",
                    message="4540 盟立若獲利為負，不可直接標為目前估值略低或低於同業。",
                    evidence=_compact(LOW_VALUATION_RE.search(body).group(0)),
                )
            )
    return issues


def _company_sections(markdown: str) -> list[tuple[str, str, str]]:
    matches = list(COMPANY_HEADING_RE.finditer(markdown))
    sections = []
    for match in matches:
        start = match.end()
        next_boundary = SECTION_BOUNDARY_RE.search(markdown, start)
        end = next_boundary.start() if next_boundary else len(markdown)
        sections.append((match.group(1), match.group(2).strip(), markdown[start:end]))
    return sections


def _named_section(markdown: str, title: str) -> str:
    pattern = re.compile(rf"^\s*###\s+{re.escape(title)}\s*$", re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        return ""
    next_boundary = GENERIC_SECTION_BOUNDARY_RE.search(markdown, match.end())
    end = next_boundary.start() if next_boundary else len(markdown)
    return markdown[match.end() : end]


def _section_labels(markdown: str, title: str, pattern: re.Pattern[str]) -> list[str]:
    section = _named_section(markdown, title)
    return [match.group(1).strip() for match in pattern.finditer(section)]


def _parse_amount(value: str) -> int:
    return int(str(value).replace(",", "").strip() or 0)


def _summary_research_count(markdown: str) -> int | None:
    match = SUMMARY_RESEARCH_COUNT_RE.search(markdown)
    if not match:
        return None
    return int(match.group(1))


def _line_containing_low_quality_source(markdown: str) -> str:
    for line in markdown.splitlines():
        if is_low_quality_investor_forum_text(line):
            return line
    return markdown


def _line_containing_pattern(markdown: str, pattern: re.Pattern[str]) -> str:
    for line in markdown.splitlines():
        if pattern.search(line):
            return line
    return markdown


def _compact(text: str) -> str:
    return " ".join(str(text).split())[:240]
