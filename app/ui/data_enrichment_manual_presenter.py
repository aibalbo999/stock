from __future__ import annotations

from typing import Any

COMPANY_FILING_TYPE_LABELS = {
    "annual_report": "年報",
    "investor_presentation": "法說/投資人簡報",
    "prospectus": "公開說明書",
    "material_information": "重大訊息",
    "company_disclosure": "其他公司揭露",
}


def manual_news_preflight_summary(
    *,
    title: str,
    publisher: str,
    published_at: Any,
    ready: bool,
    confirmed: bool,
) -> dict[str, str]:
    detail = (
        f"標題：{_text(title, default='尚未填寫')}｜"
        f"來源：{_text(publisher, default='manual')}｜日期：{_date_text(published_at)}"
    )
    if not ready:
        return {
            "state": "attention",
            "title": "新聞/研究摘要尚未完整",
            "detail": detail,
            "next_step": "請先填入標題與內文。",
            "quota_hint": "尚未寫入資料庫；確認內容可避免低品質資料污染報告。",
        }
    if not confirmed:
        return {
            "state": "attention",
            "title": "準備寫入新聞/研究摘要",
            "detail": detail,
            "next_step": "勾選確認後，再按「匯入新聞/研究摘要」直接寫入資料庫。",
            "quota_hint": "這不會消耗 AI 額度，但會影響後續 RAG/報告引用；送出前請確認來源與內文品質。",
        }
    return {
        "state": "ready",
        "title": "可以寫入新聞/研究摘要",
        "detail": detail,
        "next_step": "按「匯入新聞/研究摘要」直接寫入資料庫；完成後回報告中心確認最新版。",
        "quota_hint": "這不會消耗 AI 額度；資料會影響後續 RAG/報告引用。",
    }


def company_filing_text_preflight_summary(
    *,
    ticker: str,
    document_type: str,
    title: str,
    ready: bool,
    confirmed: bool,
) -> dict[str, str]:
    detail = (
        f"股票：{_text(ticker, default='尚未選擇')}｜"
        f"類型：{company_filing_type_label(document_type)}｜"
        f"標題：{_text(title, default='尚未填寫')}"
    )
    if not ready:
        return {
            "state": "attention",
            "title": "公司文件尚未完整",
            "detail": detail,
            "next_step": "請先填入文件標題與文字，或改用 URL 匯入。",
            "quota_hint": "尚未寫入資料庫；確認文件內容可避免低品質資料污染報告。",
        }
    if not confirmed:
        return {
            "state": "attention",
            "title": "準備寫入公司文件",
            "detail": detail,
            "next_step": "勾選確認後，再按「匯入公司文件」直接寫入資料庫。",
            "quota_hint": "這不會消耗 AI 額度，但會影響後續 RAG/報告引用；送出前請確認文件來源與文字品質。",
        }
    return {
        "state": "ready",
        "title": "可以寫入公司文件",
        "detail": detail,
        "next_step": "按「匯入公司文件」直接寫入資料庫；完成後回報告中心確認最新版。",
        "quota_hint": "這不會消耗 AI 額度；資料會影響後續 RAG/報告引用。",
    }


def company_filing_url_preflight_summary(
    *,
    ticker: str,
    document_type: str,
    url: str,
    ready: bool,
    confirmed: bool,
) -> dict[str, str]:
    detail = (
        f"股票：{_text(ticker, default='尚未選擇')}｜"
        f"類型：{company_filing_type_label(document_type)}｜"
        f"URL：{_text(url, default='尚未填寫')}"
    )
    if not ready:
        return {
            "state": "attention",
            "title": "URL 公司文件尚未完整",
            "detail": detail,
            "next_step": "請先填入文件 URL。",
            "quota_hint": "尚未送出背景任務；確認 URL 可避免失敗重試浪費排隊資源。",
        }
    if not confirmed:
        return {
            "state": "attention",
            "title": "準備送出 URL 公司文件匯入",
            "detail": detail,
            "next_step": "勾選確認後，再按「從 URL 抓取並匯入」送出背景任務。",
            "quota_hint": "背景任務會排隊執行；完成前不要重複送出同一份文件。",
        }
    return {
        "state": "ready",
        "title": "可以送出 URL 公司文件匯入",
        "detail": detail,
        "next_step": "按「從 URL 抓取並匯入」送出背景任務；完成後回報告中心確認最新版。",
        "quota_hint": "背景任務會排隊執行；完成前不要重複送出同一份文件。",
    }


def company_filing_type_label(document_type: str) -> str:
    return COMPANY_FILING_TYPE_LABELS.get(
        str(document_type or "").strip(),
        str(document_type or "").strip(),
    )


def _date_text(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return _text(value)


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
