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
    provider = str(evidence.get("configured_provider") or provider_capability.get("provider") or "-")
    provider_tier = str(evidence.get("provider_tier") or provider_capability.get("tier") or "-")
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
            "項目": "Provider",
            "狀態": ready_label(evidence.get("unlocker_provider_ready")),
            "目前": provider,
            "細節": (
                f"tier={provider_tier}；captcha_unlocker="
                f"{yes_no(provider_capability.get('captcha_unlocker'))}"
            ),
            "下一步": next_action,
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
            "狀態": "待設定" if env_lines and not evidence.get("unlocker_provider_ready") else "參考",
            "目前": "\n".join(env_lines) if env_lines else "-",
            "細節": "不改寫 .env；host-only 用 127.0.0.1，compose 服務內用 service DNS。",
            "下一步": "設定後重跑 high-risk filing unlocker smoke。",
        },
        {
            "項目": "MOPS smoke",
            "狀態": "可執行" if smoke_cli else "未提供",
            "目前": smoke_cli or "-",
            "細節": "驗證高風險公開文件入口的 render/unlocker contract。",
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
            "項目": "Fallback 判斷",
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
            "項目": "MOPS smoke",
            "狀態": "可執行",
            "指令": high_risk_mops_smoke_command(evidence),
            "說明": "驗證高風險公開資訊入口能走目前 render/unlocker contract 取得可解析 HTML。",
        },
    ]


def high_risk_mops_smoke_command(evidence: dict) -> str:
    smoke_cli = str(evidence.get("smoke_cli") or "").strip()
    if smoke_cli:
        return smoke_cli
    return ".venv/bin/python scripts/company_filing_render_smoke.py --url https://mops.twse.com.tw/ --json"


def _high_risk_unlocker_strategy(evidence: dict) -> str:
    parts = []
    if evidence.get("unlocker_provider_ready"):
        parts.append("unlocker provider ready")
    if evidence.get("ip_rotation_ready"):
        parts.append("proxy/IP rotation ready")
    if evidence.get("browser_only_render_ready"):
        parts.append("browser render fallback")
    return "；".join(parts) if parts else "尚未配置"


def _high_risk_unlocker_next_action(evidence: dict) -> str:
    if evidence.get("unlocker_provider_ready"):
        return "維持 unlocker provider，定期重跑 MOPS smoke。"
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
