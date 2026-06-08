from __future__ import annotations

from app.services import report_decision_rules, report_formatting


def render_monitoring_checklist(contexts: list[dict], downside_gate: int) -> str:
    if not contexts:
        return "目前無可監控股票。"

    lines = [
        "這張表把觀察與避開名單轉成可執行監控規則；條件未改善前，不把觀察股升級為買進研究。",
        "",
        "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |",
        "|---|---|---|---|---|",
    ]
    for context in contexts:
        lines.append(
            report_formatting.table_row(
                [
                    context["label"],
                    context["decision"],
                    report_decision_rules.recheck_trigger_text(context, downside_gate),
                    report_decision_rules.avoid_trigger_text(context, downside_gate),
                    report_decision_rules.monitor_frequency(context),
                ]
            )
        )
    return "\n".join(lines)
