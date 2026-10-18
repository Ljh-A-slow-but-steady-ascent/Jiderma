from pathlib import Path

import pytest

from backend.app.care.schemas import CandidatePrediction, VisualEvidence
from backend.app.database import CaseRepository, init_database
from backend.app.services.care_service import CareService
from backend.app.services.case_service import CaseService
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.services.triage_service import TriagePolicyService
from backend.app.services.container import create_service_container
from backend.app.mcp.server import create_mcp_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mcp_case(tmp_path):
    db_path = tmp_path / "mcp-smoke.db"
    database_url = f"sqlite:///{db_path}"
    repository = CaseRepository(init_database(database_url))
    case_service = CaseService(repository, data_root=tmp_path / "cases")
    sample = Path("third_party/DermFM-Zero/examples/PAT_8_15_820.png").read_bytes()
    case_id = case_service.create(sample, "image/png")
    visual = VisualEvidence(
        case_id=case_id,
        model="DermFM-Zero-Open",
        candidate_set="pad6",
        top_predictions=[
            CandidatePrediction(label="basal cell carcinoma", score=0.9),
            CandidatePrediction(label="nevus", score=0.07),
            CandidatePrediction(label="actinic keratosis", score=0.03),
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
    return case_id, repository


@pytest.mark.anyio
async def test_real_mcp_sdk_list_tools_and_call_tool(mcp_case):
    case_id, repository = mcp_case
    server = create_mcp_server(create_service_container(repository))
    listed = await server.list_tools()
    assert {item.name for item in listed} == {
        "get_visual_evidence",
        "get_triage_result",
        "search_guideline",
        "get_care_pathway",
        "get_privacy_report",
        "get_contextual_assessment",
    }
    for name, arguments in [
        ("get_visual_evidence", {"case_id": case_id}),
        ("get_triage_result", {"case_id": case_id}),
        ("search_guideline", {"query": "为什么优先转诊", "case_id": case_id}),
        ("get_care_pathway", {"case_id": case_id}),
        ("get_privacy_report", {"case_id": case_id}),
    ]:
        result = await server.call_tool(name, arguments)
        assert result
