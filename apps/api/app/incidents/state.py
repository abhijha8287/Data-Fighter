"""Typed state for the Data Firefighter LangGraph agent.

The graph does not run end-to-end in one call — it pauses after
investigation for a human-reviewable checkpoint before remediation, and
again before PR creation. LangGraph's SqliteSaver checkpointer (keyed by
thread_id=incident_id) persists the resume point between those calls; see
app/agents/graph.py.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, TypedDict


class IncidentStatus(StrEnum):
    DETECTED = "detected"
    INVESTIGATING = "investigating"
    INVESTIGATED = "investigated"
    REMEDIATING = "remediating"
    REMEDIATED = "remediated"
    CREATING_PR = "creating_pr"
    RESOLVED = "resolved"
    FAILED = "failed"


class SchemaField(TypedDict):
    field_path: str
    type: str
    nullable: bool


class LineageAsset(TypedDict):
    urn: str
    name: str
    platform: str
    entity_type: str
    asset_category: str | None  # "pipeline" | "dashboard" | "ml_model" | None
    owner: str


class BlastRadius(TypedDict):
    downstream_assets: list[LineageAsset]
    total_count: int
    pipelines: int
    dashboards: int
    ml_models: int
    owners: list[str]


class RootCause(TypedDict):
    summary: str
    affected_files: list[str]
    confidence: float


class ProposedFix(TypedDict):
    branch_taken: Literal["removal", "no_fix_needed"]
    files: dict[str, str]  # path -> new (fixed) file content
    files_before: dict[str, str]  # path -> original file content, for the PR/UI diff view
    explanation: str


class ValidationResult(TypedDict):
    sql_parses: bool
    schema_check_passed: bool
    file_scope_check_passed: bool
    passed: bool
    errors: list[str]


class IncidentReport(TypedDict):
    incident_id: str
    dataset: str
    incident_type: str
    description: str
    blast_radius: BlastRadius
    root_cause: RootCause
    remediation: ProposedFix
    validation: ValidationResult
    github_pr_url: str | None
    resolved_at: str | None


class IncidentState(TypedDict, total=False):
    incident_id: str
    dataset_urn: str
    incident_type: str
    incident_description: str
    affected_column: str | None  # only meaningful for incident_type="column_deleted"
    status: IncidentStatus
    error: str | None

    dataset_metadata: dict
    schema_before: list[SchemaField]
    schema_after: list[SchemaField]

    downstream_assets: list[LineageAsset]
    affected_owners: list[str]

    blast_radius: BlastRadius
    root_cause: RootCause

    affected_files: list[str]  # cached search_code() result, read-only after
                                # investigate_root_cause sets it (see
                                # GitHubService.search_code note in the design doc)

    proposed_fix: ProposedFix
    validation_result: ValidationResult

    github_pr_url: str | None
    incident_report: IncidentReport
    datahub_write_back: dict | None
