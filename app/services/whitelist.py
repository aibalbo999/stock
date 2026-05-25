from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.models.schemas import Company, SupplyChainSegment


class SupplyChainWhitelist:
    def __init__(self, path: Path | None = None, raw: dict | None = None) -> None:
        self.path = path or get_settings().whitelist_path
        self.raw = raw or json.loads(self.path.read_text(encoding="utf-8"))
        self.segments = [
            SupplyChainSegment.model_validate(segment) for segment in self.raw["segments"]
        ]
        self.risk_keywords = self.raw["risk_keywords"]

    @classmethod
    def from_candidate_whitelist(cls, candidates: list[dict]) -> "SupplyChainWhitelist":
        base = cls()
        segments_by_name: dict[str, dict] = {}
        for candidate in candidates:
            if candidate.get("status") != "evidence_supported":
                continue
            segment_name = candidate["segment"]
            segment_id = "ai_" + "".join(
                char.lower() for char in segment_name if char.isascii() and char.isalnum()
            )
            if segment_id == "ai_":
                segment_id = f"ai_segment_{len(segments_by_name) + 1}"
            segment = segments_by_name.setdefault(
                segment_name,
                {
                    "id": segment_id,
                    "name": segment_name,
                    "companies": [],
                    "notes": "AI discovered candidate; promoted only after source entity validation.",
                },
            )
            segment["companies"].append(
                {
                    "ticker": candidate["ticker"],
                    "name": candidate["name"],
                    "aliases": [candidate["ticker"], candidate["name"]],
                    "evidence_keywords": candidate.get("evidence_keywords", []),
                }
            )

        raw = {
            "segments": list(segments_by_name.values()),
            "risk_keywords": base.risk_keywords,
            "candidate_audit": candidates,
        }
        return cls(raw=raw)

    def companies(self) -> list[Company]:
        return [company for segment in self.segments for company in segment.companies]

    def allowed_tickers(self) -> set[str]:
        return {company.ticker for company in self.companies()}

    def candidate_audit(self) -> list[dict]:
        return list(self.raw.get("candidate_audit") or [])

    def segment_for_ticker(self, ticker: str) -> SupplyChainSegment | None:
        for segment in self.segments:
            if any(company.ticker == ticker for company in segment.companies):
                return segment
        return None

    def as_prompt_context(self) -> str:
        lines: list[str] = []
        for segment in self.segments:
            companies = (
                ", ".join(
                    f"{c.ticker} {c.name}"
                    + (f"（證據關鍵字：{'、'.join(c.evidence_keywords[:5])}）" if c.evidence_keywords else "")
                    for c in segment.companies
                )
                or "無台股"
            )
            lines.append(f"- {segment.name}: {companies}")
        return "\n".join(lines)
