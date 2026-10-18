from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.app.care.schemas import CarePathwayLevel, TriageDecision, VisualEvidence
from backend.app.contextual.schemas import (
    ContextualAssessment,
    ContextualIntakeRequest,
    ContextualVerificationRequest,
    VerificationPlan,
    VerificationQuestion,
)
from backend.app.database import CaseRepository
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.services.privacy import EgressGuard, EgressRequest

if TYPE_CHECKING:
    from backend.app.chat.mock import ChatProvider


QUESTION_BANK = Path(__file__).resolve().parent.parent / "knowledge" / "question_bank.json"
LEVEL_RANK = {
    CarePathwayLevel.RETAKE: 0,
    CarePathwayLevel.LOCAL_REVIEW: 1,
    CarePathwayLevel.REFERRAL: 2,
    CarePathwayLevel.PRIORITY_REFERRAL: 3,
}


class ContextualCalibrationService:
    """Structured context workflow. Cloud may rank questions; local policy owns decisions."""

    def __init__(self, repository: CaseRepository, knowledge: KnowledgeService) -> None:
        self.repository = repository
        self.knowledge = knowledge
        entries = json.loads(QUESTION_BANK.read_text(encoding="utf-8"))
        self.questions = {item["id"]: VerificationQuestion.model_validate(item) for item in entries}

    @staticmethod
    def _default_question_ids(visual: VisualEvidence, intake: ContextualIntakeRequest) -> list[str]:
        high_risk = {
            "melanoma",
            "basal cell carcinoma",
            "squamous cell carcinoma",
            "actinic keratosis",
            "lentigo maligna melanoma",
            "merkel cell carcinoma",
            "cutaneous t cell lymphoma",
            "cutaneous b-cell lymphoma",
            "kaposi's sarcoma of skin",
            "metastatic carcinoma",
            "stevens-johnson syndrome",
            "toxic epidermal necrolysis",
        }
        top_labels = {item.label.lower() for item in visual.top_predictions[:3]}
        if top_labels.intersection(high_risk):
            ordered = ["DERM_Q101", "DERM_Q102", "DERM_Q103", "DERM_Q105"]
        else:
            ordered = ["DERM_Q101", "DERM_Q103", "DERM_Q102", "DERM_Q105"]
        if intake.fever or intake.rapid_spread:
            ordered = ["DERM_Q104", *ordered]
        return list(dict.fromkeys(ordered))[:4]

    @staticmethod
    def _parse_cloud_ids(text: str, allowed: set[str]) -> list[str]:
        for match in re.findall(r"\{[^{}]*\}", text, flags=re.S):
            try:
                value = json.loads(match).get("question_ids", [])
            except (json.JSONDecodeError, AttributeError):
                continue
            selected = list(dict.fromkeys(str(item) for item in value if str(item) in allowed))
            if 2 <= len(selected) <= 4:
                return selected
        return []

    def create_plan(
        self,
        case_id: str,
        intake: ContextualIntakeRequest,
        visual: VisualEvidence,
        triage: TriageDecision,
        provider: ChatProvider,
        guard: EgressGuard,
    ) -> VerificationPlan:
        if self.repository.get_case(case_id) is None:
            raise KeyError("病例不存在")
        visual_candidates = [item.label for item in visual.top_predictions[:3]]
        if visual.prediction_mode == "supervised_linear_probe" and not visual.abstained:
            visual_candidates = visual_candidates[:1]
        chunks = self.knowledge.search_patient_context(
            user_query="结构化症状追问与风险核验",
            visual_candidates=visual_candidates,
            positive_symptoms=[
                name for name, active in {
                    "疼痛": intake.pain, "瘙痒": intake.pruritus, "发热": intake.fever,
                    "快速扩散": intake.rapid_spread, "严重出血": intake.severe_bleeding,
                }.items() if active
            ],
            risk_reasons=[triage.level.value, *triage.reason_codes],
            duration=intake.duration,
            topic="追问 鉴别 风险 转诊",
            top_k=3,
        )
        fallback_ids = self._default_question_ids(visual, intake)
        candidates = [self.questions[item] for item in fallback_ids]
        safe_context = guard.enforce(
            EgressRequest(
                channel="llm",
                destination=provider.name,
                case_id=case_id,
                payload={
                    "task": "rank_whitelisted_questions",
                    "visual_candidates": visual.model_dump(mode="json")["top_predictions"],
                    "visual_triage": triage.level.value,
                    "structured_intake": intake.model_dump(mode="json", exclude={"model"}),
                    "question_candidates": [item.model_dump(mode="json") for item in candidates],
                    "guideline_context": chunks,
                },
            )
        ).sanitized_payload
        selected_ids: list[str] = []
        source = "本地确定性排序（云端不可用或返回无效）"
        try:
            prompt = (
                "仅对候选问题排序，不得诊断或生成新问题。"
                "返回严格JSON：{\"question_ids\":[\"DERM_Q...\"]}，选2至4个。"
            )
            text = provider.generate(prompt, "clinician", {"structured_context": safe_context})
            selected_ids = self._parse_cloud_ids(text, set(fallback_ids))
            if selected_ids:
                source = f"云模型白名单排序（{provider.model}）"
        except Exception:
            selected_ids = []
        if not selected_ids:
            selected_ids = fallback_ids
        plan = VerificationPlan(
            case_id=case_id,
            questions=[self.questions[item] for item in selected_ids],
            planner_source=source,
            model_requested=intake.model,
            rag_references=self.knowledge.references(chunks),
        )
        self.repository.save_context_intake(case_id, intake)
        self.repository.save_verification_plan(case_id, plan)
        return plan

    @staticmethod
    def _raised_level(baseline: CarePathwayLevel, proposed: CarePathwayLevel) -> CarePathwayLevel:
        return proposed if LEVEL_RANK[proposed] > LEVEL_RANK[baseline] else baseline

    def calibrate(
        self, case_id: str, request: ContextualVerificationRequest, triage: TriageDecision
    ) -> ContextualAssessment:
        intake_raw = self.repository.get_context_intake(case_id)
        plan_raw = self.repository.get_verification_plan(case_id)
        if intake_raw is None or plan_raw is None:
            raise ValueError("请先完成结构化症状采集和追问规划")
        intake = ContextualIntakeRequest.model_validate(intake_raw)
        plan = VerificationPlan.model_validate(plan_raw)
        expected = {item.id for item in plan.questions}
        supplied = {item.question_id for item in request.answers}
        if supplied != expected or len(supplied) != len(request.answers):
            raise ValueError("追问答案必须与当前问题清单完全一致，且不能重复")

        facts = {item.question_id: item.answer for item in request.answers}
        emergency = any(
            [
                intake.breathing_difficulty,
                intake.altered_consciousness,
                intake.severe_bleeding,
                intake.severe_allergic_reaction,
            ]
        )
        lesion_alerts = [
            question_id
            for question_id in ("DERM_Q101", "DERM_Q102", "DERM_Q103")
            if facts.get(question_id, False)
        ]
        infection_progression = bool(facts.get("DERM_Q104", False))
        high_risk_history = bool(facts.get("DERM_Q105", False))
        red_flags: list[str] = []
        redflag_risk = CarePathwayLevel.LOCAL_REVIEW
        reason_codes: list[str] = []
        if emergency:
            redflag_risk = CarePathwayLevel.PRIORITY_REFERRAL
            red_flags.append("systemic_emergency")
            reason_codes.append("SYSTEMIC_RED_FLAG")
        elif infection_progression or (intake.fever and intake.rapid_spread):
            redflag_risk = CarePathwayLevel.PRIORITY_REFERRAL
            red_flags.append("rapid_infection_with_systemic_symptoms")
            reason_codes.append("RAPID_INFECTION_RED_FLAG")
        elif len(lesion_alerts) >= 2:
            redflag_risk = CarePathwayLevel.PRIORITY_REFERRAL
            red_flags.extend(self.questions[item].target_feature for item in lesion_alerts)
            reason_codes.append("MULTIPLE_LESION_RED_FLAGS")
        elif lesion_alerts or high_risk_history:
            redflag_risk = CarePathwayLevel.REFERRAL
            red_flags.extend(self.questions[item].target_feature for item in lesion_alerts)
            if high_risk_history:
                red_flags.append("high_risk_history")
            reason_codes.append("LESION_RED_FLAG")
        else:
            reason_codes.append("NO_RED_FLAG_ESCALATION")
        adjusted = self._raised_level(triage.level, redflag_risk)
        if adjusted == triage.level:
            reason_codes.append("VISUAL_TRIAGE_PRESERVED")
        else:
            reason_codes.append("RISK_ESCALATED_BY_LOCAL_POLICY")

        positive_features = [
            self.questions[key].target_feature for key, value in facts.items() if value
        ]
        positive_features.extend(
            name
            for name, active in {
                "fever": intake.fever,
                "rapid_spread": intake.rapid_spread,
                "systemic_red_flag": emergency,
            }.items()
            if active
        )
        chunks = self.knowledge.search_patient_context(
            user_query="症状核验后二次校准",
            positive_symptoms=positive_features,
            risk_reasons=[adjusted.value, *reason_codes],
            duration=intake.duration,
            topic="风险依据 检查依据 转诊依据 信息缺口",
            top_k=3,
        )
        actions = {
            CarePathwayLevel.RETAKE: "先重新拍摄清晰图片，若同时有严重不适请直接就医。",
            CarePathwayLevel.LOCAL_REVIEW: "建议由基层医生结合病史和现场检查继续评估。",
            CarePathwayLevel.REFERRAL: "结合症状信息后建议转诊皮肤专科进一步评估。",
            CarePathwayLevel.PRIORITY_REFERRAL: "结合视觉与症状风险信号，建议尽快就医或优先转诊；若存在系统性红旗症状，请立即寻求急诊帮助。",
        }
        result = ContextualAssessment(
            case_id=case_id,
            visual_triage_level=triage.level,
            contextual_triage_level=adjusted,
            risk_changed=adjusted != triage.level,
            red_flags=list(dict.fromkeys(red_flags)),
            positive_context_features=list(dict.fromkeys(positive_features)),
            reason_codes=reason_codes,
            action=actions[adjusted],
            rag_references=self.knowledge.references(chunks),
        )
        self.repository.save_contextual_assessment(case_id, result)
        return result

    def get(self, case_id: str) -> ContextualAssessment:
        raw = self.repository.get_contextual_assessment(case_id)
        if raw is None:
            raise KeyError("该病例尚未完成症状二次校准")
        # 兼容收敛前已写入 SQLite 的病例：旧版分数不再参与决策。
        raw = dict(raw)
        raw.pop("context_risk_score", None)
        raw.setdefault("red_flags", [])
        raw.setdefault("calibration_policy_version", "visual-baseline-redflag-v2")
        return ContextualAssessment.model_validate(raw)
