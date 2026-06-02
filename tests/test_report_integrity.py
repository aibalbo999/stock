import pytest

from app.services.report_models import AllocationItem, AllocationPlan
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


def test_report_integrity_blocks_low_quality_forum_sources() -> None:
    markdown = """
    ## 附錄：AI 補充與資料來源
    ### 資料來源與時間戳記
    - 2026-05-12 CMoney《1815 富喬-追買低檔群創也不要去追高高檔的富喬住套房-股市爆料同學會》
    - 2026-05-20 CMoney《1504 東元 一堆看新聞做股票不是真的分析走勢》
    """

    with pytest.raises(ReportIntegrityError) as exc:
        assert_report_integrity(markdown)

    assert exc.value.issues[0].code == "low_quality_forum_source_in_report"


def test_report_integrity_blocks_investment_blog_sources() -> None:
    markdown = """
    ## 投資理由地圖
    ### 1815 富喬
    - 成長假設：玻纖布需求升溫；代表性來源：2026-05-08 CMoney投資網誌《富喬還能追嗎》。
    """

    with pytest.raises(ReportIntegrityError) as exc:
        assert_report_integrity(markdown)

    assert exc.value.issues[0].code == "non_formal_source_in_report"


def test_report_integrity_blocks_nanya_tech_source_inside_nanya_section() -> None:
    markdown = """
    ## 投資理由地圖
    ### 1303 南亞
    - 成長假設：電子材料需求回升；代表性來源：2026-05-20 測試新聞《南亞科記憶體供給吃緊》。
    """

    with pytest.raises(ReportIntegrityError) as exc:
        assert_report_integrity(markdown)

    assert exc.value.issues[0].code == "confusing_entity_in_company_section"


def test_report_integrity_blocks_allocation_total_and_missing_research_candidate() -> None:
    markdown = """
    ## 一頁摘要
    | 項目 | 結果 |
    |---|---|
    | 可小額研究 | 4 檔 |

    ## 下一步
    ### 可立即研究
    - 2308 台達電：可看資金控管建議中的首筆配置；目前情境升值分 46 分，目前情境降值分 11 分。
    - 4583 大銀微系統：可看資金控管建議中的首筆配置；目前情境升值分 24 分，目前情境降值分 8 分。
    - 2359 所羅門：可看資金控管建議中的首筆配置；目前情境升值分 27 分，目前情境降值分 7 分。
    - 1504 東元：可看資金控管建議中的首筆配置；目前情境升值分 30 分，目前情境降值分 0 分。

    ## 資金控管建議
    ### 首筆配置草案
    本輪首筆配置合計約 180,000 元；可投入上限 700,000 元。
    - 2308 台達電：首筆配置約 50,000 元；淨分 35。
    - 4583 大銀微系統：首筆配置約 40,000 元；淨分 16。
    - 2359 所羅門：首筆配置約 40,000 元；淨分 20。

    ### 可小額分批研究
    - 2308 台達電：可列小額分批研究。首筆約 50,000 元。
    - 4583 大銀微系統：可列小額分批研究。首筆約 40,000 元。
    - 2359 所羅門：可列小額分批研究。首筆約 40,000 元。
    - 1504 東元：可列小額分批研究。首筆約 50,000 元。
    """

    audit = audit_report_integrity(markdown)
    codes = {issue["code"] for issue in audit["blockers"]}

    assert "allocation_total_mismatch" in codes
    assert "allocation_count_mismatch" in codes
    assert "allocation_missing_research_candidate" in codes


def test_allocation_plan_validates_declared_total_before_markdown() -> None:
    with pytest.raises(ValueError):
        AllocationPlan(
            declared_total=90_000,
            deployable=100_000,
            first_tranche=50_000,
            items=[
                AllocationItem(label="2330 台積電", amount=50_000),
                AllocationItem(label="2382 廣達", amount=40_000),
                AllocationItem(label="3324 雙鴻", amount=20_000),
            ],
        )
