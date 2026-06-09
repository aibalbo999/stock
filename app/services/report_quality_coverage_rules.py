from __future__ import annotations


def coverage_quality_notes(
    *,
    promoted_count: int,
    leading_signal_coverage: float | None,
    company_filing_coverage: float | None,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    observations: list[str] = []
    if promoted_count and leading_signal_coverage is not None:
        if leading_signal_coverage < 0.5:
            warnings.append("近況訊號覆蓋偏低，目前情境升值/降值排序信心需下修")
        elif leading_signal_coverage < 1:
            observations.append("部分股票近況訊號不足，系統已降低排序信心")
    if promoted_count and company_filing_coverage is not None:
        if company_filing_coverage < 0.5:
            warnings.append("公司公開文件覆蓋率低於 50%，正式投入前需補年報或法說會")
        elif company_filing_coverage < 1:
            warnings.append("部分股票缺少高品質公司公開文件")
    return warnings, observations


__all__ = ["coverage_quality_notes"]
