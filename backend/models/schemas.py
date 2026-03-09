"""Pydantic schemas for SQLite rows and artifact JSON payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.models.enums import (
    ActionType,
    AgentResult,
    ChatRole,
    ClaimType,
    EventStatus,
    ImageStatus,
    ManualActionStatus,
    NodeStatus,
    SupportStatus,
    TaskStatus,
)


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Task(StrictBaseModel):
    task_id: str
    parent_task_id: str | None = None
    title: str
    status: TaskStatus
    upload_file_name: str | None = None
    upload_file_path: str | None = None
    confirmed_toc_version: int | None = None
    min_generation_level: int | None = None
    text_provider: str = "mock-text"
    image_provider: str = "mock-image"
    total_nodes: int = 0
    completed_nodes: int = 0
    total_progress: float = 0.0
    current_stage: str | None = None
    current_node_uid: str | None = None
    latest_error: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    last_heartbeat_at: str | None = None
    finished_at: str | None = None


class TOCVersion(StrictBaseModel):
    toc_version_id: str
    task_id: str
    version_no: int
    file_path: str
    based_on_version_no: int | None = None
    is_confirmed: bool = False
    diff_summary_json: dict[str, Any] | None = None
    created_by: str = "system"
    created_at: str = Field(default_factory=utc_now_iso)


class TOCNode(StrictBaseModel):
    node_uid: str
    node_id: str
    level: int
    title: str
    is_generation_unit: bool = False
    source_refs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] | None = None
    children: list["TOCNode"] = Field(default_factory=list)


class TOCDocument(StrictBaseModel):
    version: int
    generated_at: str = Field(default_factory=utc_now_iso)
    based_on_version: int | None = None
    tree: list[TOCNode]


class TOCNodeSnapshot(StrictBaseModel):
    snapshot_id: str
    task_id: str
    version_no: int
    node_uid: str
    node_id: str
    parent_node_uid: str | None = None
    level: int
    title: str
    order_index: int
    is_generation_unit: bool
    source_refs_json: list[str] | None = None
    constraints_json: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class NodeState(StrictBaseModel):
    node_state_id: str
    task_id: str
    node_uid: str
    node_id: str
    title: str
    level: int
    status: NodeStatus = NodeStatus.PENDING
    progress: float = 0.0
    retry_text: int = 0
    retry_image: int = 0
    retry_fact: int = 0
    image_manual_required: bool = False
    manual_action_status: ManualActionStatus = ManualActionStatus.NONE
    current_stage: str | None = None
    last_error: str | None = None
    input_snapshot_path: str | None = None
    output_artifact_path: str | None = None
    started_at: str | None = None
    updated_at: str = Field(default_factory=utc_now_iso)
    last_heartbeat_at: str | None = None
    finished_at: str | None = None


class EventLog(StrictBaseModel):
    event_id: str
    task_id: str
    node_uid: str | None = None
    stage: str
    status: EventStatus = EventStatus.INFO
    message: str
    retry_count: int = 0
    input_snapshot_path: str | None = None
    output_artifact_path: str | None = None
    duration_ms: int | None = None
    meta_json: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class ChatMessage(StrictBaseModel):
    message_id: str
    task_id: str
    role: ChatRole
    content: str
    related_toc_version: int | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class TaskConfig(StrictBaseModel):
    task_config_id: str
    task_id: str
    text_provider: str
    image_provider: str
    text_model_name: str
    image_model_name: str
    strict_mode: bool = False
    image_retry_limit: int = 3
    length_expand_limit: int = 2
    length_trim_threshold: int = 2200
    grounded_ratio_threshold: float = 0.70
    image_score_threshold: float = 0.75
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ManualAction(StrictBaseModel):
    action_id: str
    task_id: str
    node_uid: str
    action_type: ActionType
    action_payload_json: dict[str, Any] | None = None
    operator_name: str | None = None
    result_status: str
    created_at: str = Field(default_factory=utc_now_iso)


class Milestone(StrictBaseModel):
    name: str
    date: str


class RequirementItem(StrictBaseModel):
    type: str
    key: str
    value: str
    source_ref: str | None = None


class RequirementSubsystem(StrictBaseModel):
    name: str
    description: str
    requirements: list[RequirementItem] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)


class SourceIndexItem(StrictBaseModel):
    page: int
    paragraph_id: str
    text: str


class RequirementProject(StrictBaseModel):
    name: str
    customer: str = ""
    location: str = ""
    duration_days: int | None = None
    milestones: list[Milestone] = Field(default_factory=list)


class RequirementScope(StrictBaseModel):
    overview: str
    subsystems: list[RequirementSubsystem] = Field(default_factory=list)


class RequirementConstraints(StrictBaseModel):
    standards: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)


class RequirementDocument(StrictBaseModel):
    project: RequirementProject
    scope: RequirementScope
    constraints: RequirementConstraints
    source_index: dict[str, SourceIndexItem] = Field(default_factory=dict)


class ParseReport(StrictBaseModel):
    task_id: str
    source_file: str
    result: AgentResult
    paragraph_count: int
    subsystem_count: int
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=utc_now_iso)


class TextParagraph(StrictBaseModel):
    paragraph_id: str
    text: str
    source_refs: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)


class TextSection(StrictBaseModel):
    section_id: str
    title: str
    paragraphs: list[TextParagraph] = Field(default_factory=list)


class HighlightParagraph(StrictBaseModel):
    paragraph_id: str
    text: str
    style_hint: str


class NodeText(StrictBaseModel):
    node_uid: str
    node_id: str
    title: str
    summary: str
    sections: list[TextSection] = Field(default_factory=list)
    highlight_paragraphs: list[HighlightParagraph] = Field(default_factory=list)
    word_count: int = 0
    version: int = 1
    generated_at: str = Field(default_factory=utc_now_iso)


class FactClaim(StrictBaseModel):
    claim_id: str
    text: str
    claim_type: ClaimType
    support_status: SupportStatus
    source_refs: list[str] = Field(default_factory=list)


class FactCheck(StrictBaseModel):
    node_uid: str
    grounded_ratio: float
    result: AgentResult
    claims: list[FactClaim] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    weak_claims: list[str] = Field(default_factory=list)


class EntityItem(StrictBaseModel):
    entity_id: str
    name: str
    category: str
    must_have: bool = True


class EntityExtraction(StrictBaseModel):
    node_uid: str
    entities: list[EntityItem] = Field(default_factory=list)


class ImagePromptItem(StrictBaseModel):
    prompt_id: str
    image_type: str
    prompt: str
    must_have_elements: list[str] = Field(default_factory=list)
    forbidden_elements: list[str] = Field(default_factory=list)
    bind_anchor: str | None = None
    bind_section: str | None = None


class ImagePrompts(StrictBaseModel):
    node_uid: str
    prompts: list[ImagePromptItem] = Field(default_factory=list)


class ImageItem(StrictBaseModel):
    image_id: str
    type: str
    file: str
    caption: str
    group_caption: str | None = None
    prompt_id: str | None = None
    must_have_elements: list[str] = Field(default_factory=list)
    bind_anchor: str | None = None
    bind_section: str | None = None
    retry_count: int = 0
    status: ImageStatus = ImageStatus.PASS


class ImagesArtifact(StrictBaseModel):
    node_uid: str
    images: list[ImageItem] = Field(default_factory=list)


class ImageScoreItem(StrictBaseModel):
    image_id: str
    score: float
    missing_elements: list[str] = Field(default_factory=list)
    result: AgentResult


class ImageRelevanceReport(StrictBaseModel):
    node_uid: str
    image_scores: list[ImageScoreItem] = Field(default_factory=list)
    overall_result: AgentResult


class TableItem(StrictBaseModel):
    table_id: str
    title: str
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    style_name: str = "BiddingTable"
    bind_anchor: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class TablesArtifact(StrictBaseModel):
    node_uid: str
    tables: list[TableItem] = Field(default_factory=list)


class ConsistencyIssue(StrictBaseModel):
    issue_type: str
    location: str
    detail: str
    suggestion: str
    fix_action: str | None = None
    fixable: bool = False
    fixed: bool = False


class CheckResult(StrictBaseModel):
    result: AgentResult
    issues: list[ConsistencyIssue] = Field(default_factory=list)


class ConsistencyChecks(StrictBaseModel):
    entity_consistency: CheckResult
    term_consistency: CheckResult
    constraint_consistency: CheckResult
    reference_consistency: CheckResult


class ConsistencyReport(StrictBaseModel):
    node_uid: str
    result: AgentResult
    checks: ConsistencyChecks


class Metrics(StrictBaseModel):
    node_uid: str
    word_count: int
    grounded_ratio: float
    image_score_avg: float
    image_retry_total: int
    text_retry_total: int
    fact_retry_total: int
    duration_ms: int
    final_status: NodeStatus
