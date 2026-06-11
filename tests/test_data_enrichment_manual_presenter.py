from __future__ import annotations

from datetime import date

from app.ui.data_enrichment_manual_presenter import (
    company_filing_text_preflight_summary,
    company_filing_type_label,
    company_filing_url_preflight_summary,
    manual_news_preflight_summary,
)


def test_manual_news_preflight_summary_explains_confirmation_before_database_write() -> None:
    summary = manual_news_preflight_summary(
        title=" 法說會摘要 ",
        publisher="manual",
        published_at=date(2026, 6, 10),
        ready=True,
        confirmed=False,
    )

    assert summary == {
        "state": "attention",
        "title": "準備寫入新聞/研究摘要",
        "detail": "標題：法說會摘要｜來源：manual｜日期：2026-06-10",
        "next_step": "勾選確認後，再按「匯入新聞/研究摘要」直接寫入資料庫。",
        "quota_hint": "這不會消耗 AI 額度，但會影響後續 RAG/報告引用；送出前請確認來源與內文品質。",
    }


def test_company_filing_text_preflight_summary_labels_document_type() -> None:
    summary = company_filing_text_preflight_summary(
        ticker="2330",
        document_type="investor_presentation",
        title="2026 Q2 法說",
        ready=True,
        confirmed=True,
    )

    assert summary == {
        "state": "ready",
        "title": "可以寫入公司文件",
        "detail": "股票：2330｜類型：法說/投資人簡報｜標題：2026 Q2 法說",
        "next_step": "按「匯入公司文件」直接寫入資料庫；完成後回報告中心確認最新版。",
        "quota_hint": "這不會消耗 AI 額度；資料會影響後續 RAG/報告引用。",
    }


def test_company_filing_url_preflight_summary_explains_background_queue() -> None:
    summary = company_filing_url_preflight_summary(
        ticker="2330",
        document_type="annual_report",
        url="https://example.com/ir.pdf",
        ready=True,
        confirmed=False,
    )

    assert summary == {
        "state": "attention",
        "title": "準備送出 URL 公司文件匯入",
        "detail": "股票：2330｜類型：年報｜URL：https://example.com/ir.pdf",
        "next_step": "勾選確認後，再按「從 URL 抓取並匯入」送出背景任務。",
        "quota_hint": "背景任務會排隊執行；完成前不要重複送出同一份文件。",
    }


def test_company_filing_type_label_falls_back_to_trimmed_custom_value() -> None:
    assert company_filing_type_label(" custom_filing ") == "custom_filing"
