from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, GeneratedReport
from app.models.schemas import ReportRequest, ReportResponse, RiskFinding
from app.services.report_integrity import assert_report_integrity
from app.services.report_retention import (
    empty_repository_retention_result,
    repository_retention_result,
)
from app.services.source_quality import (
    is_formal_evidence_source,
    remove_low_quality_investor_forum_lines,
)


def _formal_report_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
    return [
        finding
        for finding in findings
        if is_formal_evidence_source(
            title=finding.source.title,
            publisher=finding.source.publisher,
            url=finding.source.url,
            source_title=finding.source.title,
            text=f"{finding.topic}\n{finding.evidence}",
        )
    ]


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._last_pruned_report_ids: list[int] = []
        self._last_retained_report_id: int | None = None
        self.last_retention_result: dict = self._empty_retention_result()

    def create(self, request: ReportRequest, response: ReportResponse) -> GeneratedReport:
        markdown = remove_low_quality_investor_forum_lines(response.markdown)
        assert_report_integrity(markdown)
        findings = _formal_report_findings(response.findings)
        report = GeneratedReport(
            title=response.title,
            topic=request.topic,
            tickers_json=json.dumps(request.tickers, ensure_ascii=False),
            findings_json=json.dumps(
                [finding.model_dump(mode="json") for finding in findings],
                ensure_ascii=False,
            ),
            markdown=markdown,
            quality_gate_json=(
                json.dumps(response.quality_gate, ensure_ascii=False)
                if response.quality_gate
                else None
            ),
            generated_at=response.generated_at,
        )
        self.session.add(report)
        self.session.flush()
        created_report_id = report.id
        old_report_versions_deleted = self.prune_older_for_topic(report.topic, report.id)
        retained_report_id = self._last_retained_report_id or created_report_id
        self.last_retention_result = repository_retention_result(
            topic=report.topic,
            created_report_id=created_report_id,
            retained_report_id=retained_report_id,
            old_report_versions_deleted=old_report_versions_deleted,
            old_report_ids=self._last_pruned_report_ids,
        )
        return self.session.get(GeneratedReport, retained_report_id) or report

    def latest(self, limit: int = 20) -> list[GeneratedReport]:
        statement = (
            select(GeneratedReport)
            .order_by(GeneratedReport.generated_at.desc(), GeneratedReport.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def latest_by_topic(self, limit: int = 20) -> list[GeneratedReport]:
        ranked_reports = select(
            GeneratedReport.id.label("report_id"),
            func.row_number()
            .over(
                partition_by=GeneratedReport.topic,
                order_by=(GeneratedReport.generated_at.desc(), GeneratedReport.id.desc()),
            )
            .label("topic_rank"),
        ).subquery()
        statement = (
            select(GeneratedReport)
            .join(ranked_reports, GeneratedReport.id == ranked_reports.c.report_id)
            .where(ranked_reports.c.topic_rank == 1)
            .order_by(GeneratedReport.generated_at.desc(), GeneratedReport.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def get(self, report_id: int) -> GeneratedReport | None:
        return self.session.get(GeneratedReport, report_id)

    def delete(self, report_id: int) -> bool:
        report = self.session.get(GeneratedReport, report_id)
        if report is None:
            return False
        self._clear_analysis_run_report_links([report_id])
        self.session.delete(report)
        self.session.flush()
        return True

    def delete_before(self, before: datetime) -> int:
        old_report_ids = list(
            self.session.scalars(
                select(GeneratedReport.id).where(GeneratedReport.generated_at < before)
            )
        )
        if not old_report_ids:
            return 0
        self._clear_analysis_run_report_links(old_report_ids)
        result = self.session.execute(
            delete(GeneratedReport).where(GeneratedReport.id.in_(old_report_ids))
        )
        self.session.flush()
        return result.rowcount or 0

    def prune_older_by_topic(self) -> int:
        reports = list(
            self.session.scalars(
                select(GeneratedReport).order_by(
                    GeneratedReport.generated_at.desc(),
                    GeneratedReport.id.desc(),
                )
            )
        )
        seen_topics: set[str] = set()
        old_report_ids: list[int] = []
        for report in reports:
            if report.topic in seen_topics:
                old_report_ids.append(report.id)
                continue
            seen_topics.add(report.topic)
        if not old_report_ids:
            return 0
        self._clear_analysis_run_report_links(old_report_ids)
        result = self.session.execute(
            delete(GeneratedReport).where(GeneratedReport.id.in_(old_report_ids))
        )
        self.session.flush()
        return result.rowcount or 0

    def prune_older_for_topic(self, topic: str, keep_report_id: int) -> int:
        self._last_pruned_report_ids = []
        self._last_retained_report_id = None
        retained_report_id = self._latest_report_id_for_topic(topic) or keep_report_id
        self._last_retained_report_id = retained_report_id
        statement = select(GeneratedReport.id).where(
            GeneratedReport.topic == topic,
            GeneratedReport.id != retained_report_id,
        )
        old_report_ids = list(self.session.scalars(statement))
        if not old_report_ids:
            return 0
        self._last_pruned_report_ids = list(old_report_ids)
        self._clear_analysis_run_report_links(old_report_ids)
        result = self.session.execute(
            delete(GeneratedReport).where(GeneratedReport.id.in_(old_report_ids))
        )
        self.session.flush()
        return result.rowcount or 0

    def _latest_report_id_for_topic(self, topic: str) -> int | None:
        statement = (
            select(GeneratedReport.id)
            .where(GeneratedReport.topic == topic)
            .order_by(GeneratedReport.generated_at.desc(), GeneratedReport.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    @staticmethod
    def _empty_retention_result() -> dict:
        return empty_repository_retention_result()

    def _clear_analysis_run_report_links(self, report_ids: list[int]) -> None:
        if not report_ids:
            return
        self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.report_id.in_(report_ids))
            .values(report_id=None, output_path=None)
        )


__all__ = ["ReportRepository"]
