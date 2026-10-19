from __future__ import annotations

import json
import re
import time
from typing import Any

from backend.app.chat.mock import (
    ChatProvider,
    MockChatProvider,
    create_chat_provider,
    is_medical_definition_question,
)
from backend.app.chat.prompts import RETRIEVAL_SYSTEM_PROMPT
from backend.app.chat.schemas import AgentTraceStep, ChatRequest, ChatResponse, ChatToolTrace, RetrievalDecision
from backend.app.database import CaseRepository
from backend.app.mcp.registry import ToolRegistry
from backend.app.mcp.schemas import ToolContext
from backend.app.services.dermfm_candidate_sets import display_label_zh
from backend.app.services.privacy import EgressGuard, EgressRequest, sanitize_text


VISUAL_MODEL_DISCLOSURE_PATTERNS = (
    r"DermFM(?:[\s‑-]*Zero(?:[\s‑-]*Open)?)?",
    r"HAM7(?:[\s‑-]*(?:Linear[\s‑-]*Head|线性任务头|任务头))?",
    r"supervised_linear_probe",
    r"supervised_multimodal_pad",
    r"dermfm_extended_[A-Za-z0-9_.-]+",
    r"ham7_supervised_[A-Za-z0-9_.-]+",
    r"pad_clinical_multimodal_[A-Za-z0-9_.-]+",
)


def redact_visual_model_details(text: str) -> str:
    result = str(text)
    for pattern in VISUAL_MODEL_DISCLOSURE_PATTERNS:
        result = re.sub(pattern, "本地视觉模型", result, flags=re.I)
    return result


def public_visual_evidence(visual: dict[str, Any] | None) -> dict[str, Any] | None:
    if not visual:
        return None
    return {
        "top_predictions": [
            {"label": display_label_zh(str(item.get("label", "未知候选"))), "score": float(item.get("score", 0.0))}
            for item in visual.get("top_predictions", [])
        ],
        "image_quality": visual.get("image_quality"),
        "supports_triage": bool(visual.get("supports_triage", False)),
        "clinical_context": dict(visual.get("clinical_context") or {}),
    }


def public_triage_result(triage: dict[str, Any] | None) -> dict[str, Any] | None:
    if not triage:
        return None
    metadata = triage.get("confidence_metadata") or {}
    return {
        "level": triage.get("level"),
        "reason_codes": list(triage.get("reason_codes", [])),
        "policy_version": triage.get("policy_version"),
        "confidence_metadata": {
            "image_quality": metadata.get("image_quality"),
            "top1_label": display_label_zh(str(metadata.get("top1_label", "未知候选"))),
            "top1_score": metadata.get("top1_score"),
            "scores_are_calibrated_probabilities": metadata.get("scores_are_calibrated_probabilities", False),
        },
    }


def public_care_pathway(care: dict[str, Any] | None) -> dict[str, Any] | None:
    if not care:
        return None
    keys = ("level", "action", "destination_type", "urgency", "recommended_next_steps", "guideline_references", "disclaimer")
    return {key: care.get(key) for key in keys if key in care}


def public_guideline_context(guidelines: dict[str, Any] | None) -> dict[str, Any] | None:
    if not guidelines:
        return None
    return {
        "chunks": list(guidelines.get("chunks", [])),
        "evidence_assembly": dict(guidelines.get("evidence_assembly", {})),
    }


def _extract_decision(text: str) -> RetrievalDecision:
    cleaned = str(text).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S)
    for candidate in [cleaned, *re.findall(r"\{.*?\}", cleaned, flags=re.S)]:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return RetrievalDecision.model_validate(value)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    raise ValueError("检索决策未返回有效 JSON")


class DermaGuardChatAgent:
    """Finite-step retrieval agent. MCP reads state; local rules own all decisions."""

    MAX_RETRIEVAL_ROUNDS = 4

    def __init__(
        self,
        registry: ToolRegistry,
        repository: CaseRepository,
        egress_guard: EgressGuard | None = None,
        provider: ChatProvider | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.egress_guard = egress_guard or EgressGuard(repository)
        self.provider = provider or create_chat_provider()

    def _public_case_context(self, case_id: str, mode: str) -> dict[str, Any]:
        patient = self.repository.get_case_patient(case_id)
        narrative = ""
        if patient:
            narrative = sanitize_text(str(patient.get("chief_complaint") or ""))[0]
            for field in ("name", "outpatient_no", "phone"):
                identity = str(patient.get(field) or "").strip()
                if identity:
                    narrative = narrative.replace(identity, "[REDACTED_IDENTITY]")
        return {
            "case_exists": self.repository.get_case(case_id) is not None,
            "has_structured_clinical_profile": bool(
                patient and patient.get("clinical_profile")
            ),
            "clinical_narrative": narrative[:1200],
            "mode": mode,
        }

    @staticmethod
    def _public_observations(results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        projections = {
            "get_visual_evidence": public_visual_evidence,
            "get_triage_result": public_triage_result,
            "get_care_pathway": public_care_pathway,
            "search_guideline": public_guideline_context,
        }
        public: dict[str, dict[str, Any]] = {}
        for name, value in results.items():
            projected = projections[name](value) if name in projections else value
            if projected is not None:
                public[name] = projected
        return public

    async def _invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        request: ChatRequest,
        destination: str,
        traces: list[ChatToolTrace],
    ) -> dict[str, Any] | None:
        try:
            invocation = await self.registry.invoke(
                tool_name,
                {**arguments, "case_id": request.case_id},
                ToolContext(case_id=request.case_id, channel="mcp", destination=destination, for_cloud=True),
            )
            traces.append(ChatToolTrace(
                tool_name=tool_name,
                status="success",
                latency_ms=invocation.latency_ms,
                egress_allowed=invocation.egress_allowed,
                egress_latency_ms=invocation.egress_latency_ms,
            ))
            return invocation.result
        except Exception:
            traces.append(ChatToolTrace(tool_name=tool_name, status="error", latency_ms=0))
            return None

    @staticmethod
    def _is_privacy_question(message: str) -> bool:
        lowered = message.lower()
        return any(term in lowered for term in ("原始图片", "照片上传", "上传到云", "发给云端", "base64"))

    async def _load_case_evidence(
        self, request: ChatRequest, destination: str, message: str, traces: list[ChatToolTrace]
    ) -> dict[str, dict[str, Any]]:
        if self._is_privacy_question(message):
            names = ["get_privacy_report"]
        elif is_medical_definition_question(message):
            # 纯医学知识问题不需要把当前病例风险报告带入上下文。
            names = []
        else:
            names = ["get_visual_evidence", "get_triage_result", "get_care_pathway"]
        results: dict[str, dict[str, Any]] = {}
        for name in names:
            value = await self._invoke_tool(name, {}, request=request, destination=destination, traces=traces)
            if value is not None:
                results[name] = value
        return results

    @staticmethod
    def _default_query(
        message: str,
        results: dict[str, dict[str, Any]],
        clinical_narrative: str = "",
    ) -> str:
        visual = results.get("get_visual_evidence", {})
        triage = results.get("get_triage_result", {})
        labels = [str(item.get("label", "")) for item in visual.get("top_predictions", [])[:3] if item.get("label")]
        reasons = [str(item) for item in triage.get("reason_codes", [])]
        clinical = visual.get("clinical_context") or {}
        positive = [
            name for key, name in {
                "itch": "瘙痒", "hurt": "疼痛", "bleed": "出血",
                "grew": "近期增大", "changed": "外观变化",
                "skin_cancer_history": "皮肤肿瘤史", "cancer_history": "其他肿瘤史",
            }.items() if clinical.get(key)
        ]
        parts = [message, clinical_narrative, *labels, *positive, str(clinical.get("region", "")), str(triage.get("level", "")), *reasons, "支持证据 冲突证据 鉴别依据 检查指征 转诊指南"]
        return " ".join(item for item in parts if item)[:500]

    def _safe_query(self, query: str, case_id: str) -> str | None:
        sanitized, _ = sanitize_text(query.strip())
        if not sanitized:
            return None
        decision = self.egress_guard.check(EgressRequest(
            channel="llm", destination="retrieval_query", payload={"query": sanitized[:500]}, case_id=case_id
        ))
        return sanitized[:500] if decision.allowed else None

    def _retrieval_decision(
        self,
        provider: ChatProvider,
        *,
        message: str,
        case_evidence: dict[str, dict[str, Any]],
        retrieval_observations: list[dict[str, Any]],
        public_context: dict[str, Any],
        history: list[dict[str, Any]],
        iteration: int,
    ) -> RetrievalDecision:
        planning_method = getattr(provider, "plan", None)
        if not callable(planning_method):
            raise RuntimeError("当前提供方不支持检索决策")
        payload = {
            "user_message": message,
            "iteration": iteration,
            "public_case_context": public_context,
            "case_evidence": self._public_observations(case_evidence),
            "retrieval_observations": retrieval_observations,
            "recent_history": history[-6:],
            "output_schema": RetrievalDecision.model_json_schema(),
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                return _extract_decision(planning_method(payload, RETRIEVAL_SYSTEM_PROMPT))
            except Exception as exc:
                last_error = exc
        raise RuntimeError("检索决策连续解析失败") from last_error

    @staticmethod
    def _merge_retrievals(observations: list[dict[str, Any]]) -> dict[str, Any]:
        chunks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for observation in observations:
            for chunk in observation.get("chunks", []):
                chunk_id = str(chunk.get("id", ""))
                if chunk_id and chunk_id not in seen:
                    chunks.append(chunk)
                    seen.add(chunk_id)
        assembly = dict((observations[-1].get("evidence_assembly") or {})) if observations else {}
        if any(chunk.get("evidence_status") == "充分" for chunk in chunks):
            assembly["evidence_sufficient"] = True
        return {"chunks": chunks[:5], "evidence_assembly": assembly}

    @staticmethod
    def _risk_conflicts(response: str, results: dict[str, dict[str, Any]]) -> bool:
        triage = results.get("get_triage_result", {})
        level = str(triage.get("level") or "")
        forbidden = {
            "PRIORITY_REFERRAL": ["routine", "low risk", "local_review", "低风险", "无需就医", "无需转诊"],
            "REFERRAL": ["routine", "low risk", "local_review", "低风险", "无需就医", "无需转诊"],
        }.get(level, [])
        lowered = response.lower()
        return any(item in lowered for item in forbidden)

    def _save_trace(self, case_id: str, trace: AgentTraceStep) -> None:
        self.repository.add_agent_trace(case_id, trace.step, trace.model_dump(mode="json"))

    async def respond(self, request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        provider = self.provider if request.model == "auto" else create_chat_provider(request.model)
        provider_used, model_used = provider.name, provider.model
        history = [
            {**item, "message": redact_visual_model_details(str(item.get("message", "")))}
            for item in self.repository.list_chat_messages(request.case_id)[-12:]
        ]
        sanitized_message, _ = sanitize_text(request.message)
        traces: list[ChatToolTrace] = []
        agent_trace: list[AgentTraceStep] = []
        public_context = self._public_case_context(request.case_id, request.mode)
        results = await self._load_case_evidence(request, provider.name, sanitized_message, traces)
        retrieval_observations: list[dict[str, Any]] = []
        seen_queries: set[str] = set()
        fallback_triggered = False

        planning_gate = self.egress_guard.check(EgressRequest(
            channel="llm",
            destination=provider.name,
            payload={"message": sanitized_message, "history": history[-6:]},
            case_id=request.case_id,
        ))
        if planning_gate.allowed:
            for step in range(1, self.MAX_RETRIEVAL_ROUNDS + 1):
                try:
                    decision = self._retrieval_decision(
                        provider,
                        message=sanitized_message,
                        case_evidence=results,
                        retrieval_observations=retrieval_observations,
                        public_context=public_context,
                        history=history,
                        iteration=step,
                    )
                except Exception:
                    fallback_triggered = True
                    decision = RetrievalDecision(
                        intent="deterministic_retrieval_fallback",
                        retrieval_query=self._default_query(
                            sanitized_message, results,
                            str(public_context.get("clinical_narrative", "")),
                        ),
                        reasoning_summary="LLM 检索决策不可用，执行一次可审计的本地 fallback。",
                    )

                # 医学概念不能仅凭病例状态直接回答；至少完成一次本地循证检索。
                if is_medical_definition_question(sanitized_message) and not retrieval_observations:
                    decision = RetrievalDecision(
                        intent="medical_definition",
                        retrieval_query=(
                            decision.retrieval_query
                            or f"{sanitized_message} 定义 常见表现 危险变化 权威医学资料"
                        ),
                        evidence_sufficient=False,
                        reasoning_summary="医学概念问题在回答前必须先检索本地证据。",
                    )

                if decision.should_ask_user:
                    # The clinician already submitted the canonical structured
                    # profile before inference.  The LLM may refine retrieval,
                    # but must not start a second symptom-question workflow.
                    decision = RetrievalDecision(
                        intent=decision.intent,
                        retrieval_query=self._default_query(
                            sanitized_message, results,
                            str(public_context.get("clinical_narrative", "")),
                        ),
                        evidence_sufficient=False,
                        reasoning_summary="结构化病例已采集，改为检索证据而非追问患者。",
                    )

                if decision.evidence_sufficient:
                    trace = AgentTraceStep(
                        step=step, intent=decision.intent, evidence_sufficient=True,
                        decision="ANSWER_WITH_EVIDENCE", reasoning_summary=decision.reasoning_summary,
                        provider_used=provider.name,
                    )
                    agent_trace.append(trace)
                    self._save_trace(request.case_id, trace)
                    break

                query = self._safe_query(
                    decision.retrieval_query or self._default_query(
                        sanitized_message, results,
                        str(public_context.get("clinical_narrative", "")),
                    ), request.case_id
                )
                if not query or query in seen_queries:
                    trace = AgentTraceStep(
                        step=step, intent=decision.intent, retrieval_query=query,
                        evidence_sufficient=False, decision="STOP_NO_NEW_QUERY",
                        reasoning_summary=decision.reasoning_summary, provider_used=provider.name,
                        fallback_triggered=fallback_triggered,
                    )
                    agent_trace.append(trace)
                    self._save_trace(request.case_id, trace)
                    break

                seen_queries.add(query)
                observation = await self._invoke_tool(
                    "search_guideline", {"query": query, "top_k": 3},
                    request=request, destination=provider.name, traces=traces,
                )
                summaries: list[str] = []
                if observation is not None:
                    retrieval_observations.append(observation)
                    results["search_guideline"] = self._merge_retrievals(retrieval_observations)
                    summaries.append(f"医学检索返回 {len(observation.get('chunks', []))} 条证据")
                else:
                    summaries.append("医学检索不可用")
                trace = AgentTraceStep(
                    step=step, intent=decision.intent, retrieval_query=query,
                    evidence_sufficient=False,
                    decision="STOP_MAX_RETRIEVAL_ROUNDS" if step == self.MAX_RETRIEVAL_ROUNDS else "RETRIEVE_AND_OBSERVE",
                    observation_summary=summaries, reasoning_summary=decision.reasoning_summary,
                    provider_used=provider.name, fallback_triggered=fallback_triggered,
                )
                agent_trace.append(trace)
                self._save_trace(request.case_id, trace)
                if fallback_triggered:
                    break

        outbound_payload = {
            "message": sanitized_message,
            "mode": request.mode,
            "visual_evidence": public_visual_evidence(results.get("get_visual_evidence")),
            "triage_result": public_triage_result(results.get("get_triage_result")),
            "care_pathway": public_care_pathway(results.get("get_care_pathway")),
            "guideline_context": public_guideline_context(results.get("search_guideline")),
            "privacy_report": results.get("get_privacy_report"),
        }
        outbound = self.egress_guard.check(EgressRequest(
            channel="llm", destination=provider.name,
            payload={key: value for key, value in outbound_payload.items() if value is not None},
            case_id=request.case_id,
        ))
        if outbound.allowed:
            safe_payload = outbound.sanitized_payload
            safe_results = {
                tool_name: safe_payload[payload_name]
                for tool_name, payload_name in {
                    "get_visual_evidence": "visual_evidence",
                    "get_triage_result": "triage_result",
                    "get_care_pathway": "care_pathway",
                    "search_guideline": "guideline_context",
                    "get_privacy_report": "privacy_report",
                }.items()
                if payload_name in safe_payload
            }
            try:
                response_text = provider.generate(
                    str(safe_payload["message"]), str(safe_payload["mode"]), safe_results,
                    history=history, detail_level=request.detail_level,
                )
                response_text = redact_visual_model_details(response_text)
                if self._risk_conflicts(response_text, safe_results):
                    fallback_triggered = True
                    response_text = MockChatProvider().generate(
                        str(safe_payload["message"]), str(safe_payload["mode"]), safe_results,
                        history=history, detail_level=request.detail_level,
                    )
            except Exception:
                if provider.name == "mock":
                    raise
                provider_used, model_used = f"{provider.name}->mock", "local-mock"
                response_text = "云端解释服务暂时不可用，已自动切换为本地解释。" + MockChatProvider().generate(
                    str(safe_payload["message"]), str(safe_payload["mode"]), safe_results,
                    history=history, detail_level=request.detail_level,
                )
                self.repository.add_audit_event({
                    "event_type": "provider_fallback", "case_id": request.case_id,
                    "channel": "llm", "tool_name": None, "destination": provider.name,
                    "privacy_action": "FALLBACK_TO_LOCAL_MOCK", "allowed": True,
                    "sanitized_fields": [], "latency_ms": 0,
                })
            privacy_status, stored_user_message = "SAFE", sanitized_message
        else:
            response_text = (
                "请求中包含受保护的原始影像、图片编码或本地路径，PrivFlow 已阻止其外发。"
                "原始医疗影像必须留在本地可信域。本系统仅用于辅助筛查和分级转诊，不构成医学诊断。"
            )
            privacy_status, stored_user_message = "BLOCKED", "[BLOCKED_SENSITIVE_CONTENT]"

        self.repository.add_chat_message(request.case_id, "user", stored_user_message, [item.model_dump(mode="json") for item in traces])
        self.repository.add_chat_message(request.case_id, "assistant", response_text, [])
        return ChatResponse(
            case_id=request.case_id, response=response_text, tool_calls=traces,
            privacy_status=privacy_status, provider=provider_used, model=model_used,
            latency_ms=(time.perf_counter() - started) * 1000, mode=request.mode,
            detail_level=request.detail_level, agent_trace=agent_trace,
        )
