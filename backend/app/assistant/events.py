"""Wire contract for the assistant stream.

Mirrors frontend/src/lib/assistantTypes.ts exactly. That file is the source of truth --
the UI reducer (AssistantPage.tsx::applyEvent) reads these fields by name, so a rename
here silently renders nothing rather than raising.

Casing is deliberately mixed and load-bearing:
  * frame top level  -> snake_case  (type, run_id)
  * everything nested -> camelCase  (artifactRefs, promptId)
Hence CamelModel for the payload models and a plain BaseModel for the frames. Always
serialize frames with model_dump(by_alias=True) -- by_alias recurses into the nested
payloads while leaving the frame's own snake_case fields alone.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

AgentKind = Literal["supervisor", "sql", "graph", "vector", "legal"]
StepStatus = Literal["running", "done", "error"]
StepKind = Literal["route", "thinking", "tool_call", "tool_result"]
DocumentFormat = Literal["pdf", "csv", "docx", "text", "html", "png", "svg", "json"]
# The UI's language codes are bare (en/hi/kn); Sarvam-style "en-IN" tags are not used here.
AssistantLanguage = Literal["en", "hi", "kn"]


class CamelModel(BaseModel):
    """Serializes to camelCase, accepts either casing on input."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AssistantStep(CamelModel):
    id: str
    agent: AgentKind
    specialist: str | None = None
    kind: StepKind
    title: str
    detail: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    query: str | None = None
    output: str | None = None
    status: StepStatus
    artifact_refs: list[str] | None = None


class RetrievalChunk(CamelModel):
    case_ref: str | None = None
    source: str | None = None
    score: float | None = None
    snippet: str | None = None


class RetrievalPayload(CamelModel):
    step_id: str | None = None
    mode: str
    query: str
    count: int
    sources: list[str] = []
    chunks: list[RetrievalChunk] = []


class CodePayload(CamelModel):
    step_id: str | None = None
    phase: Literal["template", "executing", "done", "error"]
    language: str = "python"
    code: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    success: bool | None = None


class PlanTask(CamelModel):
    id: str
    title: str
    specialist: str
    status: Literal["pending", "running", "done", "error"] = "pending"


class PlanPayload(CamelModel):
    tasks: list[PlanTask]


# --- Artifacts ---------------------------------------------------------------


class GraphArtifactNode(CamelModel):
    id: str
    label: str
    type: str  # drives node colour + legend in GraphArtifactView
    properties: dict[str, str | float | int] | None = None


class GraphArtifactLink(CamelModel):
    source: str
    target: str
    relationship: str
    properties: dict[str, str | float | int] | None = None


class GraphArtifact(CamelModel):
    kind: Literal["graph"] = "graph"
    id: str
    title: str
    nodes: list[GraphArtifactNode]
    links: list[GraphArtifactLink]
    caption: str | None = None


class TableArtifact(CamelModel):
    kind: Literal["table"] = "table"
    id: str
    title: str
    columns: list[str]
    rows: list[list[Any]]
    caption: str | None = None


class DocumentArtifact(CamelModel):
    kind: Literal["document"] = "document"
    id: str
    title: str
    format: DocumentFormat
    url: str | None = None   # DocumentArtifactView fetches this when text is absent
    text: str | None = None  # inline body when there's no url
    caption: str | None = None


AssistantArtifact = Annotated[
    Union[GraphArtifact, TableArtifact, DocumentArtifact],
    Field(discriminator="kind"),
]


class AssistantAction(CamelModel):
    id: str
    label: str
    prompt: str
    prompt_id: str | None = None
    icon: str | None = None  # "link" | "graph" | "legal" | "trend"


class AssistantCitation(CamelModel):
    id: str
    label: str
    source: str
    href: str | None = None
    document_artifact_id: str | None = None
    snippet: str | None = None


# --- Frames ------------------------------------------------------------------


class RunStartedEvent(BaseModel):
    type: Literal["run_started"] = "run_started"
    run_id: str


class StepEvent(BaseModel):
    type: Literal["step"] = "step"
    run_id: str
    step: AssistantStep


class AnswerDeltaEvent(BaseModel):
    type: Literal["answer_delta"] = "answer_delta"
    run_id: str
    delta: str


class ArtifactEvent(BaseModel):
    type: Literal["artifact"] = "artifact"
    run_id: str
    artifact: AssistantArtifact


class RetrievalEvent(BaseModel):
    type: Literal["retrieval"] = "retrieval"
    run_id: str
    retrieval: RetrievalPayload


class CodeEvent(BaseModel):
    type: Literal["code"] = "code"
    run_id: str
    code: CodePayload


class PlanEvent(BaseModel):
    type: Literal["plan"] = "plan"
    run_id: str
    plan: PlanPayload


class ActionEvent(BaseModel):
    type: Literal["action"] = "action"
    run_id: str
    action: AssistantAction


class CitationEvent(BaseModel):
    type: Literal["citation"] = "citation"
    run_id: str
    citation: AssistantCitation


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    run_id: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    run_id: str
    message: str


AssistantEvent = Union[
    RunStartedEvent, StepEvent, AnswerDeltaEvent, ArtifactEvent,
    RetrievalEvent, CodeEvent, PlanEvent,
    ActionEvent, CitationEvent, DoneEvent, ErrorEvent,
]

TERMINAL_EVENT_TYPES = frozenset({"done", "error"})


def to_wire(event: AssistantEvent) -> dict[str, Any]:
    """Frame -> the exact JSON dict the frontend expects.

    exclude_none keeps optional fields absent rather than null: the UI treats
    `detail: null` and a missing `detail` the same, but absent frames stay smaller over
    the socket and read better in the trace view.
    """
    return event.model_dump(by_alias=True, exclude_none=True)
