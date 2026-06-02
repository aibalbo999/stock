from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import get_settings


class EvidenceScoringConfig(BaseModel):
    min_documents_for_upside: int = 2
    positive_keyword_points: int = 2
    opportunity_finding_points: int = 3
    document_count_offset: int = 2
    max_evidence_score: int = 15
    upside_base: int = 10
    negative_keyword_points: int = 2
    structural_finding_points: int = 2
    volatility_finding_points: int = 1
    max_news_risk_score: int = 15
    downside_base: int = 5


class ThresholdScoringConfig(BaseModel):
    upside_activation_floor: int = 11
    downside_activation_floor: int = 6
    research_upside_gate: int = 10
    risk_downside_gate: int = 5
    financial_red_flag_min_risk_score: int = 7
    financial_red_flag_upside_cap: int = 20


class RevenueScoringConfig(BaseModel):
    yoy_upside_threshold: float = 10
    yoy_upside_divisor: float = 10
    yoy_upside_min: int = 2
    yoy_upside_max: int = 5
    yoy_downside_threshold: float = 0
    yoy_downside_divisor: float = 5
    yoy_downside_min: int = 2
    yoy_downside_max: int = 6


class EarlyPotentialScoringConfig(BaseModel):
    hot_trading_money: int = 1_000_000_000
    scarce_document_limit: int = 3
    scarce_publisher_limit: int = 2
    limited_document_limit: int = 8
    limited_publisher_limit: int = 5
    reported_document_limit: int = 15
    hot_attention_bonus: int = -4
    scarce_attention_bonus: int = 10
    limited_attention_bonus: int = 6
    reported_attention_bonus: int = 2
    crowded_attention_bonus: int = -4
    strong_revenue_yoy_threshold: float = 20
    positive_revenue_yoy_threshold: float = 10
    strong_revenue_bonus: int = 6
    positive_revenue_bonus: int = 3
    strong_leading_signal_threshold: int = 5
    strong_leading_signal_bonus: int = 6
    positive_leading_signal_bonus: int = 3
    high_downside_threshold: int = 12
    moderate_downside_threshold: int = 5
    high_downside_penalty: int = 8
    moderate_downside_penalty: int = 3
    upside_score_reference: int = 10
    upside_score_divisor: int = 3
    max_score: int = 30


class ScoringConfig(BaseModel):
    evidence: EvidenceScoringConfig = Field(default_factory=EvidenceScoringConfig)
    thresholds: ThresholdScoringConfig = Field(default_factory=ThresholdScoringConfig)
    revenue: RevenueScoringConfig = Field(default_factory=RevenueScoringConfig)
    early_potential: EarlyPotentialScoringConfig = Field(default_factory=EarlyPotentialScoringConfig)


class PotentialScoringEngine:
    def __init__(self, config: ScoringConfig | None = None) -> None:
        self.config = config or load_scoring_config()

    def news_upside_score(
        self,
        *,
        document_count: int,
        positive_hits: int,
        opportunity_findings: int,
    ) -> tuple[int, int]:
        cfg = self.config.evidence
        if document_count < cfg.min_documents_for_upside:
            return 0, 0
        if positive_hits < 1 and not opportunity_findings:
            return 0, 0
        score = min(
            cfg.max_evidence_score,
            positive_hits * cfg.positive_keyword_points
            + opportunity_findings * cfg.opportunity_finding_points
            + max(0, document_count - cfg.document_count_offset),
        )
        return score, cfg.upside_base + score

    def news_downside_score(
        self,
        *,
        negative_hits: int,
        structural_findings: int,
        volatility_findings: int,
    ) -> tuple[int, int]:
        cfg = self.config.evidence
        if negative_hits < 1 and not structural_findings and not volatility_findings:
            return 0, 0
        score = min(
            cfg.max_news_risk_score,
            negative_hits * cfg.negative_keyword_points
            + structural_findings * cfg.structural_finding_points
            + volatility_findings * cfg.volatility_finding_points,
        )
        return score, cfg.downside_base + score

    def revenue_upside_bonus(self, yoy_pct: float | None) -> int:
        cfg = self.config.revenue
        if yoy_pct is None or yoy_pct < cfg.yoy_upside_threshold:
            return 0
        return min(cfg.yoy_upside_max, max(cfg.yoy_upside_min, int(yoy_pct // cfg.yoy_upside_divisor)))

    def revenue_downside_penalty(self, yoy_pct: float | None) -> int:
        cfg = self.config.revenue
        if yoy_pct is None or yoy_pct >= cfg.yoy_downside_threshold:
            return 0
        return min(
            cfg.yoy_downside_max,
            max(cfg.yoy_downside_min, int(abs(yoy_pct) // cfg.yoy_downside_divisor)),
        )

    def activate_upside(self, current: int, bonus: int) -> int:
        if bonus <= 0:
            return current
        return max(self.config.thresholds.upside_activation_floor, current) + bonus

    def activate_downside(self, current: int, penalty: int) -> int:
        if penalty <= 0:
            return current
        return max(self.config.thresholds.downside_activation_floor, current) + penalty

    def early_attention(self, *, document_count: int, publisher_count: int, trading_money: int | None) -> tuple[str, int]:
        cfg = self.config.early_potential
        if trading_money is not None and trading_money >= cfg.hot_trading_money:
            return "截至目前成交熱度高", cfg.hot_attention_bonus
        if document_count <= cfg.scarce_document_limit and publisher_count <= cfg.scarce_publisher_limit:
            return "報導較少", cfg.scarce_attention_bonus
        if document_count <= cfg.limited_document_limit and publisher_count <= cfg.limited_publisher_limit:
            return "報導偏少", cfg.limited_attention_bonus
        if document_count <= cfg.reported_document_limit:
            return "截至目前已有報導", cfg.reported_attention_bonus
        return "截至目前大量報導", cfg.crowded_attention_bonus

    def early_revenue_bonus(self, yoy_pct: float | None) -> int:
        cfg = self.config.early_potential
        if yoy_pct is None:
            return 0
        bonus = 0
        if yoy_pct >= cfg.strong_revenue_yoy_threshold:
            bonus += cfg.strong_revenue_bonus
        if yoy_pct >= cfg.positive_revenue_yoy_threshold:
            bonus += cfg.positive_revenue_bonus
        return bonus

    def early_leading_signal_bonus(self, upside_bonus: int) -> int:
        cfg = self.config.early_potential
        if upside_bonus >= cfg.strong_leading_signal_threshold:
            return cfg.strong_leading_signal_bonus
        if upside_bonus > 0:
            return cfg.positive_leading_signal_bonus
        return 0

    def early_downside_penalty(self, downside_pct: int) -> int:
        cfg = self.config.early_potential
        if downside_pct > cfg.high_downside_threshold:
            return cfg.high_downside_penalty
        if downside_pct > cfg.moderate_downside_threshold:
            return cfg.moderate_downside_penalty
        return 0

    def early_score(self, *, attention_bonus: int, signal_bonus: int, upside_pct: int) -> int:
        cfg = self.config.early_potential
        upside_component = max(0, upside_pct - cfg.upside_score_reference) // max(1, cfg.upside_score_divisor)
        return max(0, min(cfg.max_score, attention_bonus + signal_bonus + upside_component))


def load_scoring_config(path: Path | None = None) -> ScoringConfig:
    path = path or get_settings().scoring_config_path
    if not path.exists():
        return ScoringConfig()
    return ScoringConfig.model_validate(_load_toml(path))


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:
        return _load_simple_toml(path)
    with path.open("rb") as file:
        return tomllib.load(file)


def _load_simple_toml(path: Path) -> dict[str, Any]:
    data: dict[str, dict[str, Any]] = {}
    section: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = data.setdefault(line[1:-1].strip(), {})
            continue
        if section is None or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        section[key] = _parse_simple_toml_value(value)
    return data


def _parse_simple_toml_value(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
