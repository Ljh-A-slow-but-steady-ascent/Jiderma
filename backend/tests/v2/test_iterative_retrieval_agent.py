from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.chat import DermaGuardChatAgent
from backend.app.chat.mock import MockChatProvider
from backend.app.chat.schemas import ChatRequest, RetrievalDecision
from backend.app.auth import hash_password
from backend.app.care.schemas import CandidatePrediction, VisualEvidence
from backend.app.database import CaseRepository, init_database
from backend.app.mcp.factory import create_tool_registry
from backend.app.services.care_service import CareService
from backend.app.services.container import create_service_container
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.services.privacy import EgressGuard
from backend.app.services.triage_service import TriagePolicyService


@pytest.fixture
def chat_setup(tmp_path):
    repository = CaseRepository(init_database("sqlite+pysqlite:///:memory:"))
    services = create_service_container(repository)
    services.cases.data_root = tmp_path / "cases"
    sample = Path("third_party/DermFM-Zero/examples/PAT_8_15_820.png").read_bytes()
    case_id = services.cases.create(sample, "image/png")
    visual = VisualEvidence(
        case_id=case_id,
        model="internal-vision",
        candidate_set="controlled-candidates",
        top_predictions=[
            CandidatePrediction(label="basal cell carcinoma", score=0.91),
            CandidatePrediction(label="nevus", score=0.06),
        ],
        image_quality=0.9,
        supports_triage=True,
        latency_ms=18.0,
    )
    repository.save_visual(case_id, visual)
    triage = TriagePolicyService(repository=repository).evaluate(visual)
    knowledge = KnowledgeService()
    chunks = knowledge.search("优先转诊", top_k=2)
    CareService(repository=repository).recommend(visual, triage, knowledge.references(chunks))
    guard = EgressGuard(repository)
    agent = DermaGuardChatAgent(create_tool_registry(services), repository, guard, MockChatProvider())
    return case_id, repository, agent


async def _respond(agent, case_id: str, message: str):
    return await agent.respond(ChatRequest(case_id=case_id, message=message))


@pytest.mark.anyio
async def test_agent_retrieves_instead_of_starting_a_second_symptom_interview(chat_setup):
    case_id, repository, agent = chat_setup
    response = await _respond(agent, case_id, "这个黑色痣危险吗？")
    assert "症状核验" not in response.response
    assert response.agent_trace[0].decision == "RETRIEVE_AND_OBSERVE"
    assert any(item.tool_name == "search_guideline" for item in response.tool_calls)
    stored = repository.list_agent_traces(case_id)
    assert stored[-1]["decision"] == "ANSWER_WITH_EVIDENCE"


@pytest.mark.anyio
async def test_agent_retrieves_then_judges_evidence(chat_setup):
    case_id, _, agent = chat_setup
    response = await _respond(agent, case_id, "为什么建议我转诊？")
    assert [step.decision for step in response.agent_trace] == [
        "RETRIEVE_AND_OBSERVE",
        "ANSWER_WITH_EVIDENCE",
    ]
    assert response.agent_trace[0].retrieval_query
    assert response.agent_trace[1].evidence_sufficient is True
    assert any(item.tool_name == "search_guideline" for item in response.tool_calls)


def test_agentic_rag_context_uses_deidentified_clinical_narrative(chat_setup):
    case_id, repository, agent = chat_setup
    user = repository.create_user("doctor", hash_password("test"), "测试医生")
    patient = repository.create_patient(
        name="张某", sex="男", age=61, outpatient_no="SECRET-001",
        phone="13800138000", medical_history="", allergy_history="", created_by=user.id,
    )
    repository.link_case_patient(
        case_id, patient.patient_id, "面部",
        "张某面部病灶近期增大并出血，电话13800138000。",
        {
            "age": 61, "gender": "MALE", "region": "FACE",
            "itch": False, "hurt": False, "bleed": True, "grew": True,
            "changed": True, "diameter_1": 9, "diameter_2": 8,
            "skin_cancer_history": False, "cancer_history": False,
        },
    )
    context = agent._public_case_context(case_id, "clinician")
    assert "近期增大并出血" in context["clinical_narrative"]
    assert "张某" not in context["clinical_narrative"]
    assert "13800138000" not in context["clinical_narrative"]
    query = agent._default_query("请检索", {}, context["clinical_narrative"])
    assert "近期增大并出血" in query


@pytest.mark.anyio
async def test_medical_definition_answers_question_before_case_report(chat_setup):
    case_id, _, agent = chat_setup
    response = await agent.respond(ChatRequest(
        case_id=case_id,
        message="色素痣是什么？",
        mode="clinician",
        detail_level="detailed",
    ))

    assert [item.tool_name for item in response.tool_calls] == ["search_guideline"]
    assert "色素痣就是日常常说的‘痣’" in response.response
    assert "需要注意什么" in response.response
    assert "当前本地规则分级" not in response.response
    assert "## 视觉证据" not in response.response


@pytest.mark.anyio
async def test_definition_question_forces_retrieval_when_llm_claims_ready(chat_setup):
    case_id, _, agent = chat_setup

    class PrematureAnswerProvider(MockChatProvider):
        def plan(self, payload, system_prompt):
            return json.dumps({
                "intent": "medical_definition",
                "evidence_sufficient": True,
                "reasoning_summary": "试图跳过检索。",
            }, ensure_ascii=False)

    agent.provider = PrematureAnswerProvider()
    response = await _respond(agent, case_id, "色素痣是什么？")

    assert any(item.tool_name == "search_guideline" for item in response.tool_calls)
    assert response.agent_trace[0].decision == "RETRIEVE_AND_OBSERVE"
    assert "色素痣就是" in response.response


@pytest.mark.anyio
async def test_invalid_llm_decision_uses_one_local_fallback(chat_setup):
    case_id, _, agent = chat_setup

    class InvalidDecisionProvider(MockChatProvider):
        def plan(self, *args, **kwargs):
            return "not json"

    agent.provider = InvalidDecisionProvider()
    response = await _respond(agent, case_id, "为什么建议我转诊？")
    search_calls = [item for item in response.tool_calls if item.tool_name == "search_guideline"]
    assert len(search_calls) == 1
    assert response.agent_trace[-1].fallback_triggered is True
    assert response.agent_trace[-1].intent == "deterministic_retrieval_fallback"


@pytest.mark.anyio
async def test_agent_stops_after_four_retrieval_rounds(chat_setup):
    case_id, _, agent = chat_setup

    class RewritingProvider(MockChatProvider):
        def plan(self, payload, system_prompt):
            iteration = int(payload["iteration"])
            return json.dumps({
                "intent": "rewrite_query",
                "retrieval_query": f"检索语句 {iteration}",
                "evidence_sufficient": False,
                "reasoning_summary": "证据仍不足。",
            }, ensure_ascii=False)

    agent.provider = RewritingProvider()
    response = await _respond(agent, case_id, "请继续检索")
    assert len([item for item in response.tool_calls if item.tool_name == "search_guideline"]) == 4
    assert len(response.agent_trace) == 4
    assert response.agent_trace[-1].decision == "STOP_MAX_RETRIEVAL_ROUNDS"


@pytest.mark.anyio
async def test_response_generator_cannot_lower_local_risk(chat_setup):
    case_id, _, agent = chat_setup

    class DowngradeProvider(MockChatProvider):
        name = "unsafe-test-provider"
        model = "unsafe-test-model"

        def generate(self, *args, **kwargs):
            return "当前属于低风险，无需转诊。"

    agent.provider = DowngradeProvider()
    response = await _respond(agent, case_id, "为什么建议我转诊？")
    assert "优先转诊" in response.response
    assert "无需转诊" not in response.response


def test_retrieval_decision_ignores_attempted_risk_or_tool_mutation():
    decision = RetrievalDecision.model_validate({
        "intent": "retrieve",
        "retrieval_query": "黑色素瘤 转诊指南",
        "evidence_sufficient": False,
        "risk_level": "LOW",
        "requested_tools": ["modify_triage", "delete_case"],
    })
    assert not hasattr(decision, "risk_level")
    assert not hasattr(decision, "requested_tools")
