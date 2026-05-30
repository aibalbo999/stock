import pytest

from app.services.report_integrity import ReportIntegrityError, audit_report_integrity, assert_report_integrity


def test_report_integrity_passes_clean_report() -> None:
    markdown = """
    # 測試報告

    ### 2301 光寶科
    - 風險/機會證據：因應出口管制法律法規之變化，本公司已就營運狀況進行評估。
    """

    audit = audit_report_integrity(markdown)

    assert audit["status"] == "pass"
    assert audit["blockers"] == []


def test_report_integrity_blocks_company_text_owner_mismatch() -> None:
    markdown = """
    ### 2308 台達電
    - 風險/機會證據：光寶為全球次世代 AI 關鍵基礎設施中的領先廠商。
    """

    with pytest.raises(ReportIntegrityError) as exc:
        assert_report_integrity(markdown)

    assert exc.value.issues[0].code == "company_text_owner_mismatch"


def test_report_integrity_allows_owner_phrase_in_owner_section() -> None:
    markdown = """
    ### 2301 光寶科
    - 風險/機會證據：光寶為全球次世代 AI 關鍵基礎設施中的領先廠商。
    """

    assert_report_integrity(markdown)


def test_report_integrity_blocks_positive_capability_as_bottleneck() -> None:
    markdown = """
    ### 2301 光寶科
    - 本次操作結論：瓶頸/限制證據：光寶為全球次世代 AI 關鍵基礎設施中的領先廠商，實機展示液冷系統，助力資料中心建置低能耗基礎設施。
    """

    audit = audit_report_integrity(markdown)

    assert audit["status"] == "fail"
    assert audit["blockers"][0]["code"] == "positive_capability_as_bottleneck"


def test_report_integrity_blocks_loss_making_low_valuation() -> None:
    markdown = """
    ### 4540 盟立
    - 資料信心：高；目前估值位置：目前估值低於同業。
    - 財務檢查：最新淨利率為負 -2.8%；ROE 為負 -0.6%。
    """

    with pytest.raises(ReportIntegrityError) as exc:
        assert_report_integrity(markdown)

    assert exc.value.issues[0].code == "loss_making_company_marked_low_valuation"


def test_report_integrity_does_not_bleed_company_section_into_next_h2() -> None:
    markdown = """
    ### 4540 盟立
    - 財務檢查：最新淨利率為負 -2.8%；ROE 為負 -0.6%。

    ## 二次綜合篩選
    - 2301 光寶科：財務/估值正向加分 4 點（目前估值低於同業）。
    """

    assert_report_integrity(markdown)


def test_report_integrity_blocks_known_temporal_and_financial_smells() -> None:
    markdown = """
    - 過去 5 年財務檢查：2022 至 2026 營收與自由現金流成長。
    - 負債權益比約 0.00 倍。
    """

    audit = audit_report_integrity(markdown)
    codes = {issue["code"] for issue in audit["blockers"]}

    assert "future_full_year_financials" in codes
    assert "suspicious_zero_debt_ratio" in codes
