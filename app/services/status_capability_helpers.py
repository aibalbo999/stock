from __future__ import annotations


def capability(state: str, *, evidence: dict, detail: str | None = None) -> dict:
    payload = {
        "status": state,
        "evidence": evidence,
    }
    if detail:
        payload["detail"] = detail
    return payload
