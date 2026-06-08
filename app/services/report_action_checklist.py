from __future__ import annotations

from app.services import report_decision_rules


def render_action_checklist(contexts: list[dict], downside_gate: int) -> str:
    if not contexts:
        return "1. 先補足新聞與市場資料，再重新執行分析。"

    research = [item for item in contexts if item["decision"] == "可小額分批研究"]
    watch = [
        item
        for item in contexts
        if item["decision"] not in {"可小額分批研究", "避開 / 降低曝險"}
    ]
    avoid = [item for item in contexts if item["decision"] == "避開 / 降低曝險"]

    lines = [
        "1. 先處理資料缺口：若有「缺主題歸因、缺月營收、缺股價、缺公司公開文件」，先補資料再考慮加碼。",
        "2. 只把資料完整且通過目前情境降值門檻的股票放進小額研究清單。",
        "3. 對目前情境降值分高於門檻或近況訊號偏空的股票，先等風險下降或新資料確認。",
        "",
        "### 可立即研究",
    ]
    if research:
        for item in research:
            lines.append(
                f"- {item['label']}：可看資金控管建議中的首筆配置；"
                f"目前情境升值分 {item['estimate']['upside_pct']} 分，"
                f"目前情境降值分 {item['estimate']['downside_pct']} 分。"
            )
    else:
        lines.append("- 目前沒有同時通過資料完整度與風險門檻的標的。")

    lines.extend(["", "### 待補資料 / 觀察"])
    if watch:
        for item in watch:
            missing = "、".join(item["quality"]["missing"]) if item["quality"]["missing"] else "等待新證據"
            lines.append(
                f"- {item['label']}：{item['decision']}；下一步補查 {missing}。"
                f"重新評估條件：{report_decision_rules.recheck_trigger_text(item, downside_gate)}"
            )
    else:
        lines.append("- 目前沒有待補資料名單。")

    lines.extend(["", "### 先避開"])
    if avoid:
        for item in avoid:
            lines.append(
                f"- {item['label']}：目前情境降值分 {item['estimate']['downside_pct']} 分，"
                f"暫不列入買進研究。重新評估條件：{report_decision_rules.recheck_trigger_text(item, downside_gate)}"
            )
    else:
        lines.append("- 目前沒有明確避開名單。")
    return "\n".join(lines)
