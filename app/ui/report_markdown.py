from __future__ import annotations

import re
from typing import Optional


def markdown_section(markdown: str, heading: str) -> str:
    marker = f"## {heading}"
    start = markdown.find(marker)
    if start == -1:
        return "目前無足夠數據判斷。"
    next_heading = markdown.find("\n## ", start + len(marker))
    return markdown[start:next_heading].strip() if next_heading != -1 else markdown[start:].strip()


def markdown_section_or_none(markdown: str, heading: str) -> Optional[str]:
    section = markdown_section(markdown, heading)
    return None if section == "目前無足夠數據判斷。" else section


def markdown_items(markdown: str, heading: str, limit: int = 5) -> list[str]:
    section = markdown_section_or_none(markdown, heading)
    if not section:
        return []
    rows = []
    for raw_line in section.splitlines()[1:]:
        line = raw_line.strip()
        if not line or line.startswith("|---"):
            continue
        if line.startswith("|"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        elif re.match(r"^\d+\.\s+", line):
            line = re.sub(r"^\d+\.\s+", "", line).strip()
        line = line.replace("**", "").replace("###", "").replace("##", "").strip()
        if line:
            rows.append(line)
        if len(rows) >= limit:
            break
    return rows


def markdown_table_rows(markdown: str, heading: str, limit: int = 6) -> list[list[str]]:
    section = markdown_section_or_none(markdown, heading)
    if not section:
        return []
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"股票", "項目", "任務"}:
            continue
        rows.append(cells)
        if len(rows) >= limit:
            break
    return rows


def summary_table_items(markdown: str) -> list[str]:
    rows = markdown_table_rows(markdown, "一頁摘要", limit=10)
    important = {"可小額研究", "觀察/待補", "避開/降低曝險", "本次股票範圍"}
    return [f"{row[0]}：{row[1]}" for row in rows if len(row) >= 2 and row[0] in important]


def first_tranche_allocation_label(markdown: str) -> Optional[str]:
    section = markdown_section_or_none(markdown, "資金控管建議")
    if not section or "目前無可配置標的" in section:
        return "0 元"
    match = re.search(r"本輪首筆配置合計約\s*([\d,]+)\s*元", section)
    if not match:
        return None
    return f"{match.group(1)} 元"


def markdown_table_rows_by_header(
    markdown: str,
    heading: str,
    required_first_header: str,
    limit: int = 20,
) -> list[list[str]]:
    section = markdown_section_or_none(markdown, heading)
    if not section:
        return []
    rows = []
    in_target_table = False
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if in_target_table and rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        if cells[0] == required_first_header:
            in_target_table = True
            continue
        if in_target_table:
            if "---" in line:
                continue
            rows.append(cells)
            if len(rows) >= limit:
                break
    return rows
