from __future__ import annotations

from app.services import report_decision_rules


def source_label(context: dict) -> str:
    ticker = context["ticker"]
    snapshot = context.get("snapshot")
    revenue = context.get("revenue")
    source = (
        f"{snapshot.trade_date.isoformat()} {snapshot.source} {ticker}"
        if snapshot
        else "目前無足夠數據判斷"
    )
    if revenue:
        source += f"；{revenue.revenue_date.isoformat()} {revenue.source} {ticker}"
    return source


def render_final_potential_screen(contexts: list[dict]) -> str:
    if not contexts:
        return "目前無足夠數據判斷。"

    upside_rows = []
    watch_upside_rows = []
    blocked_upside_rows = []
    downside_rows = []
    insufficient_rows = []

    for context in contexts:
        estimate = context["estimate"]
        quality = context["quality"]
        decision = context["decision"]
        label = context["label"]
        source = source_label(context)

        if estimate["upside_pct"] > 10:
            if decision == "避開 / 降低曝險":
                blocked_upside_rows.append(
                    f"- {label}：升值分約 {estimate['upside_pct']} 分，但最終判斷為「{decision}」；"
                    f"主要原因：{report_decision_rules.risk_warning_reason(estimate)}來源：{source}。"
                )
            elif quality["grade"] != "supported":
                insufficient_rows.append(
                    f"- {label}：目前證據的情境升值分約 {estimate['upside_pct']} 分，但資料品質不足；"
                    f"{'；'.join(quality['missing'])}。"
                )
            elif decision == "可小額分批研究":
                upside_rows.append(
                    f"- {label}：目前證據的情境升值分約 {estimate['upside_pct']} 分。"
                    f"理由：{estimate['upside_reason']} 來源：{source}。"
                )
            else:
                watch_upside_rows.append(
                    f"- {label}：升值分約 {estimate['upside_pct']} 分，但最終判斷為「{decision}」；"
                    "需等降值分、近況訊號或風險證據改善後再研究配置。"
                )
        if estimate["downside_pct"] > 5:
            downside_rows.append(
                f"- {label}：目前證據的情境降值分約 {estimate['downside_pct']} 分。"
                f"理由：{estimate['downside_reason']} 來源：{source}。"
            )
        if estimate["upside_pct"] <= 10 and estimate["downside_pct"] <= 5:
            insufficient_rows.append(f"- {label}：未達目前情境升值/降值門檻或資料不足。")

    lines = [
        "本段為非個人化情境篩選；分數是依新聞、財務、估值與市場資料的研究分級，不是保證報酬或停損幅度。最終是否可研究以「判斷」為準，不只看升值分。",
        "",
        "### 升值分較高且通過風險門檻",
    ]
    lines.extend(upside_rows or ["目前無足夠數據判斷。"])
    if watch_upside_rows:
        lines.extend(["", "### 升值分高但仍需觀察", *watch_upside_rows])
    if blocked_upside_rows:
        lines.extend(["", "### 升值分高但風險壓過", *blocked_upside_rows])
    lines.extend(["", "### 目前情境降值分較高（目前證據 >5）"])
    lines.extend(downside_rows or ["目前無足夠數據判斷。"])
    if insufficient_rows:
        lines.extend(["", "### 未通過研究門檻 / 資料不足", *insufficient_rows])
    return "\n".join(lines)
