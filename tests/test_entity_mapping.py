from app.services.entity_mapping import EntityMapper


def test_mapper_only_matches_whitelisted_companies() -> None:
    mapper = EntityMapper()

    matches = mapper.match_text("台積電 CoWoS 產能滿載，廣達 AI 伺服器拉貨；某某科技也受惠。")

    assert {(match.ticker, match.name) for match in matches} == {("2330", "台積電"), ("2382", "廣達")}


def test_filter_allowed_tickers_removes_non_whitelist() -> None:
    mapper = EntityMapper()

    assert mapper.filter_allowed_tickers(["2330", "9999", "3324"]) == ["2330", "3324"]
