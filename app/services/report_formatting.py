from __future__ import annotations


def compact_text(value: object, max_chars: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def table_cell(value: object) -> str:
    return " ".join(str(value or "").split()).replace("|", "\\|")


def table_row(cells: list[object]) -> str:
    return "| " + " | ".join(table_cell(cell) for cell in cells) + " |"
