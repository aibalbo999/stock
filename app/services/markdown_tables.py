from __future__ import annotations


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
