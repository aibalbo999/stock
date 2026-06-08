from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SupplyChainNode:
    ticker: str
    name: str
    segment_id: str
    segment_name: str
    category: str
    evidence_keywords: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "segment_id": self.segment_id,
            "segment_name": self.segment_name,
            "category": self.category,
            "evidence_keywords": list(self.evidence_keywords),
        }


@dataclass(frozen=True)
class SupplyChainEdge:
    source_ticker: str
    target_ticker: str
    relation: str
    source_segment: str
    target_segment: str
    confidence: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "source_ticker": self.source_ticker,
            "target_ticker": self.target_ticker,
            "relation": self.relation,
            "source_segment": self.source_segment,
            "target_segment": self.target_segment,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class GraphRetrievalHint:
    ticker: str
    name: str
    segment_name: str
    relation: str
    direction: str
    relation_label: str
    confidence: str
    evidence_keywords: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "segment_name": self.segment_name,
            "relation": self.relation,
            "direction": self.direction,
            "relation_label": self.relation_label,
            "confidence": self.confidence,
            "evidence_keywords": list(self.evidence_keywords),
        }

    def search_terms(self) -> list[str]:
        return [
            self.relation_label,
            self.direction,
            self.ticker,
            self.name,
            self.segment_name,
            *self.evidence_keywords[:2],
        ]


@dataclass(frozen=True)
class GraphRetrievalQuery:
    ticker: str
    name: str
    query: str
    query_type: str
    relation_scope: str
    related_tickers: tuple[str, ...] = ()
    related_names: tuple[str, ...] = ()
    evidence_policy: str = "graph_hint_requires_source_confirmation"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "query": self.query,
            "query_type": self.query_type,
            "relation_scope": self.relation_scope,
            "related_tickers": list(self.related_tickers),
            "related_names": list(self.related_names),
            "evidence_policy": self.evidence_policy,
        }


@dataclass(frozen=True)
class SegmentCategory:
    id: str
    label: str
    keywords: tuple[str, ...]


CATEGORY_SPECS = (
    SegmentCategory("foundry", "晶圓製造", ("晶圓代工", "foundry", "台積電")),
    SegmentCategory(
        "semiconductor_equipment", "半導體設備", ("設備", "先進封裝設備", "半導體設備")
    ),
    SegmentCategory("advanced_packaging", "先進封裝", ("先進封裝", "cowos", "封裝", "封測")),
    SegmentCategory(
        "pcb_substrate", "PCB/載板材料", ("pcb", "abf", "載板", "ccl", "高速板", "銅箔", "玻纖")
    ),
    SegmentCategory("power_thermal", "電源/散熱", ("散熱", "液冷", "水冷", "電源", "cdu")),
    SegmentCategory(
        "server_components", "伺服器零組件/機構件", ("伺服器導軌", "伺服器機構件", "滑軌", "機構件")
    ),
    SegmentCategory(
        "server_odm", "伺服器/系統代工", ("ai 伺服器", "伺服器代工", "伺服器", "資料中心", "機櫃")
    ),
    SegmentCategory("semiconductor_materials", "半導體材料", ("矽晶圓", "半導體材料", "晶圓材料")),
    SegmentCategory(
        "robot_sensing",
        "機器人感測/視覺",
        ("3d 視覺", "3d 感測", "機器視覺", "感測", "鏡頭", "視覺"),
    ),
    SegmentCategory(
        "robot_components",
        "機器人零組件/控制",
        (
            "伺服驅動",
            "伺服馬達",
            "控制器",
            "滑軌",
            "螺桿",
            "減速器",
            "氣動",
            "傳動",
            "定位",
            "工業電腦",
            "機構件",
            "鎂鋁",
        ),
    ),
    SegmentCategory(
        "robot_systems", "機器人/自動化系統", ("協作型機器人", "系統整合", "自動化系統", "機器人")
    ),
    SegmentCategory(
        "materials",
        "基礎材料",
        (
            "材料",
            "矽晶圓",
            "化學",
            "特用氣體",
            "光阻",
            "cmp",
            "工程塑膠",
            "特殊鋼",
            "稀土",
            "磁材",
            "碳纖",
        ),
    ),
    SegmentCategory("chip_design", "晶片/IP", ("算力晶片", "gpu", "晶片設計", "ai 晶片")),
)

DOWNSTREAM_CATEGORIES = {
    "chip_design": ("foundry", "advanced_packaging", "server_odm"),
    "foundry": ("advanced_packaging",),
    "semiconductor_equipment": ("foundry", "advanced_packaging"),
    "advanced_packaging": ("server_odm",),
    "pcb_substrate": ("server_odm",),
    "power_thermal": ("server_odm",),
    "server_components": ("server_odm",),
    "semiconductor_materials": ("foundry", "advanced_packaging"),
    "materials": (
        "foundry",
        "advanced_packaging",
        "pcb_substrate",
        "robot_components",
        "robot_systems",
    ),
    "robot_sensing": ("robot_systems",),
    "robot_components": ("robot_systems",),
}


def category_label(category_id: str) -> str:
    for category in CATEGORY_SPECS:
        if category.id == category_id:
            return category.label
    return "未分類環節"


def direction_priority(direction: str) -> int:
    return {
        "upstream": 0,
        "downstream": 1,
        "peer": 2,
        "related": 3,
    }.get(direction, 9)


def direction_evidence_terms(direction: str) -> tuple[str, ...]:
    if direction == "upstream":
        return ("供應", "採購", "產能", "上游")
    if direction == "downstream":
        return ("客戶", "需求", "出貨", "下游")
    if direction == "peer":
        return ("同業", "競爭", "比較")
    return ("合作", "供應鏈", "關係")


def compact_search_terms(terms, max_terms: int = 18) -> list[str]:
    compacted: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = " ".join(str(term or "").split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        compacted.append(normalized)
        seen.add(key)
        if len(compacted) >= max_terms:
            break
    return compacted


__all__ = [
    "CATEGORY_SPECS",
    "DOWNSTREAM_CATEGORIES",
    "GraphRetrievalHint",
    "GraphRetrievalQuery",
    "SegmentCategory",
    "SupplyChainEdge",
    "SupplyChainNode",
    "category_label",
    "compact_search_terms",
    "direction_evidence_terms",
    "direction_priority",
]
