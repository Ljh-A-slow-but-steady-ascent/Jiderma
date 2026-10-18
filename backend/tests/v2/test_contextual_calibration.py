from pathlib import Path

import httpx
import pytest

from backend.app.api.v2_routes import create_v2_runtime, get_runtime
from backend.app.database import CaseRepository, init_database
from backend.app.main import app
from backend.app.services.container import create_service_container


class LowRiskRunner:
    def predict(self, image_path: Path) -> dict:
        return {
            "model_name": "DermFM-Zero-Open",
            "top_predictions": [
                {"label": "nevus", "score": 0.82},
                {"label": "seborrheic keratosis", "score": 0.12},
                {"label": "actinic keratosis", "score": 0.06},
            ],
            "latency_ms": 12.0,
        }


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def contextual_client(tmp_path):
    repository = CaseRepository(init_database("sqlite+pysqlite:///:memory:"))
    services = create_service_container(repository)
    services.cases.data_root = tmp_path / "cases"
    services.visual.runner = LowRiskRunner()
    test_runtime = create_v2_runtime(services)

    async def override_runtime():
        return test_runtime

    app.dependency_overrides[get_runtime] = override_runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def _create_analyzed_case(client):
    image = Path("third_party/DermFM-Zero/examples/PAT_8_15_820.png").read_bytes()
    created = await client.post(
        "/v1/cases", files={"image": ("lesion.png", image, "image/png")}
    )
    case_id = created.json()["case_id"]
    analyzed = await client.post(f"/v1/cases/{case_id}/analyze")
    assert analyzed.json()["triage"]["level"] == "LOCAL_REVIEW"
    return case_id


@pytest.mark.anyio
async def test_structured_followup_rag_and_local_escalation(contextual_client):
    case_id = await _create_analyzed_case(contextual_client)
    plan_response = await contextual_client.post(
        f"/v1/cases/{case_id}/contextual-intake",
        json={
            "duration": "over_month",
            "pain": False,
            "pruritus": False,
            "fever": False,
            "rapid_spread": False,
            "model": "auto",
        },
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    allowed = {"DERM_Q101", "DERM_Q102", "DERM_Q103", "DERM_Q104", "DERM_Q105"}
    assert 2 <= len(plan["questions"]) <= 4
    assert {item["id"] for item in plan["questions"]} <= allowed
    assert plan["rag_references"]
    assert plan["raw_image_sent_to_cloud"] is False
    assert plan["decision_still_local"] is True

    answers = [
        {"question_id": item["id"], "answer": item["id"] in {"DERM_Q101", "DERM_Q103"}}
        for item in plan["questions"]
    ]
    calibrated = await contextual_client.post(
        f"/v1/cases/{case_id}/contextual-calibration", json={"answers": answers}
    )
    assert calibrated.status_code == 200, calibrated.text
    result = calibrated.json()
    assert result["visual_triage_level"] == "LOCAL_REVIEW"
    assert result["contextual_triage_level"] in {"REFERRAL", "PRIORITY_REFERRAL"}
    assert result["risk_changed"] is True
    assert result["red_flags"]
    assert result["calibration_policy_version"] == "visual-baseline-redflag-v2"
    assert result["cloud_influenced_decision"] is False
    assert result["visual_scores_modified"] is False
    assert result["rag_references"]

    chat = await contextual_client.post(
        "/v1/chat",
        json={"case_id": case_id, "message": "为什么现在建议转诊？", "mode": "patient"},
    )
    assert chat.status_code == 200
    assert any(
        item["tool_name"] == "get_contextual_assessment" for item in chat.json()["tool_calls"]
    )


@pytest.mark.anyio
async def test_context_never_lowers_visual_triage(contextual_client):
    case_id = await _create_analyzed_case(contextual_client)
    plan = (
        await contextual_client.post(
            f"/v1/cases/{case_id}/contextual-intake",
            json={
                "duration": "1_3_days",
                "pain": False,
                "pruritus": False,
                "fever": False,
                "rapid_spread": False,
                "model": "auto",
            },
        )
    ).json()
    result = (
        await contextual_client.post(
            f"/v1/cases/{case_id}/contextual-calibration",
            json={
                "answers": [
                    {"question_id": item["id"], "answer": False}
                    for item in plan["questions"]
                ]
            },
        )
    ).json()
    rank = {"RETAKE": 0, "LOCAL_REVIEW": 1, "REFERRAL": 2, "PRIORITY_REFERRAL": 3}
    assert rank[result["contextual_triage_level"]] >= rank[result["visual_triage_level"]]
    assert result["contextual_triage_level"] == "LOCAL_REVIEW"
    assert result["red_flags"] == []
