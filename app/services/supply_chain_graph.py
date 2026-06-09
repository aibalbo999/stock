from __future__ import annotations

from app.models.schemas import Company, SupplyChainSegment
from app.services.supply_chain_graph_models import (
    CATEGORY_SPECS,
    DOWNSTREAM_CATEGORIES,
    GraphRetrievalHint,
    GraphRetrievalQuery,
    SegmentCategory as SegmentCategory,
    SupplyChainEdge,
    SupplyChainNode,
    category_label as _category_label,
    compact_search_terms as _compact_search_terms,
    direction_evidence_terms as _direction_evidence_terms,
    direction_priority as _direction_priority,
)
from app.services.supply_chain_graph_reasoning import SupplyChainGraphReasoningMixin


class SupplyChainGraph(SupplyChainGraphReasoningMixin):
    def __init__(self, segments: list[SupplyChainSegment]) -> None:
        self.segments = segments
        self.nodes = self._build_nodes(segments)
        self.edges = self._build_edges(segments, self.nodes)

    def to_dict(self) -> dict:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "note": (
                "GraphRAG edges are structural supply-chain hypotheses from segment taxonomy; "
                "they require company-level evidence before being used as investment reasons."
            ),
        }

    def neo4j_import_payload(self, tickers: list[str] | None = None) -> dict:
        requested = {ticker for ticker in tickers or [] if ticker}
        edges = self._focused_edges(requested)
        nodes = self._focused_nodes(requested, edges)
        structural_edges = [
            edge.to_dict() for edge in edges if edge.relation == "structural_upstream_to"
        ]
        peer_edges = [edge.to_dict() for edge in edges if edge.relation == "same_segment_peer"]
        return {
            "format": "neo4j_cypher_v1",
            "parameters": {
                "nodes": [node.to_dict() for node in nodes],
                "structural_edges": structural_edges,
                "peer_edges": peer_edges,
            },
            "statements": self._neo4j_statements(),
            "query_examples": {
                "upstream_suppliers": (
                    "MATCH (supplier:Company)-[r:STRUCTURAL_UPSTREAM_TO]->"
                    "(target:Company {ticker: $ticker}) "
                    "RETURN supplier, r, target ORDER BY supplier.ticker"
                ),
                "downstream_demand": (
                    "MATCH (source:Company {ticker: $ticker})-[r:STRUCTURAL_UPSTREAM_TO]->"
                    "(customer:Company) "
                    "RETURN source, r, customer ORDER BY customer.ticker"
                ),
                "same_segment_peers": (
                    "MATCH (company:Company {ticker: $ticker})-[r:SAME_SEGMENT_PEER]-(peer:Company) "
                    "RETURN company, r, peer ORDER BY peer.ticker"
                ),
                "shortest_path_between_companies": (
                    "MATCH path = shortestPath("
                    "(source:Company {ticker: $source_ticker})-[*..4]-"
                    "(target:Company {ticker: $target_ticker})"
                    ") RETURN path"
                ),
            },
            "note": (
                "Import these GraphRAG edges as retrieval context only. "
                "STRUCTURAL_UPSTREAM_TO means taxonomy-based upstream/downstream hypothesis; "
                "it is not proof of a direct supplier contract."
            ),
        }

    def neighbor_edges(self, ticker: str) -> list[SupplyChainEdge]:
        return [
            edge
            for edge in self.edges
            if edge.source_ticker == ticker or edge.target_ticker == ticker
        ]

    def retrieval_hints(self, ticker: str, max_neighbors: int = 4) -> list[GraphRetrievalHint]:
        node_by_ticker = {node.ticker: node for node in self.nodes}
        hints: list[GraphRetrievalHint] = []
        for edge in self.neighbor_edges(ticker):
            neighbor_ticker = (
                edge.target_ticker if edge.source_ticker == ticker else edge.source_ticker
            )
            neighbor = node_by_ticker.get(neighbor_ticker)
            if neighbor is None:
                continue
            direction, label = self._edge_direction_label(edge, ticker)
            hints.append(
                GraphRetrievalHint(
                    ticker=neighbor.ticker,
                    name=neighbor.name,
                    segment_name=neighbor.segment_name,
                    relation=edge.relation,
                    direction=direction,
                    relation_label=label,
                    confidence=edge.confidence,
                    evidence_keywords=neighbor.evidence_keywords,
                )
            )
        hints.sort(key=lambda hint: (_direction_priority(hint.direction), hint.ticker, hint.name))
        return hints[:max_neighbors]

    def retrieval_queries(
        self,
        ticker: str,
        topic: str = "",
        max_neighbors: int = 4,
    ) -> list[GraphRetrievalQuery]:
        node_by_ticker = {node.ticker: node for node in self.nodes}
        node = node_by_ticker.get(ticker)
        if node is None:
            return []

        hints = self.retrieval_hints(ticker, max_neighbors=max_neighbors)
        related_tickers = tuple(dict.fromkeys(hint.ticker for hint in hints if hint.ticker))
        related_names = tuple(dict.fromkeys(hint.name for hint in hints if hint.name))
        neighbor_terms = _compact_search_terms(
            [term for hint in hints for term in hint.search_terms()],
            max_terms=max_neighbors * 7,
        )
        queries = [
            GraphRetrievalQuery(
                ticker=node.ticker,
                name=node.name,
                query=" ".join(
                    _compact_search_terms(
                        [
                            topic,
                            node.ticker,
                            node.name,
                            node.segment_name,
                            *node.evidence_keywords,
                            "供應鏈",
                            "上下游",
                            *neighbor_terms,
                        ],
                        max_terms=22,
                    )
                ),
                query_type="company_graph_neighborhood",
                relation_scope="upstream_downstream_peer",
                related_tickers=related_tickers,
                related_names=related_names,
            ),
            GraphRetrievalQuery(
                ticker=node.ticker,
                name=node.name,
                query=" ".join(
                    _compact_search_terms(
                        [
                            topic,
                            node.segment_name,
                            *node.evidence_keywords[:4],
                            "同業",
                            "財報",
                            "月營收",
                        ],
                        max_terms=12,
                    )
                ),
                query_type="segment_fundamental_check",
                relation_scope="same_segment",
                related_tickers=related_tickers,
                related_names=related_names,
            ),
        ]
        for hint in hints[:2]:
            queries.append(
                GraphRetrievalQuery(
                    ticker=node.ticker,
                    name=node.name,
                    query=" ".join(
                        _compact_search_terms(
                            [
                                topic,
                                node.ticker,
                                node.name,
                                hint.relation_label,
                                hint.ticker,
                                hint.name,
                                hint.segment_name,
                                *_direction_evidence_terms(hint.direction),
                                *hint.evidence_keywords[:2],
                            ],
                            max_terms=16,
                        )
                    ),
                    query_type="relation_confirmation",
                    relation_scope=hint.direction,
                    related_tickers=(hint.ticker,),
                    related_names=(hint.name,),
                )
            )
        return [query for query in queries if query.query]

    def retrieval_plan(
        self,
        tickers: list[str] | None = None,
        topic: str = "",
        max_queries_per_ticker: int = 4,
    ) -> dict:
        requested = [ticker for ticker in tickers or [] if ticker]
        if not requested:
            requested = [node.ticker for node in self.nodes[:6]]
        queries_by_ticker = {
            ticker: [
                query.to_dict()
                for query in self.retrieval_queries(ticker, topic=topic)[:max_queries_per_ticker]
            ]
            for ticker in requested
        }
        return {
            "strategy": "taxonomy_graph_query_expansion",
            "evidence_policy": (
                "GraphRAG queries expand retrieval with upstream/downstream/peer context; "
                "graph edges are not accepted as investment evidence unless corroborated "
                "by company-level documents, news, revenue, or financial metrics."
            ),
            "tickers": requested,
            "queries_by_ticker": queries_by_ticker,
        }

    def render_prompt_context(self, tickers: list[str] | None = None, max_edges: int = 18) -> str:
        requested = {ticker for ticker in tickers or [] if ticker}
        edges = [
            edge
            for edge in self.edges
            if not requested or edge.source_ticker in requested or edge.target_ticker in requested
        ][:max_edges]
        if not edges:
            return (
                "### 產業鏈關係圖譜（GraphRAG）\n"
                "- 目前沒有足夠結構化上下游關係可輔助檢索；不得只憑概念題材推論供應關係。"
            )
        node_by_ticker = {node.ticker: node for node in self.nodes}
        lines = [
            "### 產業鏈關係圖譜（GraphRAG）",
            "- 下列關係是依產業鏈分工建立的結構性假設，只能用來輔助檢索與檢查上下游脈絡；正式投資理由仍必須回到新聞、公司文件、月營收或財報證據。",
        ]
        for edge in edges:
            source = node_by_ticker.get(edge.source_ticker)
            target = node_by_ticker.get(edge.target_ticker)
            if source is None or target is None:
                continue
            lines.append(
                "- "
                f"{source.ticker} {source.name}（{edge.source_segment}） -> "
                f"{target.ticker} {target.name}（{edge.target_segment}）："
                f"{edge.rationale}"
            )
        return "\n".join(lines)

    def _focused_edges(self, requested: set[str]) -> list[SupplyChainEdge]:
        if not requested:
            return list(self.edges)
        return [
            edge
            for edge in self.edges
            if edge.source_ticker in requested or edge.target_ticker in requested
        ]

    def _focused_nodes(
        self,
        requested: set[str],
        edges: list[SupplyChainEdge],
    ) -> list[SupplyChainNode]:
        if not requested:
            return list(self.nodes)
        related = set(requested)
        for edge in edges:
            related.add(edge.source_ticker)
            related.add(edge.target_ticker)
        return [node for node in self.nodes if node.ticker in related]

    @classmethod
    def from_whitelist(cls, whitelist) -> "SupplyChainGraph":
        return cls(list(whitelist.segments))

    @staticmethod
    def _neo4j_statements() -> list[str]:
        return [
            "CREATE CONSTRAINT company_ticker IF NOT EXISTS "
            "FOR (company:Company) REQUIRE company.ticker IS UNIQUE",
            "CREATE CONSTRAINT segment_id IF NOT EXISTS "
            "FOR (segment:SupplyChainSegment) REQUIRE segment.id IS UNIQUE",
            (
                "UNWIND $nodes AS node "
                "MERGE (company:Company {ticker: node.ticker}) "
                "SET company.name = node.name, "
                "company.category = node.category, "
                "company.evidence_keywords = node.evidence_keywords "
                "MERGE (segment:SupplyChainSegment {id: node.segment_id}) "
                "SET segment.name = node.segment_name, segment.category = node.category "
                "MERGE (company)-[:BELONGS_TO_SEGMENT]->(segment)"
            ),
            (
                "UNWIND $structural_edges AS edge "
                "MATCH (source:Company {ticker: edge.source_ticker}) "
                "MATCH (target:Company {ticker: edge.target_ticker}) "
                "MERGE (source)-[relation:STRUCTURAL_UPSTREAM_TO]->(target) "
                "SET relation.source_segment = edge.source_segment, "
                "relation.target_segment = edge.target_segment, "
                "relation.confidence = edge.confidence, "
                "relation.rationale = edge.rationale"
            ),
            (
                "UNWIND $peer_edges AS edge "
                "MATCH (source:Company {ticker: edge.source_ticker}) "
                "MATCH (target:Company {ticker: edge.target_ticker}) "
                "MERGE (source)-[relation:SAME_SEGMENT_PEER]->(target) "
                "SET relation.source_segment = edge.source_segment, "
                "relation.target_segment = edge.target_segment, "
                "relation.confidence = edge.confidence, "
                "relation.rationale = edge.rationale"
            ),
        ]

    @staticmethod
    def _edge_direction_label(edge: SupplyChainEdge, ticker: str) -> tuple[str, str]:
        if edge.relation == "same_segment_peer":
            return "peer", "同業比較"
        if edge.relation == "structural_upstream_to":
            if edge.target_ticker == ticker:
                return "upstream", "上游供應鏈"
            if edge.source_ticker == ticker:
                return "downstream", "下游需求端"
        return "related", "產業鏈相關"

    @staticmethod
    def classify_segment(segment: SupplyChainSegment) -> str:
        haystack = " ".join(
            [
                segment.id,
                segment.name,
                segment.notes or "",
                *[
                    " ".join([company.name, *company.aliases, *company.evidence_keywords])
                    for company in segment.companies
                ],
            ]
        ).lower()
        for category in CATEGORY_SPECS:
            if any(keyword.lower() in haystack for keyword in category.keywords):
                return category.id
        return "other"

    @staticmethod
    def _build_nodes(segments: list[SupplyChainSegment]) -> list[SupplyChainNode]:
        nodes = []
        for segment in segments:
            category = SupplyChainGraph.classify_segment(segment)
            for company in segment.companies:
                nodes.append(SupplyChainGraph._node_from_company(company, segment, category))
        return nodes

    @staticmethod
    def _node_from_company(
        company: Company,
        segment: SupplyChainSegment,
        category: str,
    ) -> SupplyChainNode:
        return SupplyChainNode(
            ticker=company.ticker,
            name=company.name,
            segment_id=segment.id,
            segment_name=segment.name,
            category=category,
            evidence_keywords=tuple(company.evidence_keywords),
        )

    @staticmethod
    def _build_edges(
        segments: list[SupplyChainSegment],
        nodes: list[SupplyChainNode],
    ) -> list[SupplyChainEdge]:
        nodes_by_segment = {}
        for node in nodes:
            nodes_by_segment.setdefault(node.segment_id, []).append(node)
        segment_categories = {
            segment.id: SupplyChainGraph.classify_segment(segment) for segment in segments
        }
        edges: list[SupplyChainEdge] = []
        seen = set()
        for source_segment in segments:
            source_category = segment_categories.get(source_segment.id, "other")
            for target_segment in segments:
                if source_segment.id == target_segment.id:
                    edges.extend(
                        SupplyChainGraph._peer_edges(
                            nodes_by_segment.get(source_segment.id, []),
                            seen,
                        )
                    )
                    continue
                target_category = segment_categories.get(target_segment.id, "other")
                if target_category not in DOWNSTREAM_CATEGORIES.get(source_category, ()):
                    continue
                for source in nodes_by_segment.get(source_segment.id, []):
                    for target in nodes_by_segment.get(target_segment.id, []):
                        key = (source.ticker, target.ticker, "structural_upstream_to")
                        if source.ticker == target.ticker or key in seen:
                            continue
                        seen.add(key)
                        edges.append(
                            SupplyChainEdge(
                                source_ticker=source.ticker,
                                target_ticker=target.ticker,
                                relation="structural_upstream_to",
                                source_segment=source.segment_name,
                                target_segment=target.segment_name,
                                confidence="taxonomy",
                                rationale=(
                                    f"{_category_label(source_category)}通常位於"
                                    f"{_category_label(target_category)}上游或支援環節。"
                                ),
                            )
                        )
        return sorted(
            edges, key=lambda edge: (edge.source_ticker, edge.target_ticker, edge.relation)
        )

    @staticmethod
    def _peer_edges(
        nodes: list[SupplyChainNode], seen: set[tuple[str, str, str]]
    ) -> list[SupplyChainEdge]:
        edges = []
        for index, source in enumerate(nodes):
            for target in nodes[index + 1 :]:
                key = (source.ticker, target.ticker, "same_segment_peer")
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    SupplyChainEdge(
                        source_ticker=source.ticker,
                        target_ticker=target.ticker,
                        relation="same_segment_peer",
                        source_segment=source.segment_name,
                        target_segment=target.segment_name,
                        confidence="taxonomy",
                        rationale="同屬一個產業鏈分工段，適合做同業比較，不代表互為供應商。",
                    )
                )
        return edges
