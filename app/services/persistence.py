from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisRun,
    CompanyFiling,
    FinancialMetricSnapshot,
    GeneratedReport,
    MonthlyRevenueSnapshot,
    NewsArticle,
    RiskClassificationCache,
    StockPriceSnapshot,
    ValuationMetricSnapshot,
)
from app.models.schemas import (
    CompanyFilingDocument,
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ReportResponse,
    Source,
    ValuationMetric,
)
from app.services.report_integrity import assert_report_integrity


class NewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_document(self, document: NewsDocument, entity_matches: list[dict]) -> NewsArticle:
        values = {
            "title": document.title,
            "text": document.text,
            "publisher": document.source.publisher,
            "url": document.source.url,
            "published_at": document.source.published_at,
            "fetched_at": document.source.fetched_at,
            "entity_matches_json": json.dumps(entity_matches, ensure_ascii=False),
        }
        return self.session.merge(NewsArticle(id=document.id, **values))

    def upsert_document_merging_matches(self, document: NewsDocument, entity_matches: list[dict]) -> NewsArticle:
        existing = self.session.get(NewsArticle, document.id)
        merged_matches = self._merge_entity_matches(
            json.loads(existing.entity_matches_json) if existing else [],
            entity_matches,
        )
        return self.upsert_document(document, merged_matches)

    @staticmethod
    def _merge_entity_matches(existing: list[dict], incoming: list[dict]) -> list[dict]:
        merged: dict[tuple[str, str], dict] = {}
        for item in [*existing, *incoming]:
            ticker = str(item.get("ticker") or "")
            segment_id = str(item.get("segment_id") or "")
            if not ticker:
                continue
            merged[(ticker, segment_id)] = item
        return list(merged.values())

    def latest_documents(self, limit: int = 20) -> list[NewsDocument]:
        statement = select(NewsArticle).order_by(NewsArticle.created_at.desc()).limit(limit)
        return [self._to_document(article) for article in self.session.scalars(statement)]

    def search_documents(self, query: str, limit: int = 20) -> list[NewsDocument]:
        terms = [term for term in query.split() if term]
        statement = select(NewsArticle).order_by(NewsArticle.created_at.desc()).limit(limit * 3)
        documents = [self._to_document(article) for article in self.session.scalars(statement)]
        if not terms:
            return documents[:limit]
        ranked = [
            document
            for document in documents
            if any(term in document.title or term in document.text for term in terms)
        ]
        return ranked[:limit]

    @staticmethod
    def _to_document(article: NewsArticle) -> NewsDocument:
        return NewsDocument(
            id=article.id,
            title=article.title,
            text=article.text,
            source=Source(
                title=article.title,
                url=article.url,
                publisher=article.publisher,
                published_at=article.published_at,
                fetched_at=article.fetched_at,
            ),
        )


class CompanyFilingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_document(self, document: CompanyFilingDocument) -> CompanyFiling:
        row = self.session.get(CompanyFiling, document.id)
        values = {
            "ticker": document.ticker,
            "company_name": document.company_name,
            "document_type": document.document_type,
            "title": document.title,
            "text": document.text,
            "publisher": document.source.publisher,
            "url": document.source.url,
            "published_at": document.source.published_at,
            "fetched_at": document.source.fetched_at,
        }
        if row is None:
            row = CompanyFiling(id=document.id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        return row

    def latest_by_tickers(self, tickers: list[str], limit_per_ticker: int = 5) -> list[CompanyFilingDocument]:
        documents: list[CompanyFilingDocument] = []
        for ticker in tickers:
            statement = (
                select(CompanyFiling)
                .where(CompanyFiling.ticker == ticker)
                .order_by(CompanyFiling.published_at.desc().nullslast(), CompanyFiling.created_at.desc())
                .limit(limit_per_ticker)
            )
            documents.extend(self._to_document(row) for row in self.session.scalars(statement))
        return documents

    def search_documents(self, query: str, tickers: list[str] | None = None, limit: int = 20) -> list[CompanyFilingDocument]:
        terms = [term for term in query.split() if term]
        statement = select(CompanyFiling).order_by(
            CompanyFiling.published_at.desc().nullslast(),
            CompanyFiling.created_at.desc(),
        )
        if tickers:
            statement = statement.where(CompanyFiling.ticker.in_(tickers))
        rows = list(self.session.scalars(statement.limit(limit * 4)))
        if terms:
            rows = [
                row
                for row in rows
                if any(term in row.title or term in row.text or term == row.ticker for term in terms)
            ]
        return [self._to_document(row) for row in rows[:limit]]

    def stats_by_ticker(self, ticker: str) -> dict:
        rows = list(
            self.session.scalars(
                select(CompanyFiling).where(CompanyFiling.ticker == ticker)
            )
        )
        latest = max((row.published_at for row in rows if row.published_at), default=None)
        return {
            "rows": len(rows),
            "document_types": sorted({row.document_type for row in rows}),
            "publishers": len({row.publisher or row.url or row.title for row in rows}),
            "latest_date": latest.isoformat() if latest else None,
        }

    @staticmethod
    def _to_document(row: CompanyFiling) -> CompanyFilingDocument:
        return CompanyFilingDocument(
            id=row.id,
            ticker=row.ticker,
            company_name=row.company_name,
            document_type=row.document_type,
            title=row.title,
            text=row.text,
            source=Source(
                title=row.title,
                url=row.url,
                publisher=row.publisher,
                published_at=row.published_at,
                fetched_at=row.fetched_at,
            ),
        )

    @staticmethod
    def to_news_document(document: CompanyFilingDocument) -> NewsDocument:
        label = f"公司公開文件/{document.document_type}"
        company = f"{document.ticker} {document.company_name or ''}".strip()
        text = (
            f"股票代號：{document.ticker}\n"
            f"公司名稱：{document.company_name or ''}\n"
            f"文件類型：{document.document_type}\n"
            f"{company}\n"
            f"{document.text}"
        )
        return NewsDocument(
            id=f"filing-{document.id}",
            title=document.title,
            text=text,
            source=Source(
                title=document.title,
                url=document.source.url,
                publisher=document.source.publisher or label,
                published_at=document.source.published_at,
                fetched_at=document.source.fetched_at,
            ),
        )


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, request: ReportRequest, response: ReportResponse) -> GeneratedReport:
        assert_report_integrity(response.markdown)
        report = GeneratedReport(
            title=response.title,
            topic=request.topic,
            tickers_json=json.dumps(request.tickers, ensure_ascii=False),
            findings_json=json.dumps(
                [finding.model_dump(mode="json") for finding in response.findings],
                ensure_ascii=False,
            ),
            markdown=response.markdown,
            generated_at=response.generated_at,
        )
        self.session.add(report)
        self.session.flush()
        return report

    def latest(self, limit: int = 20) -> list[GeneratedReport]:
        statement = select(GeneratedReport).order_by(GeneratedReport.generated_at.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def get(self, report_id: int) -> GeneratedReport | None:
        return self.session.get(GeneratedReport, report_id)

    def delete(self, report_id: int) -> bool:
        report = self.session.get(GeneratedReport, report_id)
        if report is None:
            return False
        self.session.delete(report)
        self.session.flush()
        return True

    def delete_before(self, before: datetime) -> int:
        result = self.session.execute(delete(GeneratedReport).where(GeneratedReport.generated_at < before))
        self.session.flush()
        return result.rowcount or 0


class MarketRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_snapshots(self, snapshots: list[MarketSnapshot]) -> list[StockPriceSnapshot]:
        rows: list[StockPriceSnapshot] = []
        for snapshot in snapshots:
            statement = select(StockPriceSnapshot).where(
                StockPriceSnapshot.ticker == snapshot.ticker,
                StockPriceSnapshot.trade_date == snapshot.trade_date,
            )
            row = self.session.scalars(statement).first()
            values = snapshot.model_dump()
            if row is None:
                row = StockPriceSnapshot(**values)
                self.session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            rows.append(row)
        self.session.flush()
        return rows

    def latest_by_tickers(self, tickers: list[str]) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []
        for ticker in tickers:
            statement = (
                select(StockPriceSnapshot)
                .where(StockPriceSnapshot.ticker == ticker)
                .order_by(StockPriceSnapshot.trade_date.desc())
                .limit(1)
            )
            row = self.session.scalars(statement).first()
            if row:
                snapshots.append(self._to_snapshot(row))
        return snapshots

    def history_by_tickers(self, tickers: list[str], limit: int = 80) -> dict[str, list[MarketSnapshot]]:
        histories: dict[str, list[MarketSnapshot]] = {}
        for ticker in tickers:
            statement = (
                select(StockPriceSnapshot)
                .where(StockPriceSnapshot.ticker == ticker)
                .order_by(StockPriceSnapshot.trade_date.desc())
                .limit(limit)
            )
            rows = list(self.session.scalars(statement))
            histories[ticker] = [self._to_snapshot(row) for row in reversed(rows)]
        return histories

    @staticmethod
    def _to_snapshot(row: StockPriceSnapshot) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=row.ticker,
            trade_date=row.trade_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            spread=row.spread,
            trading_volume=row.trading_volume,
            trading_money=row.trading_money,
            trading_turnover=row.trading_turnover,
            source=row.source,
            fetched_at=row.fetched_at,
        )


class MonthlyRevenueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_revenues(self, revenues: list[MonthlyRevenue]) -> list[MonthlyRevenueSnapshot]:
        rows: list[MonthlyRevenueSnapshot] = []
        for revenue in revenues:
            statement = select(MonthlyRevenueSnapshot).where(
                MonthlyRevenueSnapshot.ticker == revenue.ticker,
                MonthlyRevenueSnapshot.revenue_date == revenue.revenue_date,
            )
            row = self.session.scalars(statement).first()
            values = revenue.model_dump(exclude={"yoy_pct"})
            if row is None:
                row = MonthlyRevenueSnapshot(**values)
                self.session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            rows.append(row)
        self.session.flush()
        return rows

    def latest_by_tickers(self, tickers: list[str]) -> list[MonthlyRevenue]:
        latest: list[MonthlyRevenue] = []
        for ticker in tickers:
            statement = (
                select(MonthlyRevenueSnapshot)
                .where(MonthlyRevenueSnapshot.ticker == ticker)
                .order_by(MonthlyRevenueSnapshot.revenue_date.desc())
                .limit(1)
            )
            row = self.session.scalars(statement).first()
            if row:
                latest.append(self._to_revenue(row, self._yoy_pct(row)))
        return latest

    def history_by_tickers(self, tickers: list[str], limit: int = 18) -> dict[str, list[MonthlyRevenue]]:
        histories: dict[str, list[MonthlyRevenue]] = {}
        for ticker in tickers:
            statement = (
                select(MonthlyRevenueSnapshot)
                .where(MonthlyRevenueSnapshot.ticker == ticker)
                .order_by(MonthlyRevenueSnapshot.revenue_date.desc())
                .limit(limit)
            )
            rows = list(self.session.scalars(statement))
            histories[ticker] = [self._to_revenue(row, self._yoy_pct(row)) for row in reversed(rows)]
        return histories

    def _yoy_pct(self, row: MonthlyRevenueSnapshot) -> float | None:
        previous = self.session.scalars(
            select(MonthlyRevenueSnapshot)
            .where(
                MonthlyRevenueSnapshot.ticker == row.ticker,
                MonthlyRevenueSnapshot.revenue_year == row.revenue_year - 1,
                MonthlyRevenueSnapshot.revenue_month == row.revenue_month,
            )
            .limit(1)
        ).first()
        if previous is None or previous.revenue <= 0:
            return None
        return round((row.revenue - previous.revenue) / previous.revenue * 100, 2)

    @staticmethod
    def _to_revenue(row: MonthlyRevenueSnapshot, yoy_pct: float | None = None) -> MonthlyRevenue:
        return MonthlyRevenue(
            ticker=row.ticker,
            revenue_date=row.revenue_date,
            revenue=row.revenue,
            revenue_year=row.revenue_year,
            revenue_month=row.revenue_month,
            yoy_pct=yoy_pct,
            source=row.source,
            fetched_at=row.fetched_at,
        )


class FinancialMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_metrics(self, metrics: list[FinancialMetric]) -> list[FinancialMetricSnapshot]:
        rows: list[FinancialMetricSnapshot] = []
        for metric in metrics:
            statement = select(FinancialMetricSnapshot).where(
                FinancialMetricSnapshot.ticker == metric.ticker,
                FinancialMetricSnapshot.report_date == metric.report_date,
                FinancialMetricSnapshot.statement_type == metric.statement_type,
                FinancialMetricSnapshot.metric == metric.metric,
            )
            row = self.session.scalars(statement).first()
            values = metric.model_dump()
            if row is None:
                row = FinancialMetricSnapshot(**values)
                self.session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            rows.append(row)
        self.session.flush()
        return rows

    def by_tickers(self, tickers: list[str]) -> list[FinancialMetric]:
        if not tickers:
            return []
        statement = (
            select(FinancialMetricSnapshot)
            .where(FinancialMetricSnapshot.ticker.in_(tickers))
            .order_by(FinancialMetricSnapshot.report_date.desc())
        )
        return [self._to_metric(row) for row in self.session.scalars(statement)]

    @staticmethod
    def _to_metric(row: FinancialMetricSnapshot) -> FinancialMetric:
        return FinancialMetric(
            ticker=row.ticker,
            report_date=row.report_date,
            statement_type=row.statement_type,
            metric=row.metric,
            value=row.value,
            origin_name=row.origin_name,
            source=row.source,
            fetched_at=row.fetched_at,
        )


class ValuationMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_valuations(self, valuations: list[ValuationMetric]) -> list[ValuationMetricSnapshot]:
        rows: list[ValuationMetricSnapshot] = []
        for valuation in valuations:
            statement = select(ValuationMetricSnapshot).where(
                ValuationMetricSnapshot.ticker == valuation.ticker,
                ValuationMetricSnapshot.trade_date == valuation.trade_date,
            )
            row = self.session.scalars(statement).first()
            values = valuation.model_dump()
            if row is None:
                row = ValuationMetricSnapshot(**values)
                self.session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            rows.append(row)
        self.session.flush()
        return rows

    def latest_by_tickers(self, tickers: list[str]) -> list[ValuationMetric]:
        latest: list[ValuationMetric] = []
        for ticker in tickers:
            statement = (
                select(ValuationMetricSnapshot)
                .where(ValuationMetricSnapshot.ticker == ticker)
                .order_by(ValuationMetricSnapshot.trade_date.desc())
                .limit(1)
            )
            row = self.session.scalars(statement).first()
            if row:
                latest.append(self._to_valuation(row))
        return latest

    @staticmethod
    def _to_valuation(row: ValuationMetricSnapshot) -> ValuationMetric:
        return ValuationMetric(
            ticker=row.ticker,
            trade_date=row.trade_date,
            pe_ratio=row.pe_ratio,
            pb_ratio=row.pb_ratio,
            dividend_yield=row.dividend_yield,
            source=row.source,
            fetched_at=row.fetched_at,
        )


class RiskClassificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, document_id: str, topic_hash: str) -> dict | None:
        row = self.session.get(RiskClassificationCache, {"document_id": document_id, "topic_hash": topic_hash})
        if row is None:
            return None
        return {
            "document_id": row.document_id,
            "topic_hash": row.topic_hash,
            "classification": row.classification,
            "topic": row.topic,
            "evidence": row.evidence,
            "confidence": row.confidence,
            "keywords": json.loads(row.keywords_json),
            "model": row.model,
        }

    def upsert(
        self,
        document_id: str,
        topic_hash: str,
        classification: str,
        topic: str,
        evidence: str,
        confidence: float,
        keywords: list[str],
        model: str | None,
    ) -> RiskClassificationCache:
        row = self.session.get(RiskClassificationCache, {"document_id": document_id, "topic_hash": topic_hash})
        values = {
            "classification": classification,
            "topic": topic,
            "evidence": evidence,
            "confidence": confidence,
            "keywords_json": json.dumps(keywords, ensure_ascii=False),
            "model": model,
            "updated_at": datetime.utcnow(),
        }
        if row is None:
            row = RiskClassificationCache(document_id=document_id, topic_hash=topic_hash, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self.session.flush()
        return row


class AnalysisRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start(self, source: str, payload: dict) -> AnalysisRun:
        run = AnalysisRun(
            source=source,
            status="running",
            payload_json=json.dumps(payload, ensure_ascii=False),
            started_at=datetime.utcnow(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def mark_success(
        self,
        run_id: int,
        report_id: int,
        output_path: str | None = None,
    ) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        run.status = "success"
        run.report_id = report_id
        run.output_path = output_path
        run.finished_at = datetime.utcnow()
        self.session.flush()
        return run

    def update_payload(self, run_id: int, payload: dict) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        run.payload_json = json.dumps(payload, ensure_ascii=False)
        self.session.flush()
        return run

    def mark_failed(self, run_id: int, error: str) -> AnalysisRun:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        run.status = "failed"
        run.error = error
        run.finished_at = datetime.utcnow()
        self.session.flush()
        return run

    def latest(self, limit: int = 20) -> list[AnalysisRun]:
        statement = select(AnalysisRun).order_by(AnalysisRun.started_at.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def get(self, run_id: int) -> AnalysisRun | None:
        return self.session.get(AnalysisRun, run_id)

    def get_by_report_id(self, report_id: int) -> AnalysisRun | None:
        statement = (
            select(AnalysisRun)
            .where(AnalysisRun.report_id == report_id)
            .order_by(AnalysisRun.started_at.desc())
            .limit(1)
        )
        return self.session.scalars(statement).first()

    def get_by_celery_task_id(self, task_id: str) -> AnalysisRun | None:
        statement = select(AnalysisRun).order_by(AnalysisRun.started_at.desc())
        for run in self.session.scalars(statement):
            try:
                payload = json.loads(run.payload_json)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("celery_task_id") == task_id:
                return run
        return None

    def delete(self, run_id: int) -> bool:
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            return False
        self.session.delete(run)
        self.session.flush()
        return True

    def delete_failed(self) -> int:
        result = self.session.execute(delete(AnalysisRun).where(AnalysisRun.status == "failed"))
        self.session.flush()
        return result.rowcount or 0

    def mark_stale_running_failed(self, before: datetime, error: str = "run timed out") -> int:
        statement = select(AnalysisRun).where(
            AnalysisRun.status == "running",
            AnalysisRun.started_at < before,
        )
        stale_runs = list(self.session.scalars(statement))
        finished_at = datetime.utcnow()
        for run in stale_runs:
            run.status = "failed"
            run.error = error
            run.finished_at = finished_at
        self.session.flush()
        return len(stale_runs)

    def delete_before(self, before: datetime) -> int:
        result = self.session.execute(delete(AnalysisRun).where(AnalysisRun.started_at < before))
        self.session.flush()
        return result.rowcount or 0

    def orphan_report_ids(self) -> list[int]:
        statement = (
            select(AnalysisRun.id)
            .outerjoin(GeneratedReport, AnalysisRun.report_id == GeneratedReport.id)
            .where(AnalysisRun.report_id.is_not(None), GeneratedReport.id.is_(None))
        )
        return list(self.session.scalars(statement))

    def clear_orphan_report_refs(self) -> int:
        orphan_ids = self.orphan_report_ids()
        if not orphan_ids:
            return 0
        result = self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id.in_(orphan_ids))
            .values(report_id=None)
        )
        self.session.flush()
        return result.rowcount or 0
