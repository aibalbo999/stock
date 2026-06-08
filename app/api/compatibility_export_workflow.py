from __future__ import annotations

# ruff: noqa: F401

from app.services.llm_api import LLMApiService
from app.services.llm_client import LLMClient
from app.services.pipeline_api import PipelineApiService
from app.services.run_state import RunStateService
from app.services.run_task_api import (
    AsyncReportValidationError,
    RunTaskApiService,
    RunTaskNotFound,
    TaskQueueUnavailableError,
)
from app.services.schedule_config import ScheduleConfigStore
from app.services.standard_pipeline import StandardReportPipelineService
from app.services.supply_chain_graph_api import SupplyChainGraphApiService
from app.services.supply_chain_graph_neo4j import Neo4jGraphImportService
from app.services.workflow_checkpoint import (
    DISCOVERED_PIPELINE_STEPS,
    STANDARD_PIPELINE_STEPS,
    WorkflowCheckpointRecorder,
)
from app.services.workflow_orchestration import (
    WorkflowOrchestrationError,
    WorkflowOrchestrationRunner,
)

WORKFLOW_EXPORT_NAMES = (
    "RunTaskApiService",
    "AsyncReportValidationError",
    "RunTaskNotFound",
    "TaskQueueUnavailableError",
    "RunStateService",
    "LLMApiService",
    "LLMClient",
    "PipelineApiService",
    "ScheduleConfigStore",
    "StandardReportPipelineService",
    "SupplyChainGraphApiService",
    "Neo4jGraphImportService",
    "DISCOVERED_PIPELINE_STEPS",
    "STANDARD_PIPELINE_STEPS",
    "WorkflowCheckpointRecorder",
    "WorkflowOrchestrationError",
    "WorkflowOrchestrationRunner",
)


def compatibility_workflow_export_namespace() -> dict[str, object]:
    return {name: globals()[name] for name in WORKFLOW_EXPORT_NAMES}
