from __future__ import annotations

from collections import deque

from app.services.supply_chain_graph_models import (
    SupplyChainEdge,
    SupplyChainNode,
    direction_priority as _direction_priority,
)


class SupplyChainGraphReasoningMixin:
    def reasoning_plan(
        self,
        tickers: list[str] | None = None,
        *,
        target_ticker: str = "",
        topic: str = "",
        max_depth: int = 3,
        max_paths: int = 8,
    ) -> dict:
        requested = [ticker for ticker in tickers or [] if ticker]
        if not requested:
            requested = [node.ticker for node in self.nodes[:3]]
        depth = max(1, min(int(max_depth), 6))
        path_limit = max(1, min(int(max_paths), 20))
        target = str(target_ticker or "").strip()
        paths_by_ticker = {
            ticker: (
                self.shortest_paths(ticker, target, max_depth=depth, max_paths=path_limit)
                if target
                else self.neighborhood_paths(ticker, max_depth=depth, max_paths=path_limit)
            )
            for ticker in requested
        }
        return {
            "strategy": "taxonomy_graph_shortest_path_reasoning",
            "topic": topic,
            "tickers": requested,
            "target_ticker": target or None,
            "max_depth": depth,
            "max_paths": path_limit,
            "paths_by_ticker": paths_by_ticker,
            "context": self.render_reasoning_context(paths_by_ticker, topic=topic),
            "cypher_templates": self._shortest_path_cypher_templates(depth),
            "evidence_policy": (
                "Shortest paths are graph-derived structural hypotheses for LLM context. "
                "They must be corroborated by company filings, news, revenue, or financial metrics "
                "before being used as investment evidence."
            ),
        }

    def shortest_paths(
        self,
        source_ticker: str,
        target_ticker: str,
        *,
        max_depth: int = 3,
        max_paths: int = 5,
    ) -> list[dict]:
        source = str(source_ticker or "").strip()
        target = str(target_ticker or "").strip()
        if not source or not target or source == target:
            return []
        node_by_ticker = self._node_by_ticker()
        if source not in node_by_ticker or target not in node_by_ticker:
            return []
        return self._bfs_paths(
            source,
            target,
            max_depth=max(1, min(int(max_depth), 6)),
            max_paths=max(1, min(int(max_paths), 20)),
        )

    def neighborhood_paths(
        self,
        source_ticker: str,
        *,
        max_depth: int = 2,
        max_paths: int = 8,
    ) -> list[dict]:
        source = str(source_ticker or "").strip()
        if source not in self._node_by_ticker():
            return []
        return self._bfs_paths(
            source,
            "",
            max_depth=max(1, min(int(max_depth), 4)),
            max_paths=max(1, min(int(max_paths), 20)),
        )

    def render_reasoning_context(
        self, paths_by_ticker: dict[str, list[dict]], topic: str = ""
    ) -> str:
        lines = [
            "### GraphRAG 路徑推理",
            "- 下列 shortest-path 結果來自產業鏈 taxonomy graph，只能作為 LLM 分析上下游衝擊與同業傳導的 context；正式結論仍需外部證據確認。",
        ]
        if topic:
            lines.append(f"- 分析主題：{topic}")
        any_path = False
        for ticker, paths in paths_by_ticker.items():
            if not paths:
                lines.append(f"- {ticker}：目前沒有找到可用圖路徑。")
                continue
            for path in paths[:6]:
                any_path = True
                lines.append(
                    "- "
                    f"{path['path_label']}：{path['impact_direction_label']}；"
                    f"{path['evidence_policy']}"
                )
        if not any_path:
            lines.append("- 沒有可用 shortest-path context。")
        return "\n".join(lines)

    def _bfs_paths(
        self,
        source: str,
        target: str,
        *,
        max_depth: int,
        max_paths: int,
    ) -> list[dict]:
        adjacency = self._adjacency()
        queue = deque([(source, [], {source})])
        paths: list[dict] = []
        shortest_hop_count: int | None = None
        reached_targets: set[str] = set()
        while queue and len(paths) < max_paths:
            current, path_edges, visited = queue.popleft()
            if path_edges:
                if target:
                    if current == target:
                        hop_count = len(path_edges)
                        if shortest_hop_count is None:
                            shortest_hop_count = hop_count
                        if hop_count == shortest_hop_count:
                            paths.append(self._path_payload(source, path_edges))
                        continue
                elif current != source and current not in reached_targets:
                    reached_targets.add(current)
                    paths.append(self._path_payload(source, path_edges))
                    if len(paths) >= max_paths:
                        break
            if len(path_edges) >= max_depth:
                continue
            if shortest_hop_count is not None and len(path_edges) >= shortest_hop_count:
                continue
            for neighbor, edge in adjacency.get(current, []):
                if neighbor in visited:
                    continue
                queue.append(
                    (neighbor, [*path_edges, (current, neighbor, edge)], visited | {neighbor})
                )
        return paths

    def _path_payload(
        self, source: str, path_edges: list[tuple[str, str, SupplyChainEdge]]
    ) -> dict:
        node_by_ticker = self._node_by_ticker()
        tickers = [source, *[to_ticker for _from_ticker, to_ticker, _edge in path_edges]]
        nodes = [node_by_ticker[ticker].to_dict() for ticker in tickers if ticker in node_by_ticker]
        edge_payloads = []
        directions = []
        for from_ticker, to_ticker, edge in path_edges:
            direction, relation_label = self._edge_direction_label(edge, from_ticker)
            directions.append(direction)
            edge_payloads.append(
                {
                    **edge.to_dict(),
                    "from_ticker": from_ticker,
                    "to_ticker": to_ticker,
                    "direction_from_previous": direction,
                    "relation_label": relation_label,
                }
            )
        impact_direction = self._impact_direction(directions)
        return {
            "source_ticker": source,
            "target_ticker": tickers[-1] if tickers else "",
            "hop_count": len(path_edges),
            "path_tickers": tickers,
            "path_label": " -> ".join(
                f"{ticker} {node_by_ticker[ticker].name}" if ticker in node_by_ticker else ticker
                for ticker in tickers
            ),
            "impact_direction": impact_direction,
            "impact_direction_label": self._impact_direction_label(impact_direction),
            "nodes": nodes,
            "edges": edge_payloads,
            "evidence_policy": "graph_path_requires_source_confirmation",
        }

    def _adjacency(self) -> dict[str, list[tuple[str, SupplyChainEdge]]]:
        adjacency: dict[str, list[tuple[str, SupplyChainEdge]]] = {}
        for edge in self.edges:
            adjacency.setdefault(edge.source_ticker, []).append((edge.target_ticker, edge))
            adjacency.setdefault(edge.target_ticker, []).append((edge.source_ticker, edge))
        for neighbors in adjacency.values():
            neighbors.sort(
                key=lambda item: (
                    _direction_priority(self._edge_direction_label(item[1], item[0])[0]),
                    item[0],
                    item[1].relation,
                )
            )
        return adjacency

    def _node_by_ticker(self) -> dict[str, SupplyChainNode]:
        return {node.ticker: node for node in self.nodes}

    @staticmethod
    def _impact_direction(directions: list[str]) -> str:
        unique = set(directions)
        if unique == {"upstream"}:
            return "upstream_impact_path"
        if unique == {"downstream"}:
            return "downstream_demand_path"
        if unique == {"peer"}:
            return "peer_comparison_path"
        if "peer" in unique:
            return "peer_cross_segment_path"
        return "mixed_supply_chain_path"

    @staticmethod
    def _impact_direction_label(impact_direction: str) -> str:
        return {
            "upstream_impact_path": "往上游追溯供應/成本風險",
            "downstream_demand_path": "往下游追蹤需求/出貨傳導",
            "peer_comparison_path": "同業比較路徑",
            "peer_cross_segment_path": "同業與上下游混合路徑",
            "mixed_supply_chain_path": "混合上下游路徑",
        }.get(impact_direction, "產業鏈關聯路徑")

    @staticmethod
    def _shortest_path_cypher_templates(max_depth: int) -> dict:
        depth = max(1, min(int(max_depth), 6))
        return {
            "shortest_path_between_companies": (
                "MATCH path = shortestPath("
                "(source:Company {ticker: $source_ticker})-[*.."
                f"{depth}"
                "]-(target:Company {ticker: $target_ticker})"
                ") RETURN path"
            ),
            "neighborhood_paths": (
                "MATCH path = (source:Company {ticker: $source_ticker})-[*1.."
                f"{depth}"
                "]-(target:Company) RETURN path LIMIT $limit"
            ),
            "relationship_types": ["STRUCTURAL_UPSTREAM_TO", "SAME_SEGMENT_PEER"],
            "parameters": {
                "source_ticker": "3324",
                "target_ticker": "2382",
                "limit": 8,
            },
        }


__all__ = ["SupplyChainGraphReasoningMixin"]
