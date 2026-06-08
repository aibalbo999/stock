from __future__ import annotations

from app.models.schemas import MarketSnapshot
from app.services.leading_signals import LeadingSignal


def sort_decision_contexts(contexts: list[dict]) -> list[dict]:
    return sorted(contexts, key=decision_sort_key)


def decision_sort_key(context: dict) -> tuple:
    estimate = context.get("estimate") or {}
    return (
        decision_rank(context.get("decision")),
        -context_current_price(context),
        -float(estimate.get("upside_pct") or 0),
        float(estimate.get("downside_pct") or 0),
        str(context.get("ticker") or ""),
    )


def decision_rank(decision: str | None) -> int:
    ranks = {
        "可小額分批研究": 0,
        "觀察 / 等風險降低": 1,
        "觀察": 2,
        "觀察 / 資料待補": 3,
        "觀察 / 資料不足": 4,
        "資料不足": 5,
        "避開 / 降低曝險": 6,
    }
    return ranks.get(decision or "", 99)


def context_current_price(context: dict) -> float:
    snapshot = context.get("snapshot")
    close = getattr(snapshot, "close", None)
    if close is None:
        return -1.0
    try:
        return float(close)
    except (TypeError, ValueError):
        return -1.0


def recheck_trigger_text(context: dict, downside_gate: int | None = None) -> str:
    estimate = context.get("estimate") or {}
    quality = context.get("quality") or {}
    signal: LeadingSignal | None = context.get("leading_signal")
    gate = int(downside_gate or context.get("downside_gate") or 5)
    triggers = []
    if quality.get("missing"):
        triggers.append("補齊" + "、".join(quality["missing"][:3]))
    if signal and signal.direction == "偏空":
        triggers.append("近況訊號由偏空轉為中性以上")
    elif signal and signal.direction == "中性":
        triggers.append("近況訊號轉偏多且量價/營收同步改善")
    elif not signal or not signal.has_signal_data:
        triggers.append("補齊股價歷史、月營收或估值後重算近況訊號")
    if estimate.get("downside_pct", 0) > gate:
        triggers.append(f"目前情境降值分降至 {gate} 分以下")
    if estimate.get("upside_pct", 0) <= 10:
        triggers.append("目前情境升值分重新站上 10 分")
    return "；".join(triggers[:4]) if triggers else "等待新來源確認投資假設延續"


def avoid_trigger_text(context: dict, downside_gate: int | None = None) -> str:
    estimate = context.get("estimate") or {}
    signal: LeadingSignal | None = context.get("leading_signal")
    gate = int(downside_gate or context.get("downside_gate") or 5)
    triggers = []
    if estimate.get("downside_pct", 0) > gate:
        triggers.append(f"目前情境降值分仍高於 {gate} 分")
    if signal and signal.direction == "偏空":
        triggers.append("近況訊號維持偏空")
    if estimate.get("upside_pct", 0) <= 10:
        triggers.append("目前情境升值分低於 10 分")
    return "；".join(triggers[:3]) if triggers else "若新資料未改善，維持觀察"


def monitor_frequency(context: dict) -> str:
    decision = context.get("decision")
    estimate = context.get("estimate") or {}
    signal: LeadingSignal | None = context.get("leading_signal")
    if decision == "避開 / 降低曝險":
        return "每週"
    if signal and signal.direction == "偏空":
        return "每週"
    if estimate.get("downside_pct", 0) > 5:
        return "每週"
    if decision == "可小額分批研究":
        return "每週"
    return "每月"


def current_price_text(snapshot: MarketSnapshot | None) -> str:
    if not snapshot or snapshot.close is None:
        return "缺股價"
    return f"{snapshot.trade_date.isoformat()} 收盤 {snapshot.close:g}"


def current_price_label(
    snapshot: MarketSnapshot | None,
    estimate: dict,
    quality: dict,
    valuation_label: str,
    leading_signal: LeadingSignal | None,
    decision: str,
    downside_gate: int,
) -> str:
    if not snapshot or snapshot.close is None or "缺股價" in quality.get("missing", []):
        return "股價資料不足"
    downside = int(estimate.get("downside_pct") or 0)
    upside = int(estimate.get("upside_pct") or 0)
    if decision == "避開 / 降低曝險" or downside > upside:
        return "不適合追價"
    if leading_signal and leading_signal.direction == "偏空":
        return "等止跌"
    if downside > downside_gate:
        return "等風險下降"

    price_hot = False
    if leading_signal:
        price_hot = any(
            [
                leading_signal.price_20d_pct is not None and leading_signal.price_20d_pct >= 8,
                leading_signal.price_60d_pct is not None and leading_signal.price_60d_pct >= 15,
                leading_signal.volume_ratio_20d is not None
                and leading_signal.volume_ratio_20d >= 1.5
                and leading_signal.price_20d_pct is not None
                and leading_signal.price_20d_pct > 0,
            ]
        )
    valuation_hot = "偏高" in valuation_label or "略高" in valuation_label
    if decision == "可小額分批研究" and not valuation_hot and not price_hot:
        return "可小額分批"
    if decision == "可小額分批研究":
        return "可研究但勿追高"
    if valuation_hot or price_hot:
        return "等回檔/降溫"
    return "觀察等待"


def risk_warning_reason(estimate: dict) -> str:
    financial = estimate.get("financial_assessment") or {}
    if financial.get("red_flag") and int(financial.get("risk_score") or 0) >= 5:
        return "財務/估值紅旗偏重：" + financial.get("risk_summary", "需先覆核基本面風險") + "。"
    if estimate["downside_pct"] > estimate["upside_pct"]:
        return "目前情境降值分高於升值分，風險權重已壓過投資理由，不適合追價。"
    return "財務或估值紅旗偏重，需先等基本面修復或補充來源驗證。"
