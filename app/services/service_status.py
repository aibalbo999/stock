from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse

import redis

from app.core.config import get_settings
from app.data_sources.company_filings import (
    company_filing_browser_render_status,
    company_filing_playwright_browser_status,
    company_filing_structured_api_status,
)
from app.db.migration_status import db_migration_status
from app.db.session import engine
from app.services.candidate_confidence import confidence_thresholds
from app.services.llm_client import RETRYABLE_HTTP_STATUSES
from app.services.llm_observability import llm_observability_status
from app.services.source_quality import SOURCE_CREDIBILITY_LABELS, SOURCE_CREDIBILITY_WEIGHTS
from app.services.status_company_filings import (
    company_filing_status as collect_company_filing_status,
)
from app.services.status_capability_matrix import (
    upgrade_capability_matrix as build_upgrade_capability_matrix,
)
from app.services.status_frontend import frontend_status as collect_frontend_status
from app.services.status_llm import (
    _llm_effective_fallback_models,
    _llm_model_provider,
    _llm_quota_routing_status,
)
from app.services.status_graphrag import (
    supply_chain_graph_status as collect_supply_chain_graph_status,
)
from app.services.status_market_data import (
    market_data_status as collect_market_data_status,
)
from app.services.status_vector_store import vector_store_status as collect_vector_store_status
from app.services.visual_rag import visual_rag_status
from app.services.workflow_orchestration import workflow_orchestration_status


def service_status() -> dict:
    settings = get_settings()
    high_threshold, medium_threshold = confidence_thresholds()
    redis_status = _redis_status(settings.redis_url)
    llm_fallback_models = _llm_effective_fallback_models(settings)
    llm_local_gateway_configured = any(
        _llm_model_provider(model) == "local" for model in llm_fallback_models
    )
    llm_quota_routing = _llm_quota_routing_status(settings)
    llm_observability = llm_observability_status(settings)
    visual_rag_runtime = visual_rag_status(settings)
    market_data_status = collect_market_data_status(settings, redis_status=redis_status)
    supply_chain_graph_status = collect_supply_chain_graph_status()
    vector_store_status = collect_vector_store_status(
        settings,
        module_available=_module_available,
    )
    company_filing_status = collect_company_filing_status(
        settings,
        redis_status=redis_status,
        visual_rag_runtime=visual_rag_runtime,
        module_available=_module_available,
        browser_render_status_func=company_filing_browser_render_status,
        playwright_browser_status_func=company_filing_playwright_browser_status,
        structured_api_status_func=company_filing_structured_api_status,
    )
    frontend_status = collect_frontend_status()
    python_runtime_status = _python_runtime_status()
    report_retention_status = _report_retention_status()
    status = {
        "database": {
            "init_mode": settings.database_init_mode,
            "create_all_non_sqlite_allowed": settings.database_allow_create_all_non_sqlite,
            "migration": db_migration_status(bind=engine),
        },
        "redis": redis_status,
        "gemini": {
            "configured": len(settings.gemini_api_keys) > 0,
            "key_count": len(settings.gemini_api_keys),
            "model": settings.primary_llm_model,
            "provider": settings.llm_provider,
            "fallback_models": llm_fallback_models,
            "provider_keys_configured": {
                "gemini": len(settings.gemini_api_keys) > 0,
                "openai": bool(settings.openai_api_key),
                "anthropic": bool(settings.anthropic_api_key),
                "local": llm_local_gateway_configured,
            },
            "retryable_http_statuses": sorted(RETRYABLE_HTTP_STATUSES),
            "max_retries_per_key": max(0, int(settings.llm_max_retries_per_key)),
            "base_retry_delay_seconds": max(0.0, float(settings.llm_base_retry_delay_seconds)),
            "max_retry_delay_seconds": max(0.0, float(settings.llm_max_retry_delay_seconds)),
        },
        "frontend": frontend_status,
        "python_runtime": python_runtime_status,
        "report_retention": report_retention_status,
        "llm_quota_routing": llm_quota_routing,
        "llm_observability": llm_observability,
        "finmind": market_data_status["finmind"],
        "fugle": market_data_status["fugle"],
        "market_data_cache": market_data_status["market_data_cache"],
        "company_filings": company_filing_status,
        "vector_store": vector_store_status,
        "supply_chain_graph": supply_chain_graph_status,
        "celery": {
            "broker_url": _redact_url(settings.redis_url),
            "backend_url": _redact_url(settings.redis_url),
        },
        "workflow_orchestration": workflow_orchestration_status(settings),
        "security_scanning": _security_scan_status(),
        "candidate_confidence": {
            "high_threshold": high_threshold,
            "medium_threshold": medium_threshold,
            "promotion_rule": "正式分析需至少 2 篇證據、2 個來源，證據信心達高信心門檻，且低可信來源不得單獨支撐高信心。",
            "source_credibility_weights": SOURCE_CREDIBILITY_WEIGHTS,
            "source_credibility_labels": SOURCE_CREDIBILITY_LABELS,
        },
    }
    status["upgrade_capability_matrix"] = build_upgrade_capability_matrix(status)
    return status


def _python_runtime_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    pyproject_text = _read_text(root / "pyproject.toml")
    python_version_text = _read_text(root / ".python-version").strip()
    ci_text = _read_text(root / ".github" / "workflows" / "ci.yml")
    dockerfile_text = _read_text(root / "Dockerfile")
    required_specifier = _pyproject_requires_python(pyproject_text)
    minimum_supported = _minimum_python_from_requires(required_specifier)
    current_version = ".".join(str(part) for part in sys.version_info[:3])
    current_major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    current_supported = (
        sys.version_info[:2] >= minimum_supported if minimum_supported is not None else True
    )
    target_version = (
        f"{minimum_supported[0]}.{minimum_supported[1]}" if minimum_supported else ""
    )
    ci_targets_python = bool(target_version and f'python-version: "{target_version}"' in ci_text)
    docker_targets_python = bool(target_version and f"python:{target_version}" in dockerfile_text)
    python_version_file_matches = python_version_text == target_version if target_version else False
    project_targets_aligned = bool(
        target_version and ci_targets_python and docker_targets_python and python_version_file_matches
    )
    return {
        "current_version": current_version,
        "current_major_minor": current_major_minor,
        "implementation": sys.implementation.name,
        "executable": sys.executable,
        "required_specifier": required_specifier,
        "minimum_supported": target_version,
        "current_runtime_supported": current_supported,
        "python_version_file": python_version_text,
        "python_version_file_matches": python_version_file_matches,
        "ci_targets_python": ci_targets_python,
        "docker_targets_python": docker_targets_python,
        "project_targets_aligned": project_targets_aligned,
        "bootstrap_cli": ".venv/bin/python scripts/bootstrap_python_runtime.py --apply --replace-existing",
        "bootstrap_dry_run_cli": ".venv/bin/python scripts/bootstrap_python_runtime.py --json",
        "bootstrap_backup_policy": "Unsupported existing .venv is moved to .venv.backup-<timestamp> only with --replace-existing.",
        "interpreter_install_hints": _python_interpreter_install_hints(target_version),
        "recommended_action": (
            "Install a supported Python interpreter if needed, then rebuild .venv with "
            f"Python {target_version}+ before production startup."
            if target_version and not current_supported
            else None
        ),
    }


def _python_interpreter_install_hints(target_version: str) -> list[dict[str, str]]:
    version = str(target_version or "").strip()
    if not version:
        return []
    return [
        {
            "tool": "homebrew",
            "command": f"brew install python@{version}",
            "venv_command": f"python{version} -m venv .venv",
        },
        {
            "tool": "pyenv",
            "command": f"pyenv install {version}",
            "venv_command": f"pyenv local {version} && python -m venv .venv",
        },
        {
            "tool": "uv",
            "command": f"uv python install {version}",
            "venv_command": f"uv venv --python {version} .venv",
        },
    ]


def _pyproject_requires_python(pyproject_text: str) -> str:
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("requires-python"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _minimum_python_from_requires(specifier: str) -> tuple[int, int] | None:
    marker = ">="
    if marker not in specifier:
        return None
    version = specifier.split(marker, 1)[1].split(",", 1)[0].strip()
    parts = version.split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _report_retention_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    persistence_source = _read_text(root / "app" / "services" / "persistence.py")
    report_files_source = _read_text(root / "app" / "services" / "report_files.py")
    report_query_source = _read_text(root / "app" / "services" / "report_query.py")
    data_operations_source = _read_text(root / "app" / "services" / "data_operations_api.py")
    maintenance_ui_source = _read_text(
        root / "app" / "ui" / "system_settings_maintenance.py"
    )
    write_prunes_db = "self.prune_older_for_topic(report.topic, report.id)" in persistence_source
    report_file_write_prunes = (
        "prune_report_files_for_topic(report_dir, safe_topic, keep_path=path)"
        in report_files_source
    )
    return {
        "policy": "latest_per_topic",
        "write_prunes_db_by_topic": write_prunes_db,
        "write_prunes_markdown_by_topic": report_file_write_prunes,
        "repository_latest_by_topic_available": "def latest_by_topic(" in persistence_source
        and "seen_topics" in persistence_source,
        "repository_bulk_prune_available": "def prune_older_by_topic(" in persistence_source,
        "repository_topic_prune_available": "def prune_older_for_topic(" in persistence_source,
        "run_links_cleared_for_pruned_reports": ".values(report_id=None)" in persistence_source,
        "markdown_bulk_prune_available": "def prune_older_report_files_by_topic(" in report_files_source,
        "markdown_topic_key_parser_available": "def report_file_topic_key(" in report_files_source,
        "list_reports_uses_latest_by_topic": "latest_by_topic(limit)" in report_query_source,
        "quality_summary_uses_latest_by_topic": "latest_by_topic(safe_limit)"
        in report_query_source,
        "report_list_returns_policy": '"retention_policy": "latest_per_topic"'
        in report_query_source,
        "maintenance_prunes_db_by_topic": "reports.prune_older_by_topic()"
        in data_operations_source,
        "maintenance_prunes_markdown_by_topic": "self._prune_older_report_files()"
        in data_operations_source
        and "prune_older_report_files_by_topic" in data_operations_source,
        "maintenance_returns_policy": '"report_retention_policy": "latest_per_topic"'
        in data_operations_source,
        "settings_ui_cleanup_action": '"latest_reports_only": True' in maintenance_ui_source
        and '"orphan_report_refs": True' in maintenance_ui_source,
        "covered_paths": [
            "app/services/persistence.py",
            "app/services/report_files.py",
            "app/services/report_query.py",
            "app/services/data_operations_api.py",
            "app/ui/system_settings_maintenance.py",
        ],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _security_scan_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "security_scan.py"
    pyproject_path = root / "pyproject.toml"
    try:
        pyproject_text = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        pyproject_text = ""
    detect_secrets_cli = shutil.which("detect-secrets") is not None
    gitleaks_cli = shutil.which("gitleaks") is not None
    default_engine = (
        "detect-secrets"
        if detect_secrets_cli
        else "gitleaks"
        if gitleaks_cli
        else "local_regex"
    )
    return {
        "script": str(script_path.relative_to(root)),
        "pyproject_command_configured": "scripts/security_scan.py" in pyproject_text,
        "external_engine_integration": True,
        "supported_external_engines": ["detect-secrets", "gitleaks"],
        "detect_secrets_dependency_declared": "detect-secrets" in pyproject_text,
        "detect_secrets_cli_available": detect_secrets_cli,
        "detect_secrets_module_available": _module_available("detect_secrets"),
        "gitleaks_cli_available": gitleaks_cli,
        "default_engine": default_engine,
        "local_regex_fallback_enabled": script_path.exists(),
        "local_regex_fallback_role": "fallback_only",
        "scan_scope_default": "git_tracked_files",
        "all_files_flag": "--all",
    }


def _redis_status(redis_url: str) -> dict:
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        pong = client.ping()
        return {"ok": bool(pong), "url": _redact_url(redis_url)}
    except Exception as exc:
        return {"ok": False, "url": _redact_url(redis_url), "error": str(exc)}


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.password is None:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        netloc = f"{parsed.username}:***@{netloc}"
    return parsed._replace(netloc=netloc).geturl()
