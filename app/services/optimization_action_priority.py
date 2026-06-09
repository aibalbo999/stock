from __future__ import annotations


def prioritized_optimization_next_actions(actions: list[dict]) -> list[dict]:
    prioritized = [
        _action_priority_payload(action, index) for index, action in enumerate(actions)
    ]
    return sorted(
        prioritized,
        key=lambda action: (
            -int(action.get("priority_score") or 0),
            int(action.get("_source_index") or 0),
            str(action.get("domain_label") or ""),
            str(action.get("label") or ""),
        ),
    )


def _action_priority_payload(action: dict, source_index: int) -> dict:
    payload = dict(action)
    optional = bool(payload.get("optional"))
    action_type = str(payload.get("action_type") or "code_or_config")
    locally_available = bool(payload.get("locally_available"))
    capability_status = str(payload.get("capability_status") or payload.get("status") or "")

    priority_score = _action_priority_score(
        optional=optional,
        action_type=action_type,
        locally_available=locally_available,
        capability_status=capability_status,
    )
    payload.update(
        {
            "priority_score": priority_score,
            "priority_band": _action_priority_band(
                optional=optional,
                action_type=action_type,
                locally_available=locally_available,
            ),
            "cost_profile": _action_cost_profile(action_type, locally_available),
            "decision": _action_decision(
                optional=optional,
                action_type=action_type,
                locally_available=locally_available,
            ),
            "priority_reason": _action_priority_reason(
                optional=optional,
                action_type=action_type,
                locally_available=locally_available,
                capability_status=capability_status,
            ),
            "_source_index": source_index,
        }
    )
    return payload


def _action_priority_score(
    *,
    optional: bool,
    action_type: str,
    locally_available: bool,
    capability_status: str,
) -> int:
    if not optional:
        return 100
    if locally_available:
        return 75
    if action_type == "local_dependency":
        return 68
    if action_type == "free_local_or_external_config":
        return 62
    if action_type == "quota_or_external":
        return 55
    if action_type == "paid_external":
        return 30
    if capability_status == "missing":
        return 50
    return 45


def _action_priority_band(
    *,
    optional: bool,
    action_type: str,
    locally_available: bool,
) -> str:
    if not optional:
        return "blocking"
    if locally_available:
        return "free_local_ready"
    if action_type == "local_dependency":
        return "local_dependency"
    if action_type == "free_local_or_external_config":
        return "local_or_external_config"
    if action_type == "quota_or_external":
        return "quota_sensitive"
    if action_type == "paid_external":
        return "paid_external_later"
    return "optional_review"


def _action_cost_profile(action_type: str, locally_available: bool) -> str:
    if locally_available:
        return "free_local_available"
    if action_type == "local_dependency":
        return "local_dependency"
    if action_type == "free_local_or_external_config":
        return "free_local_or_external"
    if action_type == "quota_or_external":
        return "quota_or_external"
    if action_type == "paid_external":
        return "paid_external"
    return "code_or_config"


def _action_decision(
    *,
    optional: bool,
    action_type: str,
    locally_available: bool,
) -> str:
    if not optional:
        return "先處理；這是 blocking 核心缺口。"
    if locally_available:
        return "本機已可免費驗證；正式部署時再固化到 .env。"
    if action_type == "local_dependency":
        return "低成本本機依賴；需要該功能時可優先補齊。"
    if action_type == "free_local_or_external_config":
        return "先用本機/開源方案驗證；高流量部署再接外部服務。"
    if action_type == "quota_or_external":
        return "視免費額度與使用情境啟用；避免搶正式報告模型額度。"
    if action_type == "paid_external":
        return "付費資料源/外部 API；只有正式穩定性需求明確時再採購。"
    return "保留觀測；目前不必優先改程式。"


def _action_priority_reason(
    *,
    optional: bool,
    action_type: str,
    locally_available: bool,
    capability_status: str,
) -> str:
    if not optional:
        return f"capability_status={capability_status or 'unknown'}；影響核心流程。"
    if locally_available:
        return "本機服務已偵測到，驗證成本低且能提升部署信心。"
    if action_type == "local_dependency":
        return "只需補本機依賴，成本低但可按實際 PDF/解析需求延後。"
    if action_type == "quota_or_external":
        return "會消耗 vision/LLM 額度或需要外部 gateway，應按任務情境啟用。"
    if action_type == "paid_external":
        return "屬付費資料或商用外部整合，不應列為一般開發阻斷。"
    return "屬選配能力，優先級低於 blocking 與本機可驗證項。"
