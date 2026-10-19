from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.app.care.schemas import CarePathway, ClinicalMetadata, TriageDecision, VisualEvidence
from backend.app.auth import require_user
from backend.app.chat import (
    ChatRequest,
    ChatResponse,
    DermaGuardChatAgent,
    chat_model_catalog,
)
from backend.app.mcp.factory import create_tool_registry
from backend.app.services.container import ServiceContainer, create_service_container
from backend.app.services.clinical_extraction_service import field_labels
from backend.app.services.privacy import EgressGuard, EgressRequest
from backend.app.services.privacy_service import PrivacyReport
from backend.app.services.report_service import ReportService


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCreated(StrictModel):
    case_id: str
    mode: Literal["patient", "clinician"]
    retention_mode: Literal["session", "local"]
    raw_image_local_only: bool = True


class PatientCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    sex: Literal["男", "女", "其他"]
    age: int = Field(ge=0, le=130)
    outpatient_no: str = Field(min_length=1, max_length=80)
    phone: str = Field(default="", max_length=40)
    medical_history: str = Field(default="", max_length=3000)
    allergy_history: str = Field(default="", max_length=2000)


class ClinicalExtractionRequest(StrictModel):
    narrative: str = Field(min_length=10, max_length=5000)
    age: int = Field(ge=0, le=130)
    gender: Literal["MALE", "FEMALE"]
    patient_name: str = Field(default="", max_length=120)
    outpatient_no: str = Field(default="", max_length=80)
    phone: str = Field(default="", max_length=40)
    model: Literal[
        "auto", "glm-5.3-flash", "glm-4-flash", "openai/gpt-oss-120b",
        "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "gemini-flash",
    ] = "auto"


class ClinicalExtractionResponse(StrictModel):
    metadata: dict[str, Any]
    missing_fields: list[str]
    missing_field_labels: list[str]
    uncertain_fields: list[str]
    provider: str
    model: str
    privacy_status: Literal["SAFE"] = "SAFE"
    sanitized_fields: list[str] = Field(default_factory=list)


class ReportGenerateRequest(StrictModel):
    model: str = Field(default="local-template", max_length=120)


class ReportUpdateRequest(StrictModel):
    content: str = Field(min_length=1, max_length=50_000)
    status: Literal["draft", "final"] = "final"


class PerformanceMetrics(StrictModel):
    vision_model_latency_ms: float = Field(ge=0)
    visual_stage_wall_ms: float = Field(ge=0)
    triage_latency_ms: float = Field(ge=0)
    rag_latency_ms: float = Field(ge=0)
    care_pathway_latency_ms: float = Field(ge=0)
    total_pretriage_latency_ms: float = Field(ge=0)


class AnalysisResult(StrictModel):
    case_id: str
    visual: VisualEvidence
    triage: TriageDecision
    care_pathway: CarePathway
    guidelines: list[dict[str, Any]]
    privacy: PrivacyReport
    performance: PerformanceMetrics


@dataclass
class V2Runtime:
    services: ServiceContainer
    guard: EgressGuard
    agent: DermaGuardChatAgent


def create_v2_runtime(services: ServiceContainer | None = None) -> V2Runtime:
    services = services or create_service_container()
    guard = EgressGuard(services.repository)
    registry = create_tool_registry(services)
    return V2Runtime(
        services=services,
        guard=guard,
        agent=DermaGuardChatAgent(registry, services.repository, guard),
    )


runtime = create_v2_runtime()
router = APIRouter(prefix="/v1", dependencies=[Depends(require_user)])


async def get_runtime() -> V2Runtime:
    return runtime


Runtime = Annotated[V2Runtime, Depends(get_runtime)]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _positive_symptoms(profile: ClinicalMetadata) -> list[str]:
    names = {
        "瘙痒": profile.itch,
        "疼痛": profile.hurt,
        "出血": profile.bleed,
        "近期增大": profile.grew,
        "外观变化": profile.changed,
        "皮肤肿瘤史": profile.skin_cancer_history,
        "其他肿瘤史": profile.cancer_history,
    }
    return [name for name, active in names.items() if active]


@router.post("/clinical-metadata/extract", response_model=ClinicalExtractionResponse)
async def extract_clinical_metadata(
    payload: ClinicalExtractionRequest, app: Runtime
) -> ClinicalExtractionResponse:
    try:
        result = app.services.clinical_extraction.extract(
            narrative=payload.narrative.strip(),
            age=payload.age,
            gender=payload.gender,
            model_id=payload.model,
            identity_values=[payload.patient_name, payload.outpatient_no, payload.phone],
        )
        return ClinicalExtractionResponse(
            metadata=result.metadata,
            missing_fields=result.missing_fields,
            missing_field_labels=field_labels(result.missing_fields),
            uncertain_fields=result.uncertain_fields,
            provider=result.provider,
            model=result.model,
            privacy_status="SAFE",
            sanitized_fields=result.sanitized_fields,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/cases", response_model=CaseCreated)
async def create_case(
    app: Runtime,
    image: UploadFile = File(...),
    mode: Literal["patient", "clinician"] = Form("clinician"),
    retention_mode: Literal["session", "local"] = Form("local"),
    patient_id: str | None = Form(default=None),
    lesion_site: str = Form(default="未填写"),
    chief_complaint: str = Form(default="未填写"),
    clinical_metadata_json: str = Form(default=""),
) -> CaseCreated:
    try:
        if not patient_id and os.getenv("DERMAGUARD_AUTH_DISABLED", "0") != "1":
            raise ValueError("图像分析前必须先关联患者信息")
        profile: ClinicalMetadata | None = None
        if patient_id:
            patient = app.services.repository.get_patient(patient_id)
            if patient is None:
                raise KeyError(f"patient not found: {patient_id}")
            if not clinical_metadata_json.strip():
                raise ValueError("请在图像分析前完整填写结构化病例信息")
            profile = ClinicalMetadata.model_validate(json.loads(clinical_metadata_json))
            expected_gender = {"男": "MALE", "女": "FEMALE"}.get(patient.sex)
            if expected_gender is None:
                raise ValueError("当前多模态模型的官方病例格式仅接受男性或女性")
            if profile.age != patient.age or profile.gender != expected_gender:
                raise ValueError("结构化病例的年龄或性别与患者档案不一致")
        content = await image.read(10 * 1024 * 1024 + 1)
        case_id = app.services.cases.create(
            content,
            image.content_type or "application/octet-stream",
            mode=mode,
            retention_mode=retention_mode,
        )
        if patient_id:
            assert profile is not None
            app.services.repository.link_case_patient(
                case_id,
                patient_id,
                lesion_site.strip() or "未填写",
                chief_complaint.strip() or "未填写",
                profile.model_dump(mode="json"),
            )
        return CaseCreated(case_id=case_id, mode=mode, retention_mode=retention_mode)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/patients")
async def create_patient(payload: PatientCreate, app: Runtime, user: dict = Depends(require_user)) -> dict[str, Any]:
    try:
        patient = app.services.repository.create_patient(
            name=payload.name.strip(), sex=payload.sex, age=payload.age,
            outpatient_no=payload.outpatient_no.strip(), phone=payload.phone.strip() or None,
            medical_history=payload.medical_history.strip(), allergy_history=payload.allergy_history.strip(),
            created_by=int(user["id"]),
        )
        return app.services.repository.patient_public(patient)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/patients")
async def list_patients(app: Runtime, query: str = Query(default="", max_length=120)) -> list[dict[str, Any]]:
    return app.services.repository.list_patients(query=query)


@router.get("/cases/{case_id}/patient")
async def get_case_patient(case_id: str, app: Runtime) -> dict[str, Any]:
    patient = app.services.repository.get_case_patient(case_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="该病例尚未关联患者")
    return patient


@router.get("/cases/{case_id}/image")
async def get_case_image(case_id: str, app: Runtime) -> Response:
    try:
        path = app.services.cases.get_local_image_path(case_id)
        media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
        return Response(path.read_bytes(), media_type=media_type)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/cases/{case_id}/analyze", response_model=AnalysisResult)
async def analyze_case(case_id: str, app: Runtime) -> AnalysisResult:
    total_started = time.perf_counter()
    try:
        visual_started = time.perf_counter()
        case_patient = app.services.repository.get_case_patient(case_id)
        if case_patient is None:
            raise ValueError("多模态分析前必须关联患者和结构化病例")
        profile = ClinicalMetadata.model_validate(case_patient.get("clinical_profile"))
        visual = app.services.visual.analyze(case_id, clinical_metadata=profile)
        visual_wall = (time.perf_counter() - visual_started) * 1000

        triage_started = time.perf_counter()
        triage = app.services.triage.evaluate(visual)
        triage_latency = (time.perf_counter() - triage_started) * 1000

        rag_started = time.perf_counter()
        visual_candidates = [item.label for item in visual.top_predictions[:3]]
        guidelines = app.services.knowledge.search_patient_context(
            user_query=case_patient.get("chief_complaint", "皮肤病灶辅助鉴别"),
            visual_candidates=visual_candidates,
            positive_symptoms=_positive_symptoms(profile),
            risk_reasons=[triage.level.value, *triage.reason_codes],
            topic="支持依据 冲突依据 鉴别要点 检查依据 转诊依据",
            top_k=5,
        )
        rag_latency = (time.perf_counter() - rag_started) * 1000

        care_started = time.perf_counter()
        case_record = app.services.repository.get_case(case_id)
        care = app.services.care.recommend(
            visual,
            triage,
            app.services.knowledge.references(guidelines),
            mode="patient" if case_record is None else case_record.mode,
        )
        care_latency = (time.perf_counter() - care_started) * 1000
        privacy = app.services.privacy.report(case_id)
        return AnalysisResult(
            case_id=case_id,
            visual=visual,
            triage=triage,
            care_pathway=care,
            guidelines=guidelines,
            privacy=privacy,
            performance=PerformanceMetrics(
                vision_model_latency_ms=visual.latency_ms,
                visual_stage_wall_ms=visual_wall,
                triage_latency_ms=triage_latency,
                rag_latency_ms=rag_latency,
                care_pathway_latency_ms=care_latency,
                total_pretriage_latency_ms=(time.perf_counter() - total_started) * 1000,
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/cases/{case_id}/visual", response_model=VisualEvidence)
async def get_visual(case_id: str, app: Runtime) -> VisualEvidence:
    try:
        return app.services.visual.get(case_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/cases/{case_id}/triage", response_model=TriageDecision)
async def get_triage(case_id: str, app: Runtime) -> TriageDecision:
    try:
        return app.services.triage.get(case_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/cases/{case_id}/care-pathway", response_model=CarePathway)
async def get_care_pathway(case_id: str, app: Runtime) -> CarePathway:
    try:
        return app.services.care.get(case_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/cases/{case_id}/privacy", response_model=PrivacyReport)
async def get_privacy(case_id: str, app: Runtime) -> PrivacyReport:
    try:
        return app.services.privacy.report(case_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/cases/{case_id}/cloud-payload")
async def view_cloud_payload(case_id: str, app: Runtime) -> dict[str, Any]:
    try:
        payload = {
            "visual_evidence": app.services.visual.get(case_id).model_dump(mode="json"),
            "triage_result": app.services.triage.get(case_id).model_dump(mode="json"),
            "care_pathway": app.services.care.get(case_id).model_dump(mode="json"),
        }
        patient = app.services.repository.get_case_patient(case_id)
        if patient and patient.get("clinical_profile"):
            payload["clinical_profile"] = patient["clinical_profile"]
        decision = app.guard.enforce(
            EgressRequest(
                channel="llm",
                destination="cloud_payload_preview",
                payload=payload,
                case_id=case_id,
            )
        )
        return {
            "payload": decision.sanitized_payload,
            "raw_image_included": False,
            "patient_identity_included": False,
            "egress_latency_ms": decision.latency_ms,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, app: Runtime) -> ChatResponse:
    try:
        return await app.agent.respond(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/chat/models")
async def chat_models() -> list[dict[str, Any]]:
    return chat_model_catalog()


@router.get("/cases/{case_id}/chat-history")
async def chat_history(case_id: str, app: Runtime) -> list[dict[str, Any]]:
    if app.services.repository.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="病例不存在")
    return app.services.repository.list_chat_messages(case_id)


@router.get("/cases/{case_id}/agent-traces")
async def agent_traces(case_id: str, app: Runtime) -> list[dict[str, Any]]:
    if app.services.repository.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="病例不存在")
    return app.services.repository.list_agent_traces(case_id)


@router.delete("/cases/{case_id}/chat-history")
async def clear_chat_history(case_id: str, app: Runtime) -> dict[str, int]:
    if app.services.repository.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="病例不存在")
    return {"deleted": app.services.repository.clear_chat_messages(case_id)}


@router.post("/cases/{case_id}/reports")
async def generate_report(
    case_id: str,
    request: ReportGenerateRequest,
    app: Runtime,
    user: dict = Depends(require_user),
) -> dict[str, Any]:
    try:
        patient = app.services.repository.get_case_patient(case_id)
        if patient is None:
            raise KeyError("该病例尚未关联患者")
        clinical_payload = {
            "visual": app.services.repository.get_visual(case_id) or {},
            "triage": app.services.repository.get_triage(case_id) or {},
            "care_pathway": app.services.repository.get_care_pathway(case_id) or {},
            "clinical_profile": patient.get("clinical_profile", {}),
        }
        generated = ReportService(app.guard).generate(
            case_id=case_id,
            patient=patient,
            clinical_payload=clinical_payload,
            model_id=request.model,
        )
        record = app.services.repository.create_report(
            case_id=case_id,
            patient_id=patient["patient_id"],
            content=generated.content,
            structured=generated.structured,
            provider=generated.provider,
            model=generated.model,
            created_by=int(user["id"]),
        )
        report = app.services.repository.get_report(record.report_id)
        if report is None:
            raise RuntimeError("报告保存失败")
        return report
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/reports")
async def list_reports(app: Runtime, query: str = Query(default="", max_length=120)) -> list[dict[str, Any]]:
    return app.services.repository.list_reports(query=query)


@router.get("/reports/{report_id}")
async def get_report(report_id: str, app: Runtime) -> dict[str, Any]:
    report = app.services.repository.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.put("/reports/{report_id}")
async def update_report(
    report_id: str,
    request: ReportUpdateRequest,
    app: Runtime,
    user: dict = Depends(require_user),
) -> dict[str, Any]:
    try:
        return app.services.repository.update_report(
            report_id, request.content, int(user["id"]), request.status
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/reports/{report_id}")
async def delete_report(report_id: str, app: Runtime) -> dict[str, Any]:
    if not app.services.repository.delete_report(report_id):
        raise HTTPException(status_code=404, detail="报告不存在")
    return {"status": "deleted", "report_id": report_id, "case_and_image_retained": True}


@router.get("/reports/{report_id}/image")
async def get_report_image(report_id: str, app: Runtime) -> Response:
    report = app.services.repository.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    path = app.services.cases.get_local_image_path(report["case_id"])
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
    return Response(path.read_bytes(), media_type=media_type)


@router.get("/reports/{report_id}/download")
async def download_report(report_id: str, app: Runtime) -> PlainTextResponse:
    report = app.services.repository.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return PlainTextResponse(
        report["content"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={report['report_id']}.md"},
    )


@router.get("/audit")
async def audit(app: Runtime, case_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return app.services.repository.list_audit_events(case_id)
