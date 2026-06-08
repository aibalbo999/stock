from __future__ import annotations

__all__ = [
    "quality_remediation_actions",
    "should_recover_market_data_quality",
]


def should_recover_market_data_quality(quality_gate: dict | None) -> bool:
    if not isinstance(quality_gate, dict):
        return False
    metrics = quality_gate.get("metrics") or {}
    issue_text = "；".join(
        [
            *[str(item) for item in quality_gate.get("blockers") or []],
            *[str(item) for item in quality_gate.get("warnings") or []],
            *[str(item) for item in quality_gate.get("remediation_actions") or []],
        ]
    )
    market_coverage = metrics.get("market_coverage")
    market_latest_trade_date_coverage = metrics.get("market_latest_trade_date_coverage")
    market_trade_date_warning_suppressed = bool(metrics.get("market_trade_date_warning_suppressed"))
    return bool(
        (market_coverage is not None and float(market_coverage or 0) < 1)
        or int(metrics.get("market_stale_count") or 0)
        or int(metrics.get("market_latest_only_count") or 0)
        or (
            not market_trade_date_warning_suppressed
            and int(metrics.get("market_older_than_database_latest_count") or 0)
        )
        or (
            not market_trade_date_warning_suppressed
            and market_latest_trade_date_coverage is not None
            and float(market_latest_trade_date_coverage or 0) < 0.8
        )
        or any(
            term in issue_text
            for term in ["股價資料覆蓋率", "股價日期不一致", "資料庫最新交易日股價"]
        )
    )


def quality_remediation_actions(blockers: list[str], warnings: list[str]) -> list[str]:
    issue_text = "；".join([*blockers, *warnings])
    actions = []
    rules = [
        (
            ("沒有通過證據驗證",),
            "重新執行主題拆解，要求 AI 補查公司與主題的直接證據後再產生正式股票。",
        ),
        (
            ("候選公司證據覆蓋率低於 25%", "候選公司證據覆蓋率低於 60%"),
            "保留已升格的正式股票，對弱證據候選補抓公司新聞、法說會與供應鏈資料後再做二次篩選。",
        ),
        (
            ("低信心證據公司",),
            "對低信心正式股票補抓近期、有日期且不同發布者的公司來源，未補齊前不得產生買入建議。",
        ),
        (
            ("AI 動態資料來源入庫篇數過少", "AI 動態資料來源偏少"),
            "增加查詢子題、拉長回溯天數或開啟深度分析，至少補足 12 篇以上可追溯來源。",
        ),
        (
            ("來源時間戳覆蓋率", "缺少發布日期"),
            "優先改用有發布日期的來源，無日期資料只作背景參考，不納入關鍵風險或估值推論。",
        ),
        (
            ("資料來源發布者過於單一", "資料來源多樣性偏低"),
            "補入不同發布者與國際資料源，避免單一媒體或單一市場觀點主導結論。",
        ),
        (
            ("高可信來源比例偏低", "投資網誌或社群型來源比例偏高"),
            "優先補官方公告、交易所資料、法說會與主流財經新聞；投資網誌僅作輔助訊號，不可作為配置理由。",
        ),
        (
            ("來源比例偏低", "近期資料比例偏低"),
            "補抓最近期間資料，確認產能、訂單、法規與目前估值假設仍然有效。",
        ),
        (
            ("AI 拆解任務品質",),
            "請 AI 重新拆解分析任務，補齊缺漏的產業子題、風險瓶頸、估值與個股研究任務。",
        ),
        (
            ("完全缺少相關來源", "來源或資料意圖不足"),
            "針對缺來源或弱來源子題自動補抓資料；補足後重新驗證子題覆蓋，再重跑分析。",
        ),
        (
            ("股價資料覆蓋率", "股價日期不一致", "資料庫最新交易日股價"),
            "刷新股價與市值資料，缺資料股票不得產生買入或加碼建議。",
        ),
        (
            ("月營收資料覆蓋",),
            "補齊月營收資料，並把缺資料股票的成長判斷降為低信心。",
        ),
        (
            ("五年財務資料不足",),
            "補齊近五年財務指標，未補齊前不得給出高信心財務體質結論。",
        ),
        (
            ("估值資料覆蓋",),
            "補齊同業估值、P/E 與 DCF 假設，估值缺口未補齊前只保留觀察結論。",
        ),
        (
            ("快取救援",),
            "重新刷新股價、月營收、五年財務與估值資料；快取救援資料只能作暫時參考，不可單獨支撐配置決策。",
        ),
        (
            ("官方最新救援資料",),
            "補齊完整歷史股價、月營收、五年財務與估值資料；官方最新救援資料只能確認近況，不可推論長期趨勢。",
        ),
        (
            ("公司公開文件覆蓋", "高品質公司公開文件"),
            "補抓或人工匯入年報、法說會與官方 IR 文件；未補齊前不得把個股列為可投入資金標的。",
        ),
        (
            ("近況訊號覆蓋", "領先訊號覆蓋"),
            "補齊股價歷史、成交量、月營收與估值資料，避免只靠新聞排序目前情境升值與降值標的。",
        ),
        (
            ("LLM 補充分析",),
            "檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。",
        ),
        (
            ("RAG 自訂 embedding", "RAG 向量庫", "RAG reranker"),
            "檢查 RAG embedding、向量庫與 reranker 設定；恢復後重新產生報告並重新核對來源歸屬。",
        ),
    ]
    for keywords, action in rules:
        if any(keyword in issue_text for keyword in keywords):
            actions.append(action)
    if issue_text and not actions:
        actions.append("先補齊品質警示所列資料缺口，再重新執行完整分析。")
    return _dedupe(actions)


def _dedupe(items: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
