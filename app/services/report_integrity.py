from __future__ import annotations

import re
from dataclasses import dataclass


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
ZERO_DEBT_RE = re.compile(r"(負債權益比[^。\n|]{0,60}0\.0+\s*倍|0\.0+\s*倍[^。\n|]{0,60}負債權益比)")
FUTURE_FULL_YEAR_RE = re.compile(r"(2022\s*至\s*2026|2022\s*-\s*2026|2026\s*全年完整)")
UNIPCB_ATTENTION_LOW_RE = re.compile(r"(3037[^。\n|]{0,120}(報導偏少|attention-low)|(報導偏少|attention-low)[^。\n|]{0,120}3037)", re.IGNORECASE)
POSITIVE_BOTTLENECK_RE = re.compile(
    r"瓶頸/限制證據：[^。\n|]{0,180}(領先廠商|助力|低能耗|高效能|實機展示|受惠)"
)
LOSS_TERMS_RE = re.compile(r"(淨利為負|接近虧損|淨利率為負|ROE\s*為負|ROE 為負)")
LOW_VALUATION_RE = re.compile(r"(目前估值略低|目前估值低於同業)")

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
    issues.extend(_owner_phrase_issues(markdown))
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


def _compact(text: str) -> str:
    return " ".join(str(text).split())[:240]
