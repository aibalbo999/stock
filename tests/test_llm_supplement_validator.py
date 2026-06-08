from datetime import date

from app.data_sources.news import NewsFetcher
from app.models.schemas import MarketSnapshot
from app.services.entity_mapping import EntityMapper
from app.services.llm_analysis import LLMSupplementValidator
from app.services.whitelist import SupplyChainWhitelist


def test_llm_supplement_requires_source_timestamp() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    assert (
        LLMSupplementValidator.render_markdown("沒有來源的補充分析", [document])
        == "LLM 補充分析未通過來源檢查；目前無足夠數據判斷。"
    )


def test_llm_supplement_accepts_timestamped_source() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )

    text = """
    {
      "items": [
        {
          "claim": "瓶頸在 CoWoS。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "CoWoS 產能滿載影響 AI 伺服器交期",
          "source_id": ""
        }
      ]
    }
    """

    assert LLMSupplementValidator.render_markdown(text, [document]) == (
        "- 瓶頸在 CoWoS。 來源：2026-05-20 測試新聞 CoWoS 產能滿載影響 AI 伺服器交期"
    )


def test_llm_supplement_accepts_fuzzy_news_source_title() -> None:
    document = NewsFetcher.from_manual_text(
        title="CoWoS 產能滿載影響 AI 伺服器交期",
        text="台積電 CoWoS 產能滿載。",
        publisher="測試新聞股份有限公司",
        published_at=date(2026, 5, 20),
    )
    text = """
    {
      "items": [
        {
          "claim": "瓶頸仍集中在 CoWoS。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "CoWoS產能滿載影響交期",
          "source_id": ""
        }
      ]
    }
    """

    assert LLMSupplementValidator.render_markdown(text, [document]) == (
        "- 瓶頸仍集中在 CoWoS。 來源：2026-05-20 測試新聞 CoWoS產能滿載影響交期"
    )


def test_llm_supplement_accepts_market_source() -> None:
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 22),
        close=2255.0,
        source="FinMind TaiwanStockPrice",
    )
    text = """
    {
      "items": [
        {
          "claim": "2330 收盤價為 2255.0。",
          "source_type": "market",
          "source_date": "2026-05-22",
          "source_publisher": "FinMind TaiwanStockPrice",
          "source_title": "",
          "source_id": "2330"
        }
      ]
    }
    """

    assert LLMSupplementValidator.render_markdown(text, [], [snapshot]) == (
        "- 2330 收盤價為 2255.0。 來源：2026-05-22 FinMind TaiwanStockPrice 2330"
    )


def test_llm_supplement_rejects_news_claim_when_source_maps_to_another_company() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與伺服",
                "status": "evidence_supported",
            },
            {
                "ticker": "2301",
                "name": "光寶科",
                "segment": "電源供應器",
                "status": "evidence_supported",
            },
        ]
    )
    mapper = EntityMapper(whitelist)
    document = NewsFetcher.from_manual_text(
        title="光寶科 AI 電源出貨升溫",
        text="光寶科受惠 AI 伺服器電源供應器需求增加。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )
    text = """
    {
      "items": [
        {
          "claim": "台達電 AI 電源出貨升溫。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "光寶科 AI 電源出貨升溫",
          "source_id": "2308"
        }
      ]
    }
    """

    rendered = LLMSupplementValidator.render_markdown(
        text,
        [document],
        news_ticker_resolver=lambda doc: [match.ticker for match in mapper.match_document(doc)],
        claim_ticker_resolver=lambda claim: [match.ticker for match in mapper.match_text(claim)],
    )

    assert rendered == "LLM 補充分析未通過來源檢查；目前無足夠數據判斷。"


def test_llm_supplement_accepts_news_claim_when_source_id_matches_company() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與伺服",
                "status": "evidence_supported",
            }
        ]
    )
    mapper = EntityMapper(whitelist)
    document = NewsFetcher.from_manual_text(
        title="台達電 AI 電源出貨升溫",
        text="台達電受惠 AI 伺服器電源與伺服控制需求增加。",
        publisher="測試新聞",
        published_at=date(2026, 5, 20),
    )
    text = """
    {
      "items": [
        {
          "claim": "台達電 AI 電源出貨升溫。",
          "source_type": "news",
          "source_date": "2026-05-20",
          "source_publisher": "測試新聞",
          "source_title": "台達電 AI 電源出貨升溫",
          "source_id": "2308"
        }
      ]
    }
    """

    rendered = LLMSupplementValidator.render_markdown(
        text,
        [document],
        news_ticker_resolver=lambda doc: [match.ticker for match in mapper.match_document(doc)],
        claim_ticker_resolver=lambda claim: [match.ticker for match in mapper.match_text(claim)],
    )

    assert rendered == "- 台達電 AI 電源出貨升溫。 來源：2026-05-20 測試新聞 台達電 AI 電源出貨升溫"
