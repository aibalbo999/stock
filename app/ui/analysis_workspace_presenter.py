from __future__ import annotations


def analysis_submission_ready(
    topic: str,
    quota_confirmed: bool,
    *,
    ai_discovery_mode: bool = True,
    manual_tickers: list[str] | None = None,
) -> bool:
    if not topic.strip() or not quota_confirmed:
        return False
    if not ai_discovery_mode and not _selected_manual_tickers(manual_tickers):
        return False
    return True


def analysis_submission_summary(
    *,
    topic: str,
    analysis_mode_label: str,
    discovery_limit: int,
    evidence_limit: int,
    lookback_days: int,
    ai_discovery_mode: bool,
    manual_tickers: list[str] | None,
    quota_confirmed: bool,
) -> dict[str, str]:
    topic_label = topic.strip() or "尚未輸入主題"
    manual_ticker_count = len(_selected_manual_tickers(manual_tickers))
    quota_pressure = analysis_submission_quota_pressure(
        analysis_mode_label=analysis_mode_label,
        discovery_limit=discovery_limit,
        evidence_limit=evidence_limit,
        lookback_days=lookback_days,
        ai_discovery_mode=ai_discovery_mode,
        manual_tickers=manual_tickers,
    )
    mode_parts = (
        [analysis_mode_label]
        if ai_discovery_mode
        else [f"手動個股 {manual_ticker_count} 檔", analysis_mode_label]
    )
    detail = "｜".join(
        [
            topic_label,
            *mode_parts,
            f"資料抓取 {int(discovery_limit)}",
            f"引用上限 {int(evidence_limit)}",
            f"回看 {int(lookback_days)} 天",
        ]
    )
    if not topic.strip():
        return {
            "state": "attention",
            "title": "先補齊送出條件",
            "detail": detail,
            "quota_pressure": f"額度壓力：{quota_pressure['level']}",
            "quota_pressure_class": quota_pressure["class"],
            "quota_advice": quota_pressure["advice"],
            "next_step": "請先輸入分析主題。",
            "disabled_reason": "尚未輸入分析主題",
        }
    if not quota_confirmed:
        return {
            "state": "attention",
            "title": "先確認額度消耗",
            "detail": detail,
            "quota_pressure": f"額度壓力：{quota_pressure['level']}",
            "quota_pressure_class": quota_pressure["class"],
            "quota_advice": quota_pressure["advice"],
            "next_step": "勾選額度確認後才能送出背景任務。",
            "disabled_reason": "尚未確認 AI/API 額度消耗",
        }
    if not ai_discovery_mode and manual_ticker_count == 0:
        return {
            "state": "attention",
            "title": "先補齊送出條件",
            "detail": detail,
            "quota_pressure": f"額度壓力：{quota_pressure['level']}",
            "quota_pressure_class": quota_pressure["class"],
            "quota_advice": quota_pressure["advice"],
            "next_step": "手動模式請先選擇至少一檔股票。",
            "disabled_reason": "手動模式尚未選擇股票",
        }
    return {
        "state": "ready",
        "title": "可送出分析背景任務",
        "detail": detail,
        "quota_pressure": f"額度壓力：{quota_pressure['level']}",
        "quota_pressure_class": quota_pressure["class"],
        "quota_advice": quota_pressure["advice"],
        "next_step": "按「執行分析」送出背景任務。",
        "disabled_reason": "",
    }


def analysis_submission_quota_pressure(
    *,
    analysis_mode_label: str,
    discovery_limit: int,
    evidence_limit: int,
    lookback_days: int,
    ai_discovery_mode: bool,
    manual_tickers: list[str] | None,
) -> dict[str, str]:
    score = _analysis_mode_quota_score(analysis_mode_label)
    score += _range_score(int(discovery_limit), [(3, 0), (8, 1), (14, 2)], fallback=3)
    score += _range_score(int(evidence_limit), [(80, 0), (120, 1), (160, 2)], fallback=3)
    score += _range_score(int(lookback_days), [(10, 0), (21, 1), (45, 2)], fallback=3)
    if ai_discovery_mode:
        score += 1
    else:
        manual_ticker_count = len(_selected_manual_tickers(manual_tickers))
        if manual_ticker_count >= 8:
            score += 2
        elif manual_ticker_count >= 4:
            score += 1

    if score <= 2:
        return {
            "level": "低",
            "class": "low",
            "advice": "適合快速試跑或額度偏緊時使用；完成後再視結果升級分析強度。",
        }
    if score <= 6:
        return {
            "level": "中",
            "class": "medium",
            "advice": "適合一般日常分析；若接近免費額度上限，可先降低資料抓取或引用量。",
        }
    if score <= 9:
        return {
            "level": "高",
            "class": "high",
            "advice": "適合已有明確主題時執行；若今天已多次生成報告，建議先讀最新版再重跑。",
        }
    return {
        "level": "很高",
        "class": "very-high",
        "advice": "適合收盤後或額度剛重置時執行；若免費額度緊張，先改用標準研究或降低引用上限。",
    }


def _selected_manual_tickers(manual_tickers: list[str] | None) -> list[str]:
    if not isinstance(manual_tickers, list):
        return []
    return [ticker for ticker in (str(value).strip() for value in manual_tickers) if ticker]


def _analysis_mode_quota_score(analysis_mode_label: str) -> int:
    return {"快速預覽": 0, "標準研究": 2, "深度研究": 4}.get(str(analysis_mode_label), 2)


def _range_score(value: int, thresholds: list[tuple[int, int]], *, fallback: int) -> int:
    for threshold, score in thresholds:
        if value <= threshold:
            return score
    return fallback
