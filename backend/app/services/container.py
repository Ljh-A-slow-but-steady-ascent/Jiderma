from __future__ import annotations

from dataclasses import dataclass

from backend.app.database import CaseRepository
from backend.app.services.care_service import CareService
from backend.app.services.case_service import CaseService
from backend.app.services.contextual_service import ContextualCalibrationService
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.services.privacy_service import PrivacyService
from backend.app.services.triage_service import TriagePolicyService
from backend.app.services.visual_service import VisualService


@dataclass
class ServiceContainer:
    repository: CaseRepository
    cases: CaseService
    visual: VisualService
    triage: TriagePolicyService
    knowledge: KnowledgeService
    care: CareService
    privacy: PrivacyService
    contextual: ContextualCalibrationService


def create_service_container(repository: CaseRepository | None = None) -> ServiceContainer:
    repository = repository or CaseRepository()
    cases = CaseService(repository)
    knowledge = KnowledgeService()
    return ServiceContainer(
        repository=repository,
        cases=cases,
        visual=VisualService(repository, cases),
        triage=TriagePolicyService(repository=repository),
        knowledge=knowledge,
        care=CareService(repository=repository),
        privacy=PrivacyService(repository),
        contextual=ContextualCalibrationService(repository, knowledge),
    )
