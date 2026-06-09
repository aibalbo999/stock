from __future__ import annotations

from app.services import (
    topic_discovery_ai_fallback,
    topic_discovery_generic_fallback,
    topic_discovery_memory_fallback,
    topic_discovery_quality,
    topic_discovery_robotics_fallback,
)
from app.services.topic_discovery_models import CandidateCompany, TopicDiscoveryPlan


def fallback_plan(topic: str) -> TopicDiscoveryPlan:
    if is_robotics_topic(topic):
        return topic_discovery_robotics_fallback.robotics_fallback_plan(topic)
    if is_memory_topic(topic):
        return topic_discovery_memory_fallback.memory_fallback_plan(topic)
    if "AI" not in topic.upper() and "人工智慧" not in topic:
        return topic_discovery_generic_fallback.generic_exploration_plan(topic)
    return topic_discovery_ai_fallback.ai_fallback_plan()


def generic_exploration_plan(topic: str) -> TopicDiscoveryPlan:
    return topic_discovery_generic_fallback.generic_exploration_plan(topic)


def generic_anchor_candidates(topic: str) -> list[CandidateCompany]:
    return topic_discovery_generic_fallback.generic_anchor_candidates(topic)


def memory_fallback_plan(topic: str) -> TopicDiscoveryPlan:
    return topic_discovery_memory_fallback.memory_fallback_plan(topic)


def is_robotics_topic(topic: str) -> bool:
    normalized = topic.lower()
    return any(
        term in normalized for term in ["機器人", "robot", "robotics", "humanoid", "協作機器人"]
    )


def is_memory_topic(topic: str) -> bool:
    normalized = topic.lower()
    return any(term in normalized for term in ["記憶體", "memory", "dram", "nand", "flash", "ssd"])


def is_memory_plan(plan: TopicDiscoveryPlan) -> bool:
    return topic_discovery_quality.is_memory_plan(plan)


def robotics_fallback_plan(topic: str) -> TopicDiscoveryPlan:
    return topic_discovery_robotics_fallback.robotics_fallback_plan(topic)
