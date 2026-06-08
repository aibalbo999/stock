from __future__ import annotations

from app.models.schemas import InvestorProfile, ReportRequest
from app.services import report_allocation


class ReportGeneratorAllocationMixin:
    @staticmethod
    def _render_allocation_plan(
        candidates: list[dict],
        deployable: int,
        first_tranche: int,
    ) -> list[str]:
        return report_allocation.render_allocation_plan(candidates, deployable, first_tranche)

    @staticmethod
    def _allocation_amounts(
        candidates: list[dict],
        deployable: int,
        first_tranche: int,
    ) -> list[int]:
        return report_allocation.allocation_amounts(candidates, deployable, first_tranche)

    @staticmethod
    def _round_lot_amount(amount: int) -> int:
        return report_allocation.round_lot_amount(amount)

    @staticmethod
    def _round_down_lot_amount(amount: int) -> int:
        return report_allocation.round_down_lot_amount(amount)

    @staticmethod
    def _max_position_amount(request: ReportRequest) -> int:
        return report_allocation.max_position_amount(request)

    @staticmethod
    def _profile(request: ReportRequest) -> InvestorProfile:
        return report_allocation.profile(request)

    @staticmethod
    def _profile_label(request: ReportRequest) -> str:
        return report_allocation.profile_label(request)

    @staticmethod
    def _downside_gate(request: ReportRequest) -> int:
        return report_allocation.downside_gate(request)

    @staticmethod
    def _first_tranche_ratio(request: ReportRequest) -> float:
        return report_allocation.first_tranche_ratio(request)
