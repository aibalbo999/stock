from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from app.services.company_data_audit import audit_report_company_data


class CompanyDataAuditApiNotFound(ValueError):
    pass


class CompanyDataAuditApiService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        audit_report_company_data_func: Callable = audit_report_company_data,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.audit_report_company_data_func = audit_report_company_data_func

    def report_company_data_audit(self, report_id: int) -> dict:
        with self.session_scope_factory() as session:
            try:
                return self.audit_report_company_data_func(session, report_id)
            except ValueError as exc:
                raise CompanyDataAuditApiNotFound(str(exc)) from exc
