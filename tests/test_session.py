from app.db.session import session_scope
from app.services.persistence import AnalysisRunRepository


def test_session_scope_keeps_committed_attributes_readable() -> None:
    with session_scope() as session:
        run = AnalysisRunRepository(session).start("test", {"topic": "AI 產業鏈"})

    assert run.id is not None
    assert run.source == "test"
    assert run.status == "running"
