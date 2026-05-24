from app.tasks.tasks import build_run_payload


def test_build_run_payload_includes_task_id_and_ingestion() -> None:
    payload = {"topic": "AI 產業鏈", "tickers": ["2330"], "lookback_days": 7}
    ingestion = {"news": {"count": 0}, "market": {"requested_tickers": ["2330"]}}

    assert build_run_payload(payload, "task-123", ingestion) == {
        "request": payload,
        "celery_task_id": "task-123",
        "ingestion": ingestion,
    }


def test_build_run_payload_omits_empty_optional_fields() -> None:
    payload = {"topic": "AI 產業鏈"}

    assert build_run_payload(payload) == {"request": payload}
