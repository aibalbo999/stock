from __future__ import annotations

import re

from app.models.schemas import ReportResponse
from app.services.candidate_confidence import format_confidence_score


def render_quality_gate_markdown(quality_gate: dict) -> str:
    labels = {
        "ready": "資料品質可用",
        "caution": "需謹慎判讀",
        "insufficient": "資料不足",
    }
    metrics = quality_gate.get("metrics") or {}
    action_policy = quality_gate.get("action_policy") or {}
    lines = [
        "## 報告品質門檻",
        f"- 狀態：{labels.get(quality_gate.get('status'), quality_gate.get('status', 'unknown'))}",
        f"- 系統判斷：{quality_gate.get('recommendation', '目前無足夠數據判斷。')}",
        f"- 投資行動狀態：{action_policy.get('label', '目前無足夠數據判斷。')}",
        f"- 正式分析股票：{metrics.get('promoted_count', 0)} 檔",
        f"- 候選公司證據覆蓋率：{float(metrics.get('candidate_supported_ratio') or 0):.0%}",
        f"- 探索候選覆蓋率：{float(metrics.get('exploration_candidate_supported_ratio') or 0):.0%}",
        f"- 正式股票證據信心：平均 {_format_confidence_score(metrics.get('formal_confidence_avg'))} / "
        f"最低 {_format_confidence_score(metrics.get('formal_confidence_min'))}",
        f"- 自動搜尋來源入庫：{metrics.get('dynamic_source_count', 0)} 篇",
        f"- 來源發布者數：{_format_optional_int(metrics.get('source_unique_publishers'))}",
        f"- 來源時間戳覆蓋率：{_format_optional_percent(metrics.get('source_timestamp_coverage'))}",
        f"- 近 {int(metrics.get('source_lookback_days') or 90)} 天來源比例：{_format_optional_percent(metrics.get('source_recent_coverage'))}",
        f"- 高可信來源比例：{_format_optional_percent(metrics.get('source_high_credibility_ratio'))}",
        f"- 投資網誌/社群型來源比例：{_format_optional_percent(metrics.get('source_low_credibility_ratio'))}",
        f"- 拆解任務品質：{_format_plan_quality(metrics)}",
        f"- 模型補充分析：{_format_llm_status(metrics)}",
        f"- 資料檢索狀態：{_format_rag_status(metrics)}",
        f"- 市場資料來源：{_format_market_provider_summary(metrics)}",
        f"- 股價資料覆蓋率：{float(metrics.get('market_coverage') or 0):.0%}",
        "- 股價最新可取得交易日："
        f"{metrics.get('market_latest_trade_date') or '尚無'}"
        f"（同日覆蓋率 {_format_optional_percent(metrics.get('market_latest_trade_date_coverage'))}；"
        f"資料庫最新交易日 {metrics.get('market_database_latest_trade_date') or '尚無'}；"
        f"落後資料庫最新日 {int(metrics.get('market_older_than_database_latest_count') or 0)} 檔）",
        f"- 月營收資料覆蓋率：{float(metrics.get('monthly_revenue_coverage') or 0):.0%}",
        f"- 估值資料覆蓋率：{float(metrics.get('valuation_coverage') or 0):.0%}",
        "- 快取救援資料："
        f"股價 {int(metrics.get('market_stale_count') or 0)} 檔、"
        f"月營收 {int(metrics.get('monthly_revenue_stale_count') or 0)} 檔、"
        f"五年財務 {int(metrics.get('financial_metrics_stale_ticker_count') or 0)} 檔、"
        f"估值 {int(metrics.get('valuation_stale_count') or 0)} 檔",
        "- 官方最新救援資料："
        f"股價 {int(metrics.get('market_latest_only_count') or 0)} 檔、"
        f"月營收 {int(metrics.get('monthly_revenue_latest_only_count') or 0)} 檔、"
        f"五年財務 {int(metrics.get('financial_metrics_latest_only_ticker_count') or 0)} 檔、"
        f"估值 {int(metrics.get('valuation_latest_only_count') or 0)} 檔",
        f"- 近況訊號覆蓋率：{_format_optional_percent(metrics.get('leading_signal_coverage'))}",
        f"- 公司公開文件覆蓋率：{_format_optional_percent(metrics.get('company_filing_coverage'))}",
    ]
    if action_policy.get("max_deployable_amount") is not None:
        lines.append(
            f"- 品質門檻研究額度上限：約 {int(action_policy['max_deployable_amount']):,} 元"
            "（不是本次配置或買進指令；本次是否投入仍以投資建議與資金控管為準）"
        )
    blockers = quality_gate.get("blockers") or []
    warnings = quality_gate.get("warnings") or []
    observations = quality_gate.get("observations") or []
    if blockers:
        lines.append("- 阻擋項：" + "；".join(_investor_friendly_issue(item) for item in blockers))
    if warnings:
        lines.append("- 警示項：" + "；".join(_investor_friendly_issue(item) for item in warnings))
    if observations:
        lines.append(
            "- 觀察項：" + "；".join(_investor_friendly_issue(item) for item in observations)
        )
    remediation_actions = quality_gate.get("remediation_actions") or []
    if remediation_actions:
        lines.append(
            "- 建議補強："
            + "；".join(_investor_friendly_issue(action) for action in remediation_actions)
        )
    self_healing = quality_gate.get("self_healing") or {}
    self_healing_actions = self_healing.get("actions") or []
    if self_healing_actions:
        action_labels = "、".join(
            str(action.get("action_type") or action.get("tool") or "補強任務")
            for action in self_healing_actions[:8]
            if isinstance(action, dict)
        )
        lines.append(
            f"- 自癒補強計畫：{self_healing.get('status', 'planned')}；"
            f"{len(self_healing_actions)} 個任務（{action_labels}）"
        )
    if not blockers and not warnings:
        lines.append("- 阻擋/警示：無")
    return "\n".join(lines)


def _format_optional_int(value: object) -> str:
    return "未評估" if value is None else str(value)


def _format_optional_number(value: object) -> str:
    if value is None:
        return "未評估"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _format_confidence_score(value: object) -> str:
    return format_confidence_score(float(value)) if value is not None else "信心分數未匯入品質門檻"


def _format_optional_percent(value: object) -> str:
    return "未評估" if value is None else f"{float(value or 0):.0%}"


def _format_plan_quality(metrics: dict) -> str:
    status = metrics.get("discovery_plan_status")
    score = metrics.get("discovery_plan_score")
    if status is None and score is None:
        return "未評估"
    labels = {
        "ready": "完整",
        "caution": "需補強",
        "insufficient": "不足",
    }
    label = labels.get(str(status), str(status or "unknown"))
    return f"{label}（{int(score or 0)} 分）"


def _format_llm_status(metrics: dict) -> str:
    status = metrics.get("llm_analysis_status")
    if status == "enabled":
        model = metrics.get("llm_model") or "unknown"
        provider = metrics.get("llm_provider")
        provider_text = f"，provider：{provider}" if provider else ""
        recovery_bits = []
        if metrics.get("llm_retry_used"):
            recovery_bits.append("曾重試")
        if metrics.get("llm_model_fallback_used"):
            recovery_bits.append("已切換備援模型")
        elif metrics.get("llm_provider_fallback_used"):
            recovery_bits.append("已切換備援供應商")
        recovery_text = f"，{'、'.join(recovery_bits)}" if recovery_bits else ""
        trace_text = _format_llm_observability(metrics)
        return f"已啟用（模型：{model}{provider_text}{recovery_text}{trace_text}）"
    if status == "fallback":
        reason = metrics.get("llm_primary_failure_category")
        reason_text = f"；主要原因：{reason}" if reason else ""
        return f"未啟用或呼叫失敗，已改用資料規則判讀{reason_text}"
    return "未評估"


def _format_llm_observability(metrics: dict) -> str:
    total_tokens = metrics.get("llm_total_token_estimate")
    latency_ms = metrics.get("llm_latency_ms")
    cost = metrics.get("llm_estimated_cost_usd")
    parts = []
    if total_tokens is not None:
        parts.append(f"token估算：{int(total_tokens):,}")
    if latency_ms is not None:
        parts.append(f"延遲：{int(float(latency_ms))}ms")
    if cost is not None:
        parts.append(f"估算成本：${float(cost):.6f}")
    if not parts:
        return ""
    return "，" + "，".join(parts)


def _format_rag_status(metrics: dict) -> str:
    if (
        metrics.get("rag_retrieval_mode") is None
        and metrics.get("rag_reranker_execution_mode") is None
    ):
        return "未評估"
    retrieval_labels = {
        "chroma_hybrid": "向量庫 + 關鍵字混合檢索",
        "memory_hybrid": "本輪資料 + 關鍵字檢索",
    }
    reranker_labels = {
        "keyword": "關鍵字排序 fallback",
        "cross_encoder": "cross-encoder 重排序",
        "cohere_api": "Cohere API 重排序",
        "llm_rerank": "LLM 模型重排序",
        "input_order": "原排序",
        "input_order_fallback": "重排序 fallback",
    }
    retrieval = retrieval_labels.get(
        str(metrics.get("rag_retrieval_mode") or ""),
        str(metrics.get("rag_retrieval_mode") or "未評估"),
    )
    reranker = reranker_labels.get(
        str(metrics.get("rag_reranker_execution_mode") or ""),
        str(metrics.get("rag_reranker_execution_mode") or "未評估"),
    )
    embedding_fallback = metrics.get("rag_embedding_fallback_reason")
    reranker_fallback = metrics.get("rag_reranker_fallback_reason")
    reranker_gap = metrics.get("rag_reranker_model_gap")
    fallback_notes = []
    if embedding_fallback and embedding_fallback != "chroma_default_requested":
        fallback_notes.append(f"embedding：{embedding_fallback}")
    if reranker_fallback:
        fallback_notes.append(f"reranker：{reranker_fallback}")
    elif reranker_gap:
        fallback_notes.append(f"reranker：{reranker_gap}")
    suffix = "；" + "、".join(fallback_notes) if fallback_notes else ""
    bm25_note = ""
    if metrics.get("rag_bm25_enabled") is True:
        corpus_limit = metrics.get("rag_keyword_corpus_limit")
        if corpus_limit is not None:
            bm25_note = f"，BM25 keyword corpus {int(corpus_limit):,} 筆"
        else:
            bm25_note = "，BM25 關鍵字檢索啟用"
    elif metrics.get("rag_hybrid_search_enabled") is False:
        bm25_note = "，BM25 關鍵字檢索未啟用"
    return f"{retrieval}，{reranker}{bm25_note}{suffix}"


def _format_market_provider_summary(metrics: dict) -> str:
    summary = metrics.get("market_provider_summary") or {}
    if not summary:
        return "未評估"
    parts = []
    for key in ("price_history", "monthly_revenue", "financial_metrics", "valuation"):
        item = summary.get(key) or {}
        label = item.get("label") or key
        providers = item.get("providers") or []
        provider_text = (
            "、".join(str(provider) for provider in providers) if providers else "未入庫"
        )
        stale_count = int(item.get("stale_count") or 0)
        latest_only_count = int(item.get("latest_only_count") or 0)
        notes = []
        if stale_count:
            notes.append(f"含快取救援 {stale_count} 筆")
        if latest_only_count:
            notes.append(f"含官方最新救援 {latest_only_count} 筆")
        if notes:
            provider_text = f"{provider_text}（{'；'.join(notes)}）"
        parts.append(f"{label} {provider_text}")
    return "；".join(parts)


def _investor_friendly_issue(item: object) -> str:
    text = str(item)
    replacements = {
        "LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿": (
            "模型補充分析未啟用或呼叫失敗，個股結論主要由資料規則產生，需人工覆核"
        ),
        "LLM 補充分析已完成，且仍受來源與白名單驗證約束": (
            "模型補充分析已完成，仍只採用可追溯來源與白名單公司"
        ),
        "LLM 補充分析已完成，但曾經重試或切換備援模型；模型穩定性需持續觀察": (
            "模型補充分析已完成，但曾經重試或切換備援模型；模型連線穩定性需持續觀察"
        ),
        "AI 動態資料來源": "自動搜尋資料來源",
        "AI 拆解": "主題拆解",
        "LLM 補充分析": "模型補充分析",
        "檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。": (
            "請系統管理者恢復模型補充分析，恢復後重新產生報告並保留事實核查。"
        ),
        "LLM API key": "模型連線設定",
        "官方 IR 文件": "官方投資人關係文件",
        "規則引擎草稿": "資料規則草稿",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def parse_quality_gate_from_markdown(markdown: str) -> dict | None:
    section = _markdown_section(markdown, "報告品質門檻")
    if not section:
        return None
    fields: dict[str, str] = {}
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("- ") or "：" not in line:
            continue
        key, value = line[2:].split("：", 1)
        fields[key.strip()] = value.strip()

    status_map = {
        "資料品質可用": "ready",
        "需謹慎判讀": "caution",
        "資料不足": "insufficient",
    }
    action_label = fields.get("投資行動狀態", "目前無足夠數據判斷。")
    dynamic_source_field = fields.get("自動搜尋來源入庫") or fields.get("AI 動態來源入庫")
    llm_field = fields.get("模型補充分析") or fields.get("LLM 補充分析")
    recent_source_field = _first_matching_value(fields, r"近\s*\d+\s*天來源比例") or fields.get(
        "近期資料比例"
    )
    return {
        "status": status_map.get(fields.get("狀態", ""), "unknown"),
        "blockers": _split_issue_field(fields.get("阻擋項")),
        "warnings": _split_issue_field(fields.get("警示項")),
        "observations": _split_issue_field(fields.get("觀察項")),
        "remediation_actions": _split_issue_field(fields.get("建議補強")),
        "action_policy": {
            "label": action_label,
            "max_deployable_amount": _parse_amount(
                fields.get("品質門檻研究額度上限")
                or fields.get("品質通過後研究資金上限")
                or fields.get("本輪品質門檻後可投入上限")
            ),
        },
        "metrics": {
            "promoted_count": _parse_int(fields.get("正式分析股票")),
            "candidate_supported_ratio": _parse_percent(fields.get("候選公司證據覆蓋率")),
            "exploration_candidate_supported_ratio": _parse_percent(fields.get("探索候選覆蓋率")),
            "formal_confidence_avg": _parse_confidence_value(
                fields.get("正式股票證據信心"), "平均"
            ),
            "formal_confidence_min": _parse_confidence_value(
                fields.get("正式股票證據信心"), "最低"
            ),
            "dynamic_source_count": _parse_int(dynamic_source_field),
            "source_unique_publishers": _parse_optional_int(fields.get("來源發布者數")),
            "source_timestamp_coverage": _parse_optional_percent(fields.get("來源時間戳覆蓋率")),
            "source_recent_coverage": _parse_optional_percent(recent_source_field),
            "source_lookback_days": _parse_int(
                _first_matching_field(fields, r"近\s*(\d+)\s*天來源比例")
            ),
            "discovery_plan_status": _parse_plan_quality_status(fields.get("拆解任務品質")),
            "discovery_plan_score": _parse_plan_quality_score(fields.get("拆解任務品質")),
            "llm_analysis_status": _parse_llm_status(llm_field),
            "market_coverage": _parse_percent(fields.get("股價資料覆蓋率")),
            "monthly_revenue_coverage": _parse_percent(fields.get("月營收資料覆蓋率")),
            "valuation_coverage": _parse_percent(fields.get("估值資料覆蓋率")),
            "market_stale_count": _parse_stale_metric_count(fields.get("快取救援資料"), "股價"),
            "monthly_revenue_stale_count": _parse_stale_metric_count(
                fields.get("快取救援資料"), "月營收"
            ),
            "financial_metrics_stale_ticker_count": _parse_stale_metric_count(
                fields.get("快取救援資料"), "五年財務"
            ),
            "valuation_stale_count": _parse_stale_metric_count(fields.get("快取救援資料"), "估值"),
            "leading_signal_coverage": _parse_optional_percent(
                fields.get("近況訊號覆蓋率") or fields.get("領先訊號覆蓋率")
            ),
            "company_filing_coverage": _parse_optional_percent(fields.get("公司公開文件覆蓋率")),
        },
        "recommendation": fields.get("系統判斷", "目前無足夠數據判斷。"),
    }


def _markdown_section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)", markdown, flags=re.S | re.M
    )
    return match.group("body").strip() if match else ""


def _split_issue_field(value: str | None) -> list[str]:
    if not value or value == "無":
        return []
    return [item.strip() for item in value.split("；") if item.strip()]


def _first_matching_field(fields: dict[str, str], pattern: str) -> str | None:
    for key in fields:
        match = re.search(pattern, key)
        if match:
            return match.group(1) if match.groups() else key
    return None


def _first_matching_value(fields: dict[str, str], pattern: str) -> str | None:
    for key, value in fields.items():
        if re.search(pattern, key):
            return value
    return None


def _parse_int(value: str | None) -> int:
    if not value:
        return 0
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def _parse_optional_int(value: str | None) -> int | None:
    if not value or value == "未評估":
        return None
    return _parse_int(value)


def _parse_stale_metric_count(value: str | None, label: str) -> int:
    if not value:
        return 0
    match = re.search(rf"{re.escape(label)}\s*(\d+)\s*檔", value)
    return int(match.group(1)) if match else 0


def _parse_percent(value: str | None) -> float:
    parsed = _parse_optional_percent(value)
    return parsed if parsed is not None else 0


def _parse_optional_percent(value: str | None) -> float | None:
    if not value or value == "未評估":
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)%", value)
    return float(match.group(1)) / 100 if match else None


def _parse_confidence_value(value: str | None, label: str) -> float | None:
    if not value or "未評估" in value:
        return None
    match = re.search(rf"{re.escape(label)}\s*(?:高|中|低)?\s*(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


def _parse_plan_quality_status(value: str | None) -> str | None:
    if not value or value == "未評估":
        return None
    if "完整" in value:
        return "ready"
    if "需補強" in value:
        return "caution"
    if "不足" in value:
        return "insufficient"
    return "unknown"


def _parse_plan_quality_score(value: str | None) -> int | None:
    if not value or value == "未評估":
        return None
    match = re.search(r"(\d+)\s*分", value)
    return int(match.group(1)) if match else None


def _parse_llm_status(value: str | None) -> str | None:
    if not value or value == "未評估":
        return None
    if "退回規則引擎" in value or "呼叫失敗" in value:
        return "fallback"
    if "已啟用" in value:
        return "enabled"
    return None


def _parse_amount(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def render_quality_action_guard_markdown(quality_gate: dict) -> str:
    status = quality_gate.get("status")
    if status == "ready":
        return ""
    action_policy = quality_gate.get("action_policy") or {}
    amount = action_policy.get("max_deployable_amount")
    amount_line = (
        f"- 品質門檻後本輪研究資金上限：{int(amount):,} 元；此數字不是買進指令，且優先於後續摘要或表格中的一般資金上限。"
        if amount is not None
        else "- 品質門檻後本輪研究資金上限以本段限制為準，優先於後續摘要或表格中的一般資金上限。"
    )
    if status == "insufficient":
        return "\n".join(
            [
                "## 投資行動限制",
                "- 本次報告品質狀態為「資料不足」。",
                amount_line,
                "- 所有個股結論自動降級為「觀察 / 補資料」，不得視為買入清單。",
                "- 若報告其他章節出現目前情境升值分或可研究字樣，僅代表研究線索，不代表可投入資金。",
                "- 下一步應先補齊阻擋項，再重新執行分析。",
            ]
        )
    return "\n".join(
        [
            "## 投資行動限制",
            "- 本次報告品質狀態為「需謹慎判讀」。",
            amount_line,
            "- 可保留觀察名單，但不應直接轉成買入或加碼指令。",
            "- 需先人工覆核警示項，確認資料缺口不影響核心投資假設。",
        ]
    )


def remove_quality_gate_sections(markdown: str) -> str:
    return re.sub(
        r"\n*## (報告品質門檻|投資行動限制)\n.*?(?=\n## |\Z)",
        "",
        markdown,
        flags=re.S,
    ).strip()


def attach_quality_gate_to_report(response: ReportResponse, quality_gate: dict) -> ReportResponse:
    quality_section = render_quality_gate_markdown(quality_gate)
    action_guard = render_quality_action_guard_markdown(quality_gate)
    inserted_sections = (
        quality_section if not action_guard else f"{quality_section}\n\n{action_guard}"
    )
    markdown = remove_quality_gate_sections(response.markdown)
    first_section = markdown.find("\n## ")
    if first_section == -1:
        markdown = f"{markdown.rstrip()}\n\n{inserted_sections}"
    else:
        markdown = f"{markdown[:first_section].rstrip()}\n\n{inserted_sections}\n{markdown[first_section:]}"
    return response.model_copy(update={"markdown": markdown, "quality_gate": quality_gate})
