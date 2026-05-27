from datetime import date

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
