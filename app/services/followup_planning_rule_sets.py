from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricActionRule:
    metric_key: str
    action_type: str
    reason: str
    priority: str
    frequency: str


@dataclass(frozen=True)
class KeywordActionRule:
    action_type: str
    keywords: tuple[str, ...]
    reason: str | None
    priority: str
    frequency: str
    purpose: str
    topic_level_keywords: tuple[str, ...] = ()


QUALITY_METRIC_RULES = (
    MetricActionRule("market_stale_count", "refresh_market", "快取救援資料：刷新股價歷史、成交量與近況訊號。", "high", "weekly"),
    MetricActionRule("monthly_revenue_stale_count", "refresh_monthly_revenue", "快取救援資料：刷新月營收與成長加速資料。", "high", "monthly"),
    MetricActionRule("financial_metrics_stale_ticker_count", "refresh_financial_metrics", "快取救援資料：刷新近五年財務資料。", "high", "monthly"),
    MetricActionRule("valuation_stale_count", "refresh_valuations", "快取救援資料：刷新估值與同業比較資料。", "high", "weekly"),
)

QUALITY_TEXT_RULES = (
    KeywordActionRule(
        "refresh_market",
        ("股價", "成交量", "領先訊號", "近況訊號"),
        "補齊股價歷史、成交量與近況訊號。",
        "high",
        "weekly",
        "required",
    ),
    KeywordActionRule(
        "refresh_monthly_revenue",
        ("月營收", "營收"),
        "補齊月營收與成長加速資料。",
        "high",
        "monthly",
        "required",
    ),
    KeywordActionRule(
        "refresh_financial_metrics",
        ("五年財務", "財務指標", "財務資料"),
        "補齊近五年財務資料。",
        "medium",
        "monthly",
        "required",
    ),
    KeywordActionRule(
        "refresh_valuations",
        ("估值", "P/E", "DCF", "同業"),
        "補齊估值與同業比較資料。",
        "medium",
        "weekly",
        "required",
    ),
    KeywordActionRule(
        "ingest_news",
        ("資料來源", "來源", "新聞", "國際", "發布者", "時間戳", "近期資料"),
        "補抓近期與國際資料源，提高 RAG 證據覆蓋。",
        "high",
        "weekly",
        "required",
        topic_level_keywords=("主題拆解子題", "來源覆蓋子題"),
    ),
    KeywordActionRule(
        "rerun_discovery",
        ("AI 拆解任務", "候選公司", "證據驗證", "正式分析股票"),
        "重新執行 AI 主題拆解與候選白名單驗證。",
        "high",
        "once",
        "required",
    ),
    KeywordActionRule(
        "rerun_analysis",
        ("LLM 補充分析", "模型恢復"),
        "LLM 供應商或 API key 恢復後，重新產生報告並保留來源核查。",
        "high",
        "once",
        "required",
    ),
)

COMPANY_DATA_AUDIT_RULES = (
    KeywordActionRule("refresh_market", ("股價", "成交量"), None, "high", "once", "required"),
    KeywordActionRule("refresh_monthly_revenue", ("月營收",), None, "high", "once", "required"),
    KeywordActionRule("refresh_financial_metrics", ("五年財報", "核心財報", "財報"), None, "medium", "once", "required"),
    KeywordActionRule("refresh_valuations", ("估值",), None, "medium", "once", "required"),
    KeywordActionRule("ingest_company_filings", ("公司原始公開文件", "公開文件"), None, "high", "monthly", "required"),
    KeywordActionRule("ingest_news", ("公司文本", "公司層級文本", "文本證據", "AI 歸因", "入庫"), None, "high", "weekly", "required"),
)

MONITORING_TRIGGER_RULES = (
    KeywordActionRule("refresh_market", ("股價歷史", "股價", "成交量", "領先訊號", "近況訊號"), None, "high", "weekly", "tracking"),
    KeywordActionRule("refresh_monthly_revenue", ("月營收", "營收"), None, "high", "monthly", "tracking"),
    KeywordActionRule("refresh_valuations", ("估值", "同業", "P/E", "DCF"), None, "medium", "weekly", "tracking"),
    KeywordActionRule("refresh_financial_metrics", ("五年財報", "財報", "財務"), None, "medium", "monthly", "tracking"),
    KeywordActionRule("ingest_news", ("新來源", "公司文本", "AI 歸因", "證據", "來源"), None, "medium", "weekly", "tracking"),
)
