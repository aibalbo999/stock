from datetime import date
from pathlib import Path

from app.data_sources.news import NewsFetcher, NewsSourceStore


def test_parse_rss_feed() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>CoWoS 產能滿載</title>
          <link>https://example.com/news/1</link>
          <description><![CDATA[<p>台積電 CoWoS 產能滿載。</p>]]></description>
          <pubDate>Wed, 20 May 2026 10:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """

    documents = NewsFetcher().parse_feed(xml, "https://example.com/rss", "測試 RSS")

    assert len(documents) == 1
    assert documents[0].title == "CoWoS 產能滿載"
    assert documents[0].text == "台積電 CoWoS 產能滿載。"
    assert documents[0].source.published_at == date(2026, 5, 20)
    assert documents[0].source.publisher == "測試 RSS"


def test_parse_atom_feed() -> None:
    xml = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>HBM 供給不足</title>
        <link href="https://example.com/news/2" />
        <summary>HBM 供給不足使 AI 伺服器交期延長。</summary>
        <updated>2026-05-21T09:00:00Z</updated>
      </entry>
    </feed>
    """

    documents = NewsFetcher().parse_feed(xml, "https://example.com/atom", "測試 Atom")

    assert documents[0].title == "HBM 供給不足"
    assert documents[0].source.url == "https://example.com/news/2"
    assert documents[0].source.published_at == date(2026, 5, 21)


def test_news_source_store_loads_enabled_sources(tmp_path) -> None:
    path = tmp_path / "sources.json"
    path.write_text(
        """
        {
          "sources": [
            {"name": "on", "url": "https://example.com/rss", "enabled": true, "category": "cloud_capex"},
            {"name": "off", "url": "https://example.com/off", "enabled": false}
          ]
        }
        """,
        encoding="utf-8",
    )

    store = NewsSourceStore(path)

    assert [source.name for source in store.enabled_sources()] == ["on"]
    assert store.enabled_sources()[0].category == "cloud_capex"
    assert store.load()[1].category == "news"


def test_news_source_store_filters_topic_specific_sources(tmp_path) -> None:
    path = tmp_path / "sources.json"
    path.write_text(
        """
        {
          "sources": [
            {"name": "base", "url": "https://example.com/base", "enabled": true, "scope": "universal"},
            {"name": "ai", "url": "https://example.com/ai", "enabled": true, "scope": "topic", "topics": ["AI", "人工智慧"]},
            {"name": "ev", "url": "https://example.com/ev", "enabled": true, "scope": "topic", "topics": ["電動車"]},
            {"name": "off", "url": "https://example.com/off", "enabled": false, "scope": "universal"}
          ]
        }
        """,
        encoding="utf-8",
    )

    store = NewsSourceStore(path)

    assert [source.name for source in store.sources_for_topic("AI 產業鏈")] == ["ai", "base"]
    assert [source.name for source in store.sources_for_topic("電動車供應鏈")] == ["ev", "base"]
    assert [source.name for source in store.sources_for_topic("航運景氣循環")] == ["base"]
    assert [source.name for source in store.sources_for_topic("航運景氣循環 industry_news")] == ["base"]
    selection = store.selection_for_topic("AI 產業鏈")
    assert selection["selected"][0]["name"] == "ai"
    assert selection["selected"][0]["match_terms"] == ["AI"]
    assert any(item["name"] == "ev" and item["reason"] == "topic_not_matched" for item in selection["skipped"])


def test_default_news_sources_have_research_categories_and_unique_urls() -> None:
    sources = NewsSourceStore(Path("data/news_sources.json")).load()
    names = [source.name for source in sources]
    urls = [source.url for source in sources]
    categories = {source.category for source in sources}

    assert len(sources) >= 31
    assert len(names) == len(set(names))
    assert len(urls) == len(set(urls))
    assert all(source.category for source in sources)
    assert all(source.scope in {"universal", "topic"} for source in sources)
    assert all(source.source_intents for source in sources)
    assert any(source.scope == "universal" for source in sources)
    assert any(source.scope == "topic" and "AI" in source.topics for source in sources)
    assert {
        "taiwan_news",
        "ai_chip_vendor",
        "cloud_capex",
        "datacenter_power",
        "advanced_packaging",
        "server_odm",
        "server_infrastructure",
        "thermal_liquid_cooling",
        "policy_export_controls",
        "semiconductor_industry",
    }.issubset(categories)
