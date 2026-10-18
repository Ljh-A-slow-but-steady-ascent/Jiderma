from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.care.schemas import CarePathwayLevel, GuidelineReference


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextualIntakeRequest(StrictModel):
    duration: Literal["within_24h", "1_3_days", "4_7_days", "1_4_weeks", "over_month", "unknown"]
    pain: bool
    pruritus: bool
    fever: bool
    rapid_spread: bool
    breathing_difficulty: bool = False
    altered_consciousness: bool = False
    severe_bleeding: bool = False
    severe_allergic_reaction: bool = False
    model: str = "auto"


class VerificationQuestion(StrictModel):
    id: str
    target_feature: str
    question: str
    patient_hint: str
    answer_type: Literal["boolean"] = "boolean"


class VerificationPlan(StrictModel):
    case_id: str
    questions: list[VerificationQuestion]
    planner_source: str
    model_requested: str
    rag_references: list[GuidelineReference]
    raw_image_sent_to_cloud: bool = False
    decision_still_local: bool = True


class VerificationAnswer(StrictModel):
    question_id: str
    answer: bool


class ContextualVerificationRequest(StrictModel):
    answers: list[VerificationAnswer] = Field(min_length=1)


class ContextualAssessment(StrictModel):
    case_id: str
    visual_triage_level: CarePathwayLevel
    contextual_triage_level: CarePathwayLevel
    risk_changed: bool
    red_flags: list[str]
    positive_context_features: list[str]
    reason_codes: list[str]
    action: str
    rag_references: list[GuidelineReference]
    calibration_policy_version: str = "visual-baseline-redflag-v2"
    cloud_influenced_decision: bool = False
    visual_scores_modified: bool = False
    disclaimer: str = "本系统仅用于辅助筛查和分级转诊，不构成医学诊断。"
