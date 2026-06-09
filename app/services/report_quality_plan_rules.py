from __future__ import annotations


def discovery_plan_quality_notes(plan_quality: dict | None) -> tuple[list[str], list[str]]:
    if not plan_quality:
        return [], []
    blockers: list[str] = []
    warnings: list[str] = []
    plan_status = str(plan_quality.get("status") or "unknown")
    plan_score = int(plan_quality.get("score") or 0)
    missing = plan_quality.get("missing") or []
    missing_summary = "、".join(str(item) for item in missing[:3])
    detail = f"：{missing_summary}" if missing_summary else ""
    if plan_status == "insufficient" or plan_score < 55:
        blockers.append(f"AI 拆解任務品質不足{detail}")
    elif plan_status == "caution" or plan_score < 80:
        warnings.append(f"AI 拆解任務仍有缺口{detail}")
    return blockers, warnings
