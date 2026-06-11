from __future__ import annotations

from app.ui.external_deployment_common import (
    external_deployment_item_by_capability,
    ready_label,
    string_list,
    yes_no,
)


def high_risk_filing_unlocker_rows(upgrade_audit: dict) -> list[dict]:
    item = external_deployment_item_by_capability(
        upgrade_audit,
        "company_filing_high_risk_unlocker",
    )
    if not item:
        return []
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    provider_capability = (
        evidence.get("provider_capability")
        if isinstance(evidence.get("provider_capability"), dict)
        else {}
    )
    provider = str(
        evidence.get("configured_provider") or provider_capability.get("provider") or "-"
    )
    provider_tier = str(evidence.get("provider_tier") or provider_capability.get("tier") or "-")
    configuration_check = (
        evidence.get("configuration_check")
        if isinstance(evidence.get("configuration_check"), dict)
        else {}
    )
    recommended_env = string_list(evidence.get("recommended_env"))
    compose_recommended_env = string_list(evidence.get("compose_recommended_env"))
    env_lines = [*recommended_env]
    if compose_recommended_env:
        env_lines.extend(["# compose", *compose_recommended_env])
    domains = string_list(evidence.get("domains"))
    smoke_cli = str(evidence.get("smoke_cli") or "").strip()
    next_action = item.get("remediation") or _high_risk_unlocker_next_action(evidence)
    return [
        {
            "項目": "解鎖服務",
            "狀態": ready_label(evidence.get("unlocker_provider_ready")),
            "目前": provider,
            "細節": (
                f"tier={provider_tier}；captcha_unlocker="
                f"{yes_no(provider_capability.get('captcha_unlocker'))}"
            ),
            "下一步": next_action,
        },
        {
            "項目": "設定檢查",
            "狀態": _high_risk_unlocker_status_label(
                _high_risk_unlocker_configuration_status(configuration_check)
            ),
            "目前": _high_risk_unlocker_configuration_current(configuration_check),
            "細節": _high_risk_unlocker_configuration_detail(configuration_check),
            "下一步": _high_risk_unlocker_configuration_next_action(configuration_check),
        },
        {
            "項目": "高風險防護",
            "狀態": ready_label(evidence.get("captcha_challenge_ready")),
            "目前": _high_risk_unlocker_strategy(evidence),
            "細節": str(evidence.get("fallback_reason") or "-"),
            "下一步": _high_risk_unlocker_next_action(evidence),
        },
        {
            "項目": "高風險網域",
            "狀態": "範圍",
            "目前": "、".join(domains) if domains else "-",
            "細節": "MOPS / doc.twse / TWSE / TPEx",
            "下一步": "-",
        },
        {
            "項目": "建議 env",
            "狀態": "待設定"
            if env_lines and not evidence.get("unlocker_provider_ready")
            else "參考",
            "目前": "\n".join(env_lines) if env_lines else "-",
            "細節": "不改寫 .env；host-only 用 127.0.0.1，compose 服務內用 service DNS。",
            "下一步": "設定後重跑高風險文件解鎖檢查。",
        },
        {
            "項目": "MOPS 解鎖檢查",
            "狀態": "可執行" if smoke_cli else "未提供",
            "目前": smoke_cli or "-",
            "細節": "驗證高風險公開文件入口的網頁解析與解鎖流程。",
            "下一步": smoke_cli or "-",
        },
    ]


def local_unlocker_operation_rows(upgrade_audit: dict) -> list[dict]:
    item = external_deployment_item_by_capability(
        upgrade_audit,
        "company_filing_high_risk_unlocker",
    )
    if not item:
        return []
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    return [
        {
            "項目": "一鍵啟動",
            "狀態": _local_unlocker_start_status(evidence),
            "指令": ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker",
            "說明": "啟動 Browserless 與 FlareSolverr，並在本次程序優先套用 unlocker provider。",
        },
        {
            "項目": "本機稽核",
            "狀態": "已就緒" if evidence.get("unlocker_provider_ready") else "待驗證",
            "指令": (
                ".venv/bin/python scripts/upgrade_audit.py "
                "--prefer-unlocker --wait-local-flaresolverr 20 "
                "--local-browser-render-defaults --json"
            ),
            "說明": "等待 FlareSolverr 8191 後套用本機 defaults；不改寫 .env。",
        },
        {
            "項目": "備援判斷",
            "狀態": "目前路徑",
            "指令": "-",
            "說明": _local_unlocker_fallback_detail(evidence),
        },
        {
            "項目": "容器診斷",
            "狀態": "必要時",
            "指令": "docker compose ps flaresolverr && docker compose logs flaresolverr",
            "說明": "檢查 FlareSolverr container 是否啟動、port 是否綁定、image 是否拉取成功。",
        },
        {
            "項目": "MOPS 解鎖檢查",
            "狀態": "可執行",
            "指令": high_risk_mops_smoke_command(evidence),
            "說明": "驗證高風險公開資訊入口能走目前網頁解析與解鎖流程取得可解析 HTML。",
        },
    ]


def high_risk_mops_smoke_command(evidence: dict) -> str:
    smoke_cli = str(evidence.get("smoke_cli") or "").strip()
    if smoke_cli:
        return smoke_cli
    return (
        ".venv/bin/python scripts/company_filing_render_smoke.py "
        "--local-browser-render-defaults --prefer-unlocker "
        "--url https://mops.twse.com.tw/ --json"
    )


def _high_risk_unlocker_strategy(evidence: dict) -> str:
    parts = []
    if evidence.get("unlocker_provider_ready"):
        parts.append("Unlocker provider 可用")
    if evidence.get("ip_rotation_ready"):
        parts.append("Proxy/IP rotation 可用")
    if evidence.get("browser_only_render_ready"):
        parts.append("Browser render 後援")
    return "；".join(parts) if parts else "尚未配置"


def _high_risk_unlocker_configuration_status(configuration_check: dict) -> str:
    if not configuration_check:
        return "未提供"
    if configuration_check.get("ready"):
        return "ready"
    return str(configuration_check.get("status") or "missing_required_env")


def _high_risk_unlocker_status_label(value: object) -> str:
    status_labels = {
        "ready": "可用",
        "missing_required_env": "缺少必要設定",
        "not_configured": "未設定",
        "degraded": "需處理",
        "failed": "需處理",
        "unknown": "未評估",
    }
    text = str(value or "unknown")
    return status_labels.get(text, text)


def _high_risk_unlocker_configuration_current(configuration_check: dict) -> str:
    if not configuration_check:
        return "-"
    missing = string_list(configuration_check.get("missing_env_keys"))
    configured = string_list(configuration_check.get("configured_env_keys"))
    return (
        f"provider={configuration_check.get('provider') or '-'}；"
        f"missing={','.join(missing) or '-'}；"
        f"configured={','.join(configured) or '-'}"
    )


def _high_risk_unlocker_configuration_detail(configuration_check: dict) -> str:
    if not configuration_check:
        return "缺少 configuration_check；請重跑系統狀態檢查或 upgrade audit。"
    token_state = "required" if configuration_check.get("token_required") else "optional"
    endpoint_configured = bool(configuration_check.get("endpoint_configured"))
    endpoint_valid = bool(configuration_check.get("endpoint_valid"))
    endpoint_state = (
        "valid" if endpoint_valid else "configured_invalid" if endpoint_configured else "missing"
    )
    return (
        f"provider_supported={yes_no(configuration_check.get('provider_supported'))}；"
        f"token={token_state}；"
        f"token_configured={yes_no(configuration_check.get('token_configured'))}；"
        f"endpoint={endpoint_state}。"
    )


def _high_risk_unlocker_configuration_next_action(configuration_check: dict) -> str:
    if not configuration_check:
        return "重跑系統狀態檢查或 upgrade audit，確認 unlocker 配置檢查結果。"
    if configuration_check.get("ready"):
        return "配置完整；重跑高風險文件解鎖檢查驗證入口頁。"
    missing = string_list(configuration_check.get("missing_env_keys"))
    fallback_reason = str(configuration_check.get("fallback_reason") or "")
    if "COMPANY_FILING_BROWSER_RENDER_TOKEN" in missing:
        return "設定 COMPANY_FILING_BROWSER_RENDER_TOKEN 後重跑 MOPS 解鎖檢查。"
    if "COMPANY_FILING_BROWSER_RENDER_ENABLED" in missing:
        return "設定 COMPANY_FILING_BROWSER_RENDER_ENABLED=true 並補齊 render URL。"
    if (
        "COMPANY_FILING_BROWSER_RENDER_URL" in missing
        or fallback_reason == "missing_browser_render_url"
    ):
        return "設定 COMPANY_FILING_BROWSER_RENDER_URL 後重跑高風險文件解鎖檢查。"
    if fallback_reason == "invalid_browser_render_url":
        return "修正 COMPANY_FILING_BROWSER_RENDER_URL，需為 http/https 且包含 host。"
    if fallback_reason == "unsupported_browser_render_provider":
        return "改用 FlareSolverr、ScrapingBee 或 BrightData 等支援的 render/unlocker provider。"
    return "補齊缺少的 unlocker env 後重跑高風險文件解鎖檢查。"


def _high_risk_unlocker_next_action(evidence: dict) -> str:
    if evidence.get("unlocker_provider_ready"):
        return "維持 unlocker provider，定期重跑 MOPS 解鎖檢查。"
    if evidence.get("ip_rotation_ready"):
        return "已具備 IP rotation；仍建議補 FlareSolverr、ScrapingBee 或 BrightData。"
    if evidence.get("browser_only_render_ready"):
        return "目前只有 Browserless/Playwright；高風險 CAPTCHA 入口需補 unlocker provider。"
    return "設定 FlareSolverr、ScrapingBee 或 BrightData，或至少配置 rotating proxy。"


def _local_unlocker_start_status(evidence: dict) -> str:
    if evidence.get("unlocker_provider_ready"):
        return "可重跑"
    if evidence.get("browser_only_render_ready") or evidence.get("ip_rotation_ready"):
        return "建議升級"
    return "待啟動"


def _local_unlocker_fallback_detail(evidence: dict) -> str:
    if evidence.get("unlocker_provider_ready"):
        return "目前使用 FlareSolverr、ScrapingBee 或 BrightData 等 unlocker provider。"
    if evidence.get("ip_rotation_ready"):
        return "目前具備 proxy/IP rotation，但高風險 CAPTCHA 入口仍缺 unlocker provider。"
    if evidence.get("browser_only_render_ready"):
        return "目前會 fallback 到 Browserless/Playwright；高風險 CAPTCHA 入口仍需 unlocker。"
    return "尚未配置 browser render、proxy 或 unlocker；高風險公開文件容易只取到阻擋頁。"
