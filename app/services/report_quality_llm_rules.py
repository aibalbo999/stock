from __future__ import annotations


def llm_quality_notes(llm_status: dict | None) -> tuple[list[str], list[str]]:
    if not llm_status:
        return [], []
    warnings: list[str] = []
    observations: list[str] = []
    attempt_summary = llm_status.get("attempt_summary") or {}
    if llm_status.get("fallback"):
        warnings.append("LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿")
    elif attempt_summary.get("success_after_failure"):
        observations.append("LLM 補充分析已完成，但曾經重試或切換備援模型；模型穩定性需持續觀察")
    else:
        observations.append("LLM 補充分析已完成，且仍受來源與白名單驗證約束")
    return warnings, observations
