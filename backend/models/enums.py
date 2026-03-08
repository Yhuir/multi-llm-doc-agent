"""Shared enum definitions for task, node, and artifact states."""

from enum import Enum


class StrEnum(str, Enum):
    """String-backed enum with stable serialization."""

    def __str__(self) -> str:
        return self.value


class TaskStatus(StrEnum):
    NEW = "NEW"
    PARSED = "PARSED"
    TOC_REVIEW = "TOC_REVIEW"
    GENERATING = "GENERATING"
    LAYOUTING = "LAYOUTING"
    EXPORTING = "EXPORTING"
    DONE = "DONE"
    PAUSED = "PAUSED"
    FAILED = "FAILED"


class NodeStatus(StrEnum):
    PENDING = "PENDING"
    TEXT_GENERATING = "TEXT_GENERATING"
    TEXT_DONE = "TEXT_DONE"
    FACT_CHECKING = "FACT_CHECKING"
    FACT_PASSED = "FACT_PASSED"
    IMAGE_GENERATING = "IMAGE_GENERATING"
    IMAGE_DONE = "IMAGE_DONE"
    IMAGE_VERIFYING = "IMAGE_VERIFYING"
    IMAGE_VERIFIED = "IMAGE_VERIFIED"
    LENGTH_CHECKING = "LENGTH_CHECKING"
    LENGTH_PASSED = "LENGTH_PASSED"
    CONSISTENCY_CHECKING = "CONSISTENCY_CHECKING"
    READY_FOR_LAYOUT = "READY_FOR_LAYOUT"
    LAYOUTED = "LAYOUTED"
    NODE_DONE = "NODE_DONE"
    NODE_FAILED = "NODE_FAILED"
    WAITING_MANUAL = "WAITING_MANUAL"


class ManualActionStatus(StrEnum):
    NONE = "NONE"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SKIPPED = "SKIPPED"
    REGENERATED = "REGENERATED"
    FAILED = "FAILED"


class EventStatus(StrEnum):
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ActionType(StrEnum):
    VIEW_FAILURE = "VIEW_FAILURE"
    REGENERATE_NODE = "REGENERATE_NODE"
    SKIP_IMAGE = "SKIP_IMAGE"
    RELAX_THRESHOLD = "RELAX_THRESHOLD"
    MARK_PASSED = "MARK_PASSED"
    EXPORT_PARTIAL = "EXPORT_PARTIAL"


class ClaimType(StrEnum):
    EQUIPMENT = "equipment"
    QUANTITY = "quantity"
    LOCATION = "location"
    INTERFACE = "interface"
    PARAMETER = "parameter"
    THRESHOLD = "threshold"
    STANDARD = "standard"
    DURATION = "duration"
    ACCEPTANCE = "acceptance"
    PROCESS = "process"


class AgentResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    RETRY = "RETRY"
    MANUAL = "MANUAL"
    SKIP = "SKIP"


class SupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    WEAKLY_SUPPORTED = "WEAKLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    GENERAL_ENGINEERING_KNOWLEDGE = "GENERAL_ENGINEERING_KNOWLEDGE"


class ImageStatus(StrEnum):
    PASS = "PASS"
    RETRYING = "RETRYING"
    NEED_MANUAL_CONFIRM = "NEED_MANUAL_CONFIRM"
    FAILED = "FAILED"
