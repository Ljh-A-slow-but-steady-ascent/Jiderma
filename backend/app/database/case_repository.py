from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Type
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.app.database.models import (
    AgentTraceRecord,
    AuthSessionRecord,
    AuditEventRecord,
    CarePathwayRecord,
    CaseRecord,
    CasePatientRecord,
    ChatMessageRecord,
    ContextualRecord,
    PatientRecord,
    ReportRecord,
    ReportRevisionRecord,
    ToolCallRecord,
    TriageResultRecord,
    UserRecord,
    VisualResultRecord,
)
from backend.app.database.repository import init_database


class CaseRepository:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or init_database()
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _json(value: Any) -> str:
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        return json.dumps(value, ensure_ascii=False)

    def create_case(
        self,
        case_id: str,
        local_image_path: str,
        image_sha256: str,
        retention_mode: str,
        mode: str,
    ) -> None:
        with self.sessions.begin() as db:
            db.add(
                CaseRecord(
                    case_id=case_id,
                    local_image_path=local_image_path,
                    image_sha256=image_sha256,
                    retention_mode=retention_mode,
                    mode=mode,
                )
            )

    @staticmethod
    def user_public(user: UserRecord) -> dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
        }

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self.sessions() as db:
            return db.scalar(select(UserRecord).where(UserRecord.username == username))

    def create_user(self, username: str, password_hash: str, full_name: str) -> UserRecord:
        with self.sessions.begin() as db:
            user = UserRecord(
                username=username,
                password_hash=password_hash,
                full_name=full_name,
                role="clinician",
            )
            db.add(user)
            db.flush()
            return user

    def create_auth_session(self, token_hash: str, user_id: int, expires_at: datetime) -> None:
        with self.sessions.begin() as db:
            db.add(AuthSessionRecord(token_hash=token_hash, user_id=user_id, expires_at=expires_at))

    def get_session_user(self, token_hash: str, now: datetime) -> UserRecord | None:
        with self.sessions() as db:
            session = db.get(AuthSessionRecord, token_hash)
            if session is None or session.expires_at <= now:
                return None
            user = db.get(UserRecord, session.user_id)
            return user if user is not None and user.active else None

    def delete_auth_session(self, token_hash: str) -> None:
        with self.sessions.begin() as db:
            db.execute(delete(AuthSessionRecord).where(AuthSessionRecord.token_hash == token_hash))

    def create_patient(
        self,
        *,
        name: str,
        sex: str,
        age: int,
        outpatient_no: str,
        phone: str | None,
        medical_history: str,
        allergy_history: str,
        created_by: int,
    ) -> PatientRecord:
        patient_id = f"PAT_{uuid4().hex[:12]}"
        with self.sessions.begin() as db:
            existing = db.scalar(select(PatientRecord).where(PatientRecord.outpatient_no == outpatient_no))
            if existing is not None:
                existing.name = name
                existing.sex = sex
                existing.age = age
                existing.phone = phone
                existing.medical_history = medical_history
                existing.allergy_history = allergy_history
                return existing
            patient = PatientRecord(
                patient_id=patient_id,
                name=name,
                sex=sex,
                age=age,
                outpatient_no=outpatient_no,
                phone=phone,
                medical_history=medical_history,
                allergy_history=allergy_history,
                created_by=created_by,
            )
            db.add(patient)
            db.flush()
            return patient

    def get_patient(self, patient_id: str) -> PatientRecord | None:
        with self.sessions() as db:
            return db.get(PatientRecord, patient_id)

    def list_patients(self, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        with self.sessions() as db:
            statement = select(PatientRecord).order_by(PatientRecord.updated_at.desc()).limit(limit)
            if query.strip():
                pattern = f"%{query.strip()}%"
                statement = statement.where(
                    PatientRecord.name.like(pattern) | PatientRecord.outpatient_no.like(pattern)
                )
            return [self.patient_public(item) for item in db.scalars(statement).all()]

    @staticmethod
    def patient_public(item: PatientRecord) -> dict[str, Any]:
        return {
            "patient_id": item.patient_id,
            "name": item.name,
            "sex": item.sex,
            "age": item.age,
            "outpatient_no": item.outpatient_no,
            "phone": item.phone or "",
            "medical_history": item.medical_history,
            "allergy_history": item.allergy_history,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

    def link_case_patient(self, case_id: str, patient_id: str, lesion_site: str, chief_complaint: str) -> None:
        with self.sessions.begin() as db:
            db.add(CasePatientRecord(
                case_id=case_id,
                patient_id=patient_id,
                lesion_site=lesion_site,
                chief_complaint=chief_complaint,
            ))

    def get_case_patient(self, case_id: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            link = db.get(CasePatientRecord, case_id)
            if link is None:
                return None
            patient = db.get(PatientRecord, link.patient_id)
            if patient is None:
                return None
            result = self.patient_public(patient)
            result.update({"case_id": case_id, "lesion_site": link.lesion_site, "chief_complaint": link.chief_complaint})
            return result

    def create_report(
        self,
        *, case_id: str, patient_id: str, content: str, structured: dict[str, Any],
        provider: str, model: str, created_by: int,
    ) -> ReportRecord:
        report_id = f"RPT_{uuid4().hex[:12]}"
        filename = f"{patient_id}-{report_id[-6:]}-辅助诊断报告.md"
        with self.sessions.begin() as db:
            report = ReportRecord(
                report_id=report_id,
                case_id=case_id,
                patient_id=patient_id,
                filename=filename,
                content=content,
                structured_json=self._json(structured),
                provider=provider,
                model=model,
                created_by=created_by,
            )
            db.add(report)
            db.add(ReportRevisionRecord(
                report_id=report_id, content=content, editor_user_id=created_by
            ))
            db.flush()
            return report

    def list_reports(self, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        with self.sessions() as db:
            statement = select(ReportRecord).order_by(ReportRecord.updated_at.desc()).limit(limit)
            records = db.scalars(statement).all()
            output = []
            for item in records:
                patient = db.get(PatientRecord, item.patient_id)
                if query.strip() and patient is not None:
                    needle = query.strip().lower()
                    if needle not in patient.name.lower() and needle not in patient.outpatient_no.lower() and needle not in item.filename.lower():
                        continue
                output.append(self._report_public(item, patient))
            return output

    @staticmethod
    def _report_public(item: ReportRecord, patient: PatientRecord | None = None) -> dict[str, Any]:
        return {
            "report_id": item.report_id,
            "case_id": item.case_id,
            "patient_id": item.patient_id,
            "patient_name": patient.name if patient else "",
            "outpatient_no": patient.outpatient_no if patient else "",
            "filename": item.filename,
            "content": item.content,
            "structured": json.loads(item.structured_json or "{}"),
            "provider": item.provider,
            "model": item.model,
            "status": item.status,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            item = db.get(ReportRecord, report_id)
            if item is None:
                return None
            return self._report_public(item, db.get(PatientRecord, item.patient_id))

    def update_report(self, report_id: str, content: str, editor_user_id: int, status: str = "final") -> dict[str, Any]:
        with self.sessions.begin() as db:
            item = db.get(ReportRecord, report_id)
            if item is None:
                raise KeyError(f"report not found: {report_id}")
            item.content = content
            item.status = status
            item.updated_at = datetime.utcnow()
            db.add(ReportRevisionRecord(report_id=report_id, content=content, editor_user_id=editor_user_id))
            db.flush()
            return self._report_public(item, db.get(PatientRecord, item.patient_id))

    def delete_report(self, report_id: str) -> bool:
        with self.sessions.begin() as db:
            db.execute(delete(ReportRevisionRecord).where(ReportRevisionRecord.report_id == report_id))
            result = db.execute(delete(ReportRecord).where(ReportRecord.report_id == report_id))
            return bool(result.rowcount)

    def get_case(self, case_id: str) -> CaseRecord | None:
        with self.sessions() as db:
            return db.get(CaseRecord, case_id)

    def _upsert_result(self, model: Type, case_id: str, result: BaseModel) -> None:
        with self.sessions.begin() as db:
            record = db.scalar(select(model).where(model.case_id == case_id))
            if record is None:
                record = model(case_id=case_id, result_json=result.model_dump_json())
                db.add(record)
            else:
                record.result_json = result.model_dump_json()

    def _get_result(self, model: Type, case_id: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            record = db.scalar(select(model).where(model.case_id == case_id))
            return None if record is None else json.loads(record.result_json)

    def save_visual(self, case_id: str, result: BaseModel) -> None:
        self._upsert_result(VisualResultRecord, case_id, result)

    def get_visual(self, case_id: str) -> dict[str, Any] | None:
        return self._get_result(VisualResultRecord, case_id)

    def save_triage(self, case_id: str, result: BaseModel) -> None:
        self._upsert_result(TriageResultRecord, case_id, result)

    def get_triage(self, case_id: str) -> dict[str, Any] | None:
        return self._get_result(TriageResultRecord, case_id)

    def save_care_pathway(self, case_id: str, result: BaseModel) -> None:
        self._upsert_result(CarePathwayRecord, case_id, result)

    def get_care_pathway(self, case_id: str) -> dict[str, Any] | None:
        return self._get_result(CarePathwayRecord, case_id)

    def _save_context_field(self, case_id: str, field: str, value: BaseModel) -> None:
        with self.sessions.begin() as db:
            record = db.scalar(select(ContextualRecord).where(ContextualRecord.case_id == case_id))
            if record is None:
                record = ContextualRecord(case_id=case_id)
                db.add(record)
            setattr(record, field, value.model_dump_json())

    def _get_context_field(self, case_id: str, field: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            record = db.scalar(select(ContextualRecord).where(ContextualRecord.case_id == case_id))
            raw = None if record is None else getattr(record, field)
            return None if raw is None else json.loads(raw)

    def save_context_intake(self, case_id: str, value: BaseModel) -> None:
        self._save_context_field(case_id, "intake_json", value)

    def get_context_intake(self, case_id: str) -> dict[str, Any] | None:
        return self._get_context_field(case_id, "intake_json")

    def save_verification_plan(self, case_id: str, value: BaseModel) -> None:
        self._save_context_field(case_id, "plan_json", value)

    def get_verification_plan(self, case_id: str) -> dict[str, Any] | None:
        return self._get_context_field(case_id, "plan_json")

    def save_contextual_assessment(self, case_id: str, value: BaseModel) -> None:
        self._save_context_field(case_id, "result_json", value)

    def get_contextual_assessment(self, case_id: str) -> dict[str, Any] | None:
        return self._get_context_field(case_id, "result_json")

    def add_chat_message(self, case_id: str, role: str, message: str, tool_calls: list[dict]) -> None:
        with self.sessions.begin() as db:
            db.add(
                ChatMessageRecord(
                    case_id=case_id,
                    role=role,
                    sanitized_message=message,
                    tool_calls_json=self._json(tool_calls),
                )
            )

    def list_chat_messages(self, case_id: str) -> list[dict[str, Any]]:
        with self.sessions() as db:
            records = db.scalars(
                select(ChatMessageRecord)
                .where(ChatMessageRecord.case_id == case_id)
                .order_by(ChatMessageRecord.id)
            ).all()
            return [
                {
                    "role": item.role,
                    "message": item.sanitized_message,
                    "tool_calls": json.loads(item.tool_calls_json),
                    "timestamp": item.created_at.isoformat(),
                }
                for item in records
            ]

    def clear_chat_messages(self, case_id: str) -> int:
        with self.sessions.begin() as db:
            result = db.execute(
                delete(ChatMessageRecord).where(ChatMessageRecord.case_id == case_id)
            )
            return int(result.rowcount or 0)

    def add_tool_call(
        self,
        case_id: str | None,
        tool_name: str,
        arguments: dict,
        result: dict,
        success: bool,
        latency_ms: float,
    ) -> None:
        with self.sessions.begin() as db:
            db.add(
                ToolCallRecord(
                    case_id=case_id,
                    tool_name=tool_name,
                    arguments_json=self._json(arguments),
                    result_json=self._json(result),
                    success=success,
                    latency_ms=round(latency_ms),
                )
            )

    def add_agent_trace(self, case_id: str, step: int, trace: dict[str, Any]) -> None:
        with self.sessions.begin() as db:
            db.add(
                AgentTraceRecord(
                    case_id=case_id,
                    step=step,
                    trace_json=self._json(trace),
                )
            )

    def list_agent_traces(self, case_id: str) -> list[dict[str, Any]]:
        with self.sessions() as db:
            records = db.scalars(
                select(AgentTraceRecord)
                .where(AgentTraceRecord.case_id == case_id)
                .order_by(AgentTraceRecord.id)
            ).all()
            return [json.loads(item.trace_json) for item in records]

    def add_audit_event(self, event: dict[str, Any]) -> None:
        with self.sessions.begin() as db:
            db.add(
                AuditEventRecord(
                    event_type=event["event_type"],
                    case_id=event.get("case_id"),
                    channel=event["channel"],
                    tool_name=event.get("tool_name"),
                    destination=event["destination"],
                    privacy_action=event["privacy_action"],
                    allowed=event["allowed"],
                    sanitized_fields_json=self._json(event.get("sanitized_fields", [])),
                    latency_ms=round(event.get("latency_ms", 0)),
                )
            )

    def list_audit_events(self, case_id: str | None = None) -> list[dict[str, Any]]:
        with self.sessions() as db:
            query = select(AuditEventRecord).order_by(AuditEventRecord.id)
            if case_id:
                query = query.where(AuditEventRecord.case_id == case_id)
            return [
                {
                    "event_type": item.event_type,
                    "case_id": item.case_id,
                    "channel": item.channel,
                    "tool_name": item.tool_name,
                    "destination": item.destination,
                    "privacy_action": item.privacy_action,
                    "allowed": item.allowed,
                    "sanitized_fields": json.loads(item.sanitized_fields_json),
                    "latency_ms": item.latency_ms,
                    "timestamp": item.created_at.isoformat(),
                }
                for item in db.scalars(query).all()
            ]
