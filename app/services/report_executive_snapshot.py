from __future__ import annotations

from app.models.schemas import ReportRequest
from app.services import report_allocation, report_formatting, report_potential


def is_low_attention_topic(topic: str) -> bool:
    normalized = str(topic or "").lower()
    return any(term in normalized for term in ["低關注", "冷門", "未被市場", "low attention"])


def decision_counts(contexts: list[dict]) -> dict[str, int]:
    counts = {"actionable": 0, "watch": 0, "avoid": 0, "weak": 0}
    for context in contexts:
        decision = context["decision"]
        quality = context["quality"]
        if decision == "可小額分批研究":
            counts["actionable"] += 1
        elif decision == "避開 / 降低曝險":
            counts["avoid"] += 1
        elif quality["grade"] == "weak":
            counts["weak"] += 1
        else:
            counts["watch"] += 1
    return counts


def headline_for_counts(counts: dict[str, int]) -> str:
    if counts["actionable"]:
        return f"本次有 {counts['actionable']} 檔可小額研究；仍需依資金控管分批，不建議一次買滿。"
    if counts["avoid"]:
        return "本次沒有可小額研究標的，且有股票進入避開/降低曝險名單。"
    return "本次沒有可小額研究標的；先補資料或等待新證據。"


def overview_row(context: dict) -> str:
    quality = context["quality"]
    estimate = context["estimate"]
    signal = context.get("leading_signal")
    return report_formatting.table_row(
        [
            context["label"],
            context["decision"],
            context["current_price"],
            context["current_price_label"],
            report_potential.quality_label(quality["grade"]),
            f"{estimate['upside_pct']} 分",
            f"{estimate['downside_pct']} 分",
            signal.direction if signal else "未評估",
            "、".join(quality["missing"]) if quality["missing"] else "完整",
        ]
    )


def render_executive_snapshot(
    contexts: list[dict],
    request: ReportRequest,
    reading_sort_note: str,
) -> str:
    if not contexts:
        return "本次沒有形成可驗證個股清單；先補資料，不建議依此報告做個股配置。"

    rows = [overview_row(context) for context in contexts]
    counts = decision_counts(contexts)
    deployable = request.investor_capital - int(request.investor_capital * request.cash_reserve_pct)
    lines = [
        f"**重點提醒：{headline_for_counts(counts)}**",
        "",
        "| 項目 | 結果 |",
        "|---|---|",
        f"| 投資人設定 | {report_allocation.profile_label(request)}；總資金 {request.investor_capital:,} 元；"
        f"品質門檻最多允許研究約 {deployable:,} 元，但本次實際配置以投資建議與資金控管為準 |",
        f"| 本次股票範圍 | {len(contexts)} 檔 |",
        f"| 可小額研究 | {counts['actionable']} 檔 |",
        f"| 觀察/待補 | {counts['watch'] + counts['weak']} 檔 |",
        f"| 避開/降低曝險 | {counts['avoid']} 檔 |",
    ]
    if is_low_attention_topic(request.topic):
        lines.append(
            "| 低關注核對 | 可小額研究不等於低關注；是否真的屬於報導較少標的，請以「早期潛力雷達」為準 |"
        )
    lines.extend(
        [
            "",
            "### 決策總覽",
            reading_sort_note,
            "",
            "| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 資料等級 | 目前情境升值分 | 目前情境降值分 | 近況訊號 | 主要缺口 |",
            "|---|---|---|---|---|---:|---:|---|---|",
            *rows,
            "",
            "閱讀方式：先看「判斷」與「主要缺口」；升值/降值欄位是目前情境分數，不是未來報酬率。",
        ]
    )
    return "\n".join(lines)
