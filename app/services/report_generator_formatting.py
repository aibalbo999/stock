from __future__ import annotations

from app.services import report_formatting


class ReportGeneratorFormattingMixin:
    @staticmethod
    def _compact_text(value: object, max_chars: int = 80) -> str:
        return report_formatting.compact_text(value, max_chars=max_chars)

    @staticmethod
    def _table_cell(value: object) -> str:
        return report_formatting.table_cell(value)

    @staticmethod
    def _table_row(cells: list[object]) -> str:
        return report_formatting.table_row(cells)
