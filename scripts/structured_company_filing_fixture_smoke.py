from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.data_sources.company_filing_structured_api import (
    STRUCTURED_API_PROVIDER_PROFILES,
    STRUCTURED_API_LOCAL_FIXTURE_HOST,
    STRUCTURED_API_LOCAL_FIXTURE_PATH,
    STRUCTURED_API_LOCAL_FIXTURE_PORT,
    STRUCTURED_API_SAMPLE_CONTRACT_PATH,
    structured_api_provider_profile,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TICKER = "2330"
DEFAULT_COMPANY_NAME = "台積電"
DEFAULT_DOCUMENT_TYPES = ("investor_presentation",)
DEFAULT_STARTUP_TIMEOUT_SECONDS = 10.0
DEFAULT_SMOKE_TIMEOUT_SECONDS = 45.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.2
DEFAULT_PROVIDER_PROFILE = "custom"
LOCAL_FIXTURE_AUTH_VALUE = "local-structured-fixture-" + "credential"


def structured_company_filing_fixture_smoke_report(
    *,
    root: Path | None = None,
    sample_json_path: str | Path = STRUCTURED_API_SAMPLE_CONTRACT_PATH,
    host: str = STRUCTURED_API_LOCAL_FIXTURE_HOST,
    port: int = STRUCTURED_API_LOCAL_FIXTURE_PORT,
    path: str = STRUCTURED_API_LOCAL_FIXTURE_PATH,
    ticker: str = DEFAULT_TICKER,
    company_name: str = DEFAULT_COMPANY_NAME,
    document_types: list[str] | tuple[str, ...] | None = DEFAULT_DOCUMENT_TYPES,
    limit: int = 3,
    provider_profile: str = DEFAULT_PROVIDER_PROFILE,
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    smoke_timeout_seconds: float = DEFAULT_SMOKE_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    popen_func=subprocess.Popen,
    run_func=subprocess.run,
    url_ready_func=None,
    sleep_func=time.sleep,
) -> dict[str, Any]:
    root_path = root or PROJECT_ROOT
    sample_path = Path(sample_json_path)
    requested_types = tuple(document_types or ())
    api_path = _normalized_api_path(path)
    fixture_url = f"http://{host}:{int(port)}{api_path}"
    profile = structured_api_provider_profile(provider_profile)
    profile_key = str(profile.get("profile_key") or DEFAULT_PROVIDER_PROFILE)
    token_configured = _profile_requires_token(profile)
    probe_url = _fixture_probe_url(
        fixture_url,
        ticker=ticker,
        company_name=company_name,
        document_types=requested_types,
        limit=limit,
    )
    serve_argv = _fixture_serve_argv(
        sample_path=sample_path,
        host=host,
        port=port,
        path=api_path,
    )
    smoke_argv = _fixture_smoke_argv(
        ticker=ticker,
        company_name=company_name,
        document_types=requested_types,
        limit=limit,
    )
    ready_probe = url_ready_func or _url_ready
    fixture_process = None
    reused_existing_fixture = bool(ready_probe(probe_url, timeout=1.0))
    fixture_started = False
    try:
        if not reused_existing_fixture:
            fixture_process = popen_func(
                [str(part) for part in serve_argv],
                cwd=root_path,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            fixture_started = True
            startup_result = _wait_for_fixture(
                fixture_process,
                probe_url=probe_url,
                timeout_seconds=startup_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                url_ready_func=ready_probe,
                sleep_func=sleep_func,
            )
            if not startup_result["ready"]:
                return _fixture_smoke_error_report(
                    status=str(startup_result["status"]),
                    category=str(startup_result["category"]),
                    message=str(startup_result["message"]),
                    fixture_url=fixture_url,
                    sample_path=sample_path,
                    ticker=ticker,
                    company_name=company_name,
                    document_types=requested_types,
                    limit=limit,
                    provider_profile=profile_key,
                    token_configured=token_configured,
                    serve_argv=serve_argv,
                    smoke_argv=smoke_argv,
                    fixture_started=fixture_started,
                    reused_existing_fixture=reused_existing_fixture,
                    fixture_process=fixture_process,
                )

        completed = run_func(
            [str(part) for part in smoke_argv],
            cwd=root_path,
            env=_fixture_smoke_env(fixture_url, provider_profile=profile_key),
            check=False,
            text=True,
            capture_output=True,
            timeout=float(smoke_timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        return _fixture_smoke_error_report(
            status="failed",
            category="smoke_timeout",
            message=f"Structured fixture HTTP smoke timed out after {smoke_timeout_seconds:g}s.",
            fixture_url=fixture_url,
            sample_path=sample_path,
            ticker=ticker,
            company_name=company_name,
            document_types=requested_types,
            limit=limit,
            provider_profile=profile_key,
            token_configured=token_configured,
            serve_argv=serve_argv,
            smoke_argv=smoke_argv,
            fixture_started=fixture_started,
            reused_existing_fixture=reused_existing_fixture,
            stdout_tail=_tail_text(exc.stdout),
            stderr_tail=_tail_text(exc.stderr),
            fixture_process=fixture_process,
        )
    except Exception as exc:
        return _fixture_smoke_error_report(
            status="failed",
            category="fixture_smoke_exception",
            message=str(exc),
            fixture_url=fixture_url,
            sample_path=sample_path,
            ticker=ticker,
            company_name=company_name,
            document_types=requested_types,
            limit=limit,
            provider_profile=profile_key,
            token_configured=token_configured,
            serve_argv=serve_argv,
            smoke_argv=smoke_argv,
            fixture_started=fixture_started,
            reused_existing_fixture=reused_existing_fixture,
            fixture_process=fixture_process,
        )
    finally:
        if fixture_process is not None:
            _terminate_process(fixture_process)

    smoke_payload = _json_object_from_stdout(completed.stdout)
    ready = completed.returncode == 0 and bool(smoke_payload.get("ready"))
    errors = _fixture_smoke_errors(smoke_payload, completed)
    return {
        "status": "ready" if ready else "failed",
        "ready": ready,
        "mode": "local_fixture_http_smoke",
        "fixture_url": fixture_url,
        "provider_profile": profile_key,
        "auth_mode": str(profile.get("auth_mode") or ""),
        "token_location": str(profile.get("token_location") or ""),
        "token_configured": token_configured,
        "token_redacted": token_configured,
        "document_type_param": str(profile.get("document_type_param") or ""),
        "fixture_started": fixture_started,
        "reused_existing_fixture": reused_existing_fixture,
        "sample_path": str(sample_path),
        "request": smoke_payload.get("request")
        or _request_payload(
            ticker=ticker,
            company_name=company_name,
            document_types=requested_types,
            limit=limit,
        ),
        "runtime": smoke_payload.get("runtime") or {},
        "document_count": int(smoke_payload.get("document_count") or 0),
        "error_count": int(smoke_payload.get("error_count") or len(errors)),
        "documents": _list_value(smoke_payload, "documents"),
        "errors": errors,
        "serve_command": _display_command(serve_argv),
        "smoke_command": _display_smoke_command(
            smoke_argv,
            fixture_url,
            provider_profile=profile_key,
            token_configured=token_configured,
        ),
        "smoke_returncode": int(completed.returncode),
        "smoke_status": smoke_payload.get("status") or "-",
        "stdout_tail": "" if ready else _tail_text(completed.stdout),
        "stderr_tail": "" if ready else _tail_text(completed.stderr),
        "remediation": None
        if ready
        else (
            smoke_payload.get("remediation")
            or "Inspect fixture server output and structured_company_filing_smoke.py stderr."
        ),
    }


def fixture_smoke_exit_code(report: dict[str, Any], *, strict: bool = False) -> int:
    if report.get("ready"):
        return 0
    return 1 if strict else 0


def format_structured_company_filing_fixture_smoke(report: dict[str, Any]) -> str:
    lines = [
        f"Structured company filing fixture HTTP smoke: {report['status']}",
        f"- ready: {str(bool(report.get('ready'))).lower()}",
        f"- fixture url: {report.get('fixture_url') or '-'}",
        f"- provider profile: {report.get('provider_profile') or '-'}",
        f"- fixture started: {str(bool(report.get('fixture_started'))).lower()}",
        f"- reused existing fixture: {str(bool(report.get('reused_existing_fixture'))).lower()}",
        f"- documents: {report.get('document_count', 0)}",
        f"- errors: {report.get('error_count', 0)}",
        f"- command: {report.get('smoke_command') or '-'}",
    ]
    if report.get("remediation"):
        lines.append(f"- remediation: {report['remediation']}")
    return "\n".join(lines)


def _wait_for_fixture(
    fixture_process,
    *,
    probe_url: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    url_ready_func,
    sleep_func,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    while time.monotonic() < deadline:
        returncode = fixture_process.poll()
        if returncode is not None:
            stdout, stderr = _communicate_process(fixture_process)
            return {
                "ready": False,
                "status": "failed",
                "category": "fixture_exited",
                "message": (
                    f"Local structured filing fixture exited before becoming ready "
                    f"(returncode={returncode}, stdout={_tail_text(stdout)}, "
                    f"stderr={_tail_text(stderr)})."
                ),
            }
        if url_ready_func(probe_url, timeout=1.0):
            return {"ready": True, "status": "ready", "category": "", "message": ""}
        sleep_func(max(0.01, float(poll_interval_seconds)))
    return {
        "ready": False,
        "status": "failed",
        "category": "fixture_startup_timeout",
        "message": f"Local structured filing fixture was not ready within {timeout_seconds:g}s.",
    }


def _fixture_smoke_error_report(
    *,
    status: str,
    category: str,
    message: str,
    fixture_url: str,
    sample_path: Path,
    ticker: str,
    company_name: str,
    document_types: tuple[str, ...],
    limit: int,
    provider_profile: str,
    token_configured: bool,
    serve_argv: list[str],
    smoke_argv: list[str],
    fixture_started: bool,
    reused_existing_fixture: bool,
    stdout_tail: str = "",
    stderr_tail: str = "",
    fixture_process=None,
) -> dict[str, Any]:
    process_returncode = fixture_process.poll() if fixture_process is not None else None
    return {
        "status": status,
        "ready": False,
        "mode": "local_fixture_http_smoke",
        "fixture_url": fixture_url,
        "provider_profile": provider_profile,
        "token_configured": token_configured,
        "token_redacted": token_configured,
        "fixture_started": fixture_started,
        "reused_existing_fixture": reused_existing_fixture,
        "fixture_returncode": process_returncode,
        "sample_path": str(sample_path),
        "request": _request_payload(
            ticker=ticker,
            company_name=company_name,
            document_types=document_types,
            limit=limit,
        ),
        "document_count": 0,
        "error_count": 1,
        "documents": [],
        "errors": [{"category": category, "message": message}],
        "serve_command": _display_command(serve_argv),
        "smoke_command": _display_smoke_command(
            smoke_argv,
            fixture_url,
            provider_profile=provider_profile,
            token_configured=token_configured,
        ),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "remediation": "Run the serve_command and smoke_command separately to inspect the failing step.",
    }


def _fixture_serve_argv(
    *,
    sample_path: Path,
    host: str,
    port: int,
    path: str,
) -> list[str]:
    return [
        sys.executable,
        "scripts/local_structured_company_filing_api.py",
        "--sample-json",
        str(sample_path),
        "--host",
        host,
        "--port",
        str(int(port)),
        "--path",
        path,
        "--quiet",
    ]


def _fixture_smoke_argv(
    *,
    ticker: str,
    company_name: str,
    document_types: tuple[str, ...],
    limit: int,
) -> list[str]:
    argv = [
        sys.executable,
        "scripts/structured_company_filing_smoke.py",
        "--ticker",
        ticker,
        "--company-name",
        company_name,
        "--limit",
        str(max(1, int(limit))),
    ]
    for document_type in document_types:
        argv.extend(["--document-type", str(document_type)])
    argv.extend(["--json", "--strict"])
    return argv


def _fixture_smoke_env(
    fixture_url: str,
    *,
    provider_profile: str = DEFAULT_PROVIDER_PROFILE,
) -> dict[str, str]:
    env = dict(os.environ)
    profile = structured_api_provider_profile(provider_profile)
    env["COMPANY_FILING_STRUCTURED_API_PROVIDER"] = str(
        profile.get("profile_key") or DEFAULT_PROVIDER_PROFILE
    )
    env["COMPANY_FILING_STRUCTURED_API_URL"] = fixture_url
    if _profile_requires_token(profile):
        env["COMPANY_FILING_STRUCTURED_API_TOKEN"] = LOCAL_FIXTURE_AUTH_VALUE
    else:
        env.pop("COMPANY_FILING_STRUCTURED_API_TOKEN", None)
    return env


def _fixture_probe_url(
    fixture_url: str,
    *,
    ticker: str,
    company_name: str,
    document_types: tuple[str, ...],
    limit: int,
) -> str:
    query_pairs = [
        ("ticker", ticker),
        ("company_name", company_name),
        ("limit", str(max(1, int(limit)))),
    ]
    query_pairs.extend(("document_type", document_type) for document_type in document_types)
    return f"{fixture_url}?{urlencode(query_pairs)}"


def _url_ready(url: str, *, timeout: float = 1.0) -> bool:
    try:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=max(0.1, float(timeout))) as response:
            if int(response.status) != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, URLError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return bool(
        meta.get("mode") == "local_structured_company_filing_fixture"
        or payload.get("mode") == "local_structured_company_filing_fixture"
        or isinstance(payload.get("documents"), list)
    )


def _normalized_api_path(path: str) -> str:
    normalized = "/" + str(path or STRUCTURED_API_LOCAL_FIXTURE_PATH).strip().strip("/")
    return normalized if normalized != "/" else STRUCTURED_API_LOCAL_FIXTURE_PATH


def _profile_requires_token(profile: dict) -> bool:
    return str(profile.get("auth_mode") or "").strip().lower() not in {
        "",
        "bearer_optional",
        "none",
    }


def _json_object_from_stdout(value: object) -> dict[str, Any]:
    text = _text(value).strip()
    if not text:
        return {}
    for candidate in (text, _json_object_slice(text)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _json_object_slice(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    return text[start : end + 1]


def _fixture_smoke_errors(payload: dict[str, Any], completed: subprocess.CompletedProcess) -> list:
    errors = _list_value(payload, "errors")
    if errors:
        return errors
    if completed.returncode == 0 and payload.get("ready"):
        return []
    return [
        {
            "category": payload.get("status") or "smoke_failed",
            "message": payload.get("remediation") or _tail_text(completed.stderr) or "Smoke failed.",
        }
    ]


def _request_payload(
    *,
    ticker: str,
    company_name: str,
    document_types: tuple[str, ...],
    limit: int,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "company_name": company_name,
        "document_types": list(document_types),
        "limit": max(1, int(limit)),
    }


def _list_value(payload: dict[str, Any], key: str) -> list:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _tail_text(value: object, *, limit: int = 4000) -> str:
    return _text(value)[-limit:]


def _text(value: object) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _display_command(argv: list[str]) -> str:
    display_argv = [".venv/bin/python", *argv[1:]] if argv else []
    return " ".join(shlex.quote(str(part)) for part in display_argv)


def _display_smoke_command(
    argv: list[str],
    fixture_url: str,
    *,
    provider_profile: str = DEFAULT_PROVIDER_PROFILE,
    token_configured: bool = False,
) -> str:
    env_parts = [
        f"COMPANY_FILING_STRUCTURED_API_PROVIDER={shlex.quote(provider_profile)}",
        f"COMPANY_FILING_STRUCTURED_API_URL={shlex.quote(fixture_url)}",
    ]
    if token_configured:
        env_parts.append(
            f"COMPANY_FILING_STRUCTURED_API_TOKEN={shlex.quote('<token>')}"
        )
    return " ".join([*env_parts, _display_command(argv)])


def _communicate_process(process) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=0.2)
    except Exception:
        return "", ""
    return _tail_text(stdout), _tail_text(stderr)


def _terminate_process(process) -> None:
    try:
        if process.poll() is not None:
            _communicate_process(process)
            return
        process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Start the local structured company filing API fixture, run the live HTTP smoke "
            "against it, and stop the fixture."
        )
    )
    parser.add_argument("--host", default=STRUCTURED_API_LOCAL_FIXTURE_HOST, help="Fixture host.")
    parser.add_argument("--port", type=int, default=STRUCTURED_API_LOCAL_FIXTURE_PORT)
    parser.add_argument("--path", default=STRUCTURED_API_LOCAL_FIXTURE_PATH, help="Fixture path.")
    parser.add_argument(
        "--sample-json",
        default=str(STRUCTURED_API_SAMPLE_CONTRACT_PATH),
        help="Sample JSON payload to serve from the fixture.",
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER, help="Ticker to query.")
    parser.add_argument("--company-name", default=DEFAULT_COMPANY_NAME, help="Company name to query.")
    parser.add_argument(
        "--document-type",
        dest="document_types",
        action="append",
        help="Requested document type. Can be repeated.",
    )
    parser.add_argument("--limit", type=int, default=3, help="Maximum documents to request.")
    parser.add_argument(
        "--provider-profile",
        default=DEFAULT_PROVIDER_PROFILE,
        choices=sorted(STRUCTURED_API_PROVIDER_PROFILES),
        help=(
            "Structured API provider profile to validate against the local fixture. "
            "Profiles that require auth receive a local dummy token in the child process."
        ),
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=DEFAULT_STARTUP_TIMEOUT_SECONDS,
        help="Seconds to wait for the local fixture to become reachable.",
    )
    parser.add_argument(
        "--smoke-timeout",
        type=float,
        default=DEFAULT_SMOKE_TIMEOUT_SECONDS,
        help="Seconds to wait for structured_company_filing_smoke.py.",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when not ready.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = structured_company_filing_fixture_smoke_report(
        sample_json_path=args.sample_json,
        host=args.host,
        port=args.port,
        path=args.path,
        ticker=args.ticker,
        company_name=args.company_name,
        document_types=args.document_types or list(DEFAULT_DOCUMENT_TYPES),
        limit=args.limit,
        provider_profile=args.provider_profile,
        startup_timeout_seconds=args.startup_timeout,
        smoke_timeout_seconds=args.smoke_timeout,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_structured_company_filing_fixture_smoke(report))
    return fixture_smoke_exit_code(report, strict=bool(args.strict))


if __name__ == "__main__":
    raise SystemExit(main())
