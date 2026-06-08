from __future__ import annotations

from app.services import topic_discovery_news_queries
from app.services.topic_discovery_models import CandidateCompany

SUPPLEMENTAL_HYPOTHESIS = "補強弱證據候選與低覆蓋子題，重新驗證是否可進入正式分析。"


def candidate_query_items(candidate: CandidateCompany, include_international: bool = True) -> list[dict]:
    keywords = " ".join(candidate.evidence_keywords[:3])
    candidate_hypothesis = f"驗證 {candidate.ticker} {candidate.name} 是否與「{candidate.segment}」及主題證據直接相關。"
    items = [
        topic_discovery_news_queries.query_item(
            f"{candidate.ticker} {candidate.name} {candidate.segment} {keywords}".strip(),
            "candidate",
            candidate_hypothesis,
            "候選公司證據",
            "industry_news",
        ),
        topic_discovery_news_queries.query_item(
            f"{candidate.ticker} {candidate.name} 法說會 年報 月營收".strip(),
            "candidate",
            candidate_hypothesis,
            "公司公開資訊",
            "company_disclosure",
        ),
        topic_discovery_news_queries.query_item(
            f"{candidate.name} {candidate.segment} 訂單 營收 出貨".strip(),
            "candidate",
            candidate_hypothesis,
            "財務/營收",
            "financial_metrics",
        ),
        topic_discovery_news_queries.query_item(
            f"{candidate.ticker} {candidate.name} 公開資訊觀測站 法人說明會".strip(),
            "candidate",
            candidate_hypothesis,
            "公司公開資訊",
            "company_disclosure",
        ),
    ]
    if include_international:
        items.extend(
            [
                topic_discovery_news_queries.query_item(
                    f"{candidate.name} {candidate.ticker} Taiwan supplier {keywords}".strip(),
                    "candidate_international",
                    candidate_hypothesis,
                    "國際供應鏈證據",
                    "international_context",
                ),
                topic_discovery_news_queries.query_item(
                    f"{candidate.segment} {keywords} global supply chain Taiwan listed company".strip(),
                    "candidate_international",
                    candidate_hypothesis,
                    "國際供應鏈證據",
                    "international_context",
                ),
            ]
        )
    return topic_discovery_news_queries.dedupe_query_items(items)


def supplemental_candidate_query_items(
    candidate: CandidateCompany,
    include_international: bool = True,
) -> list[dict]:
    return [
        {
            **item,
            "source_type": "supplemental",
            "hypothesis": SUPPLEMENTAL_HYPOTHESIS,
            "evidence_type": "補抓資料源",
        }
        for item in candidate_query_items(
            candidate,
            include_international=include_international,
        )
    ]


def round_robin_query_groups(groups: list[list[dict]]) -> list[dict]:
    items: list[dict] = []
    max_depth = max((len(group) for group in groups), default=0)
    for index in range(max_depth):
        for group in groups:
            if index < len(group):
                items.append(group[index])
    return topic_discovery_news_queries.dedupe_query_items(items)
