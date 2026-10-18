from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictModel):
    case_id: str
    message: str = Field(min_length=1, max_length=2000)
    mode: Literal["patient", "clinician"] = "patient"
    detail_level: Literal["concise", "detailed"] = "concise"
    model: Literal[
        "auto",
        "glm-5.3-flash",
        "glm-4-flash",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "gemini-flash",
    ] = "auto"


class ChatToolTrace(StrictModel):
    tool_name: str
    status: Literal["success", "blocked", "error"]
    latency_ms: float = Field(ge=0)
    egress_allowed: bool | None = None
    egress_latency_ms: float | None = Field(default=None, ge=0)


class RetrievalDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")
    intent: str = Field(min_length=1, max_length=80)
    retrieval_query: str | None = Field(default=None, max_length=500)
    missing_information: list[str] = Field(default_factory=list, max_length=8)
    should_ask_user: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)
    evidence_sufficient: bool = False
    reasoning_summary: str = Field(default="", max_length=300)


class AgentTraceStep(StrictModel):
    step: int = Field(ge=1)
    intent: str
    retrieval_query: str | None = None
    evidence_sufficient: bool = False
    missing_information: list[str] = Field(default_factory=list)
    decision: str
    observation_summary: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    provider_used: str
    fallback_triggered: bool = False


class ChatResponse(StrictModel):
    case_id: str
    response: str
    tool_calls: list[ChatToolTrace]
    privacy_status: str
    provider: str
    model: str
    latency_ms: float = Field(ge=0)
    mode: Literal["patient", "clinician"]
    detail_level: Literal["concise", "detailed"]
    agent_trace: list[AgentTraceStep] = Field(default_factory=list)
