from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.llm_model_routing_policy import normalize_model_name
from app.services.llm_quota_reference import (
    FREE_TIER_RATE_LIMIT_SOURCE,
    FREE_TIER_REQUEST_BUDGET_REFERENCES,
    PROJECT_CONFIGURED_MODEL_BUDGET_NOTES,
    quota_reference_note,
    quota_reference_source,
)

BUDGET_ENV_KEY = "LLM_MODEL_DAILY_REQUEST_BUDGETS"


def llm_quota_env_audit(
    *,
    env_file: str | Path = ".env",
    apply_reference_budgets: bool = False,
) -> dict[str, Any]:
    path = Path(env_file)
    apply_result = (
        apply_llm_quota_env_reference_budgets(path)
        if apply_reference_budgets
        else {"applied": False, "updated_models": []}
    )
    report = _llm_quota_env_audit(path)
    report["apply"] = apply_result
    return report


def apply_llm_quota_env_reference_budgets(env_file: str | Path = ".env") -> dict[str, Any]:
    path = Path(env_file)
    if not path.exists():
        return {
            "applied": False,
            "updated_models": [],
            "reason": "missing_env_file",
        }

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        assignment = _env_assignment(line)
        if not assignment or assignment["key"] != BUDGET_ENV_KEY:
            continue
        updated_value, updated_models = _rewrite_reference_budget_value(
            str(assignment["value"])
        )
        if not updated_models:
            return {
                "applied": False,
                "updated_models": [],
                "reason": "no_reference_budget_drift",
            }
        lines[index] = (
            f"{assignment['prefix']}{assignment['export_prefix']}"
            f"{BUDGET_ENV_KEY}={updated_value}{assignment['newline']}"
        )
        path.write_text("".join(lines), encoding="utf-8")
        return {
            "applied": True,
            "updated_models": updated_models,
            "reason": "reference_budgets_applied",
        }

    return {
        "applied": False,
        "updated_models": [],
        "reason": "missing_budget_env_key",
    }


def _llm_quota_env_audit(path: Path) -> dict[str, Any]:
    base = {
        "collector_path": "app/services/llm_quota_env_audit.py",
        "env_file": str(path),
        "budget_env_key": BUDGET_ENV_KEY,
        "free_tier_rate_limit_source": FREE_TIER_RATE_LIMIT_SOURCE,
        "project_configured_model_notes": PROJECT_CONFIGURED_MODEL_BUDGET_NOTES,
    }
    if not path.exists():
        return {
            **base,
            "status": "missing_env_file",
            "ready": False,
            "model_count": 0,
            "drift_count": 0,
            "invalid_count": 0,
            "rows": [],
            "next_action": f"建立 {path} 並設定 {BUDGET_ENV_KEY}。",
        }

    value = _env_key_value(path, BUDGET_ENV_KEY)
    if value is None:
        return {
            **base,
            "status": "missing_budget_env_key",
            "ready": False,
            "model_count": 0,
            "drift_count": 0,
            "invalid_count": 0,
            "rows": [],
            "next_action": f"在 {path} 加入 {BUDGET_ENV_KEY}=<model>=<requests>。",
        }

    rows = _budget_rows(value)
    drift_rows = [row for row in rows if row["status"] == "drift"]
    invalid_rows = [row for row in rows if row["status"] == "invalid"]
    status = (
        "invalid_budget_value"
        if invalid_rows
        else "drift_detected"
        if drift_rows
        else "ready"
    )
    return {
        **base,
        "status": status,
        "ready": status == "ready",
        "model_count": sum(1 for row in rows if row["status"] != "invalid"),
        "drift_count": len(drift_rows),
        "invalid_count": len(invalid_rows),
        "rows": rows,
        "next_action": _next_action_for_rows(drift_rows, invalid_rows),
    }


def _env_key_value(path: Path, key: str) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        assignment = _env_assignment(line)
        if assignment and assignment["key"] == key:
            return str(assignment["value"])
    return None


def _env_assignment(line: str) -> dict[str, str] | None:
    newline = "\n" if line.endswith("\n") else ""
    body = line[:-1] if newline else line
    prefix_length = len(body) - len(body.lstrip())
    prefix = body[:prefix_length]
    stripped = body[prefix_length:]
    if not stripped or stripped.startswith("#"):
        return None
    export_prefix = ""
    if stripped.startswith("export "):
        export_prefix = "export "
        stripped = stripped.removeprefix("export ").lstrip()
    key_part, separator, value = stripped.partition("=")
    if not separator:
        return None
    key = key_part.strip()
    if not key:
        return None
    return {
        "key": key,
        "value": _strip_env_quotes(value.strip()),
        "prefix": prefix,
        "export_prefix": export_prefix,
        "newline": newline,
    }


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {"'", '"'}:
        return value[1:-1]
    return value


def _budget_rows(raw_value: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, token in enumerate(_budget_tokens(raw_value), start=1):
        if "=" not in token:
            rows.append(
                {
                    "status": "invalid",
                    "token_index": index,
                    "reason": "missing_model_value_separator",
                }
            )
            continue
        model, raw_budget = token.split("=", 1)
        model = model.strip()
        model_key = normalize_model_name(model)
        budget = _positive_int(raw_budget)
        if not model_key or budget is None:
            rows.append(
                {
                    "status": "invalid",
                    "token_index": index,
                    "model": model or "-",
                    "model_key": model_key or "-",
                    "reason": "invalid_positive_integer_budget",
                }
            )
            continue
        official_reference = FREE_TIER_REQUEST_BUDGET_REFERENCES.get(model_key)
        row_status = _budget_row_status(model_key, budget, official_reference)
        rows.append(
            {
                "status": row_status,
                "model": model,
                "model_key": model_key,
                "configured_request_budget": budget,
                "official_free_tier_request_budget_reference": official_reference,
                "quota_reference_source": quota_reference_source(
                    model_key,
                    unreferenced_source="unreferenced_project_config",
                ),
                "quota_reference_note": quota_reference_note(
                    model_key,
                    free_tier_note=str(FREE_TIER_RATE_LIMIT_SOURCE["note"]),
                    unreferenced_note="No public Free Tier reference is tracked for this model.",
                ),
            }
        )
    return rows


def _budget_tokens(raw_value: str) -> list[str]:
    return [token.strip() for token in str(raw_value or "").split(",") if token.strip()]


def _positive_int(raw_value: str) -> int | None:
    try:
        parsed = int(float(str(raw_value).strip()))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _budget_row_status(
    model_key: str,
    configured_budget: int,
    official_reference: int | None,
) -> str:
    if official_reference is None:
        return (
            "project_configured_reference"
            if model_key in PROJECT_CONFIGURED_MODEL_BUDGET_NOTES
            else "no_public_reference"
        )
    return "matches_reference" if configured_budget == official_reference else "drift"


def _rewrite_reference_budget_value(raw_value: str) -> tuple[str, list[str]]:
    tokens: list[str] = []
    updated_models: list[str] = []
    for token in _budget_tokens(raw_value):
        if "=" not in token:
            tokens.append(token)
            continue
        model, raw_budget = token.split("=", 1)
        model_name = model.strip()
        model_key = normalize_model_name(model_name)
        budget = _positive_int(raw_budget)
        official_reference = FREE_TIER_REQUEST_BUDGET_REFERENCES.get(model_key)
        if (
            budget is not None
            and official_reference is not None
            and budget != official_reference
        ):
            tokens.append(f"{model_name}={official_reference}")
            updated_models.append(model_key)
        else:
            tokens.append(f"{model_name}={raw_budget.strip()}")
    return ",".join(tokens), updated_models


def _next_action_for_rows(drift_rows: list[dict[str, Any]], invalid_rows: list[dict[str, Any]]) -> str:
    if invalid_rows:
        return f"修正 {BUDGET_ENV_KEY} 中無法解析的模型額度值。"
    if drift_rows:
        changes = ", ".join(
            (
                f"{row['model_key']}="
                f"{row['official_free_tier_request_budget_reference']}"
            )
            for row in drift_rows
        )
        return f"執行 scripts/llm_quota_env_audit.py --apply 或手動更新：{changes}。"
    return "目前 .env 的 LLM request budgets 與追蹤中的官方/專案參考值一致。"


def format_llm_quota_env_audit(report: dict[str, Any]) -> str:
    lines = [
        (
            f"LLM 額度環境檢查: {report.get('status', 'unknown')} "
            f"(模型數={report.get('model_count', 0)}；"
            f"漂移={report.get('drift_count', 0)}；"
            f"無效={report.get('invalid_count', 0)})"
        )
    ]
    lines.append(f"環境檔: {report.get('env_file', '-')}")
    lines.append(f"建議下一步: {report.get('next_action', '-')}")
    for row in report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        lines.append(
            (
                f"- [{row.get('status', '-')}] {row.get('model_key', '-')} "
                f"已設定={row.get('configured_request_budget', '-')} "
                f"參考額度={row.get('official_free_tier_request_budget_reference', '-')}"
            )
        )
    apply_result = report.get("apply") or {}
    if apply_result.get("applied"):
        lines.append(
            "已套用: "
            + ", ".join(str(model) for model in apply_result.get("updated_models") or [])
        )
    return "\n".join(lines)
