from __future__ import annotations

from app.core.time import now_taipei
from app.models.schemas import MarketSnapshot, MonthlyRevenue, ReportRequest, ValuationMetric
from app.services import report_allocation


def render_time_scope_note(
    request: ReportRequest,
    market_snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue] | None = None,
    valuation_metrics: list[ValuationMetric] | None = None,
) -> str:
    latest_market = max((snapshot.trade_date for snapshot in market_snapshots), default=None)
    latest_revenue = max((revenue.revenue_date for revenue in monthly_revenues or []), default=None)
    latest_valuation = max((valuation.trade_date for valuation in valuation_metrics or []), default=None)
    market_text = latest_market.isoformat() if latest_market else "尚無股價日期"
    revenue_text = latest_revenue.isoformat() if latest_revenue else "尚無月營收日期"
    valuation_text = latest_valuation.isoformat() if latest_valuation else "尚無估值日期"
    generated_text = now_taipei().isoformat(timespec="seconds")
    return "\n".join(
        [
            f"- 「目前」指本報告生成時間（台灣）{generated_text} 前已取得並通過資料品質檢查的內容，不代表未來一定維持。",
            f"- 「近 {request.lookback_days} 天來源」指新聞/RAG 來源回看區間；公司公開文件、已揭露年度財報與估值仍以各自原始日期判讀。",
            f"- 「目前估值」只比較最新估值日 {valuation_text} 的 P/E、P/B、殖利率與本次同業樣本，不是未來估值預測。",
            "- 「追價風險標籤」會納入最新可取得收盤價、近 20/60 日股價動能、量能、目前相對估值與目前情境降值分；它是追價風險提示，不是即時報價或買賣指令。",
            "- 「目前情境升值分／目前情境降值分」是依目前證據計算的排序分數，不是預期報酬率、目標價或保證幅度。",
            f"- 「近況訊號」使用最新股價日 {market_text}、月營收日 {revenue_text} 與估值日 {valuation_text} 的近 20/60 日或月資料，是追蹤警示，不是未來走勢預測。",
        ]
    )


def render_decision_criteria_note(request: ReportRequest) -> str:
    downside_gate = report_allocation.downside_gate(request)
    return "\n".join(
        [
            f"- 本次投資人設定為「{report_allocation.profile_label(request)}」；目前情境降值分超過 {downside_gate} 分時，原則上先列觀察。",
            "- 「可小額分批研究」必須同時符合：資料等級完整、目前情境升值分高於 10 分、目前情境降值分未超過投資人門檻、近況訊號不偏空，且沒有結構性瓶頸、短期波動或財務/估值紅旗。",
            "- 「觀察 / 等風險降低」代表題材與資料可以追蹤，但存在結構性瓶頸或尚未解除的財務/估值疑慮，不列入本次配置。",
            "- 「避開 / 降低曝險」代表目前情境降值分已高於升值分，或財務/估值紅旗偏重；單純超過投資人門檻會先列觀察，不會一票否決。",
            "- 「追價風險標籤」若顯示不適合追價、等止跌、等回檔或等風險下降，代表現在不應只因題材熱度就投入。",
            "- 財務/估值檢查會納入已揭露年度營收、淨利、負債權益比、ROE/淨利率與目前相對估值；若財務紅旗存在，題材分數不能單獨升級成可研究標的。",
        ]
    )
