from __future__ import annotations

import json
from pathlib import Path

from backend.app.services.clinical_extraction_service import ClinicalExtractionService
from backend.app.services.privacy import EgressGuard


def test_offline_extraction_preserves_explicit_positive_and_negative_facts() -> None:
    result = ClinicalExtractionService(EgressGuard()).extract(
        narrative=(
            "70岁男性，面部色素性病灶约9×9毫米，近期明显增大且颜色发生变化，"
            "无疼痛、瘙痒和出血，无皮肤癌病史及其他癌症病史。"
        ),
        age=70,
        gender="MALE",
        model_id="auto",
        identity_values=[],
    )
    assert result.missing_fields == []
    assert result.metadata == {
        "age": 70, "gender": "MALE", "region": "FACE",
        "itch": False, "hurt": False, "bleed": False,
        "grew": True, "changed": True,
        "diameter_1": 9.0, "diameter_2": 9.0,
        "skin_cancer_history": False, "cancer_history": False,
    }


def test_cloud_extraction_masks_identity_and_keeps_unknown_fields(monkeypatch) -> None:
    captured: dict = {}

    class FakeProvider:
        name = "fake-cloud"
        model = "fake-model"

        def plan(self, payload, system_prompt):
            captured["payload"] = payload
            captured["system_prompt"] = system_prompt
            return json.dumps({
                "metadata": {
                    "region": "FOREARM", "itch": True, "hurt": None,
                    "bleed": False, "grew": True, "changed": True,
                    "diameter_1": 10, "diameter_2": 8,
                    "skin_cancer_history": False, "cancer_history": False,
                },
                "uncertain_fields": ["hurt"],
            })

    monkeypatch.setattr(
        "backend.app.chat.mock.create_chat_provider", lambda model_id: FakeProvider()
    )
    result = ClinicalExtractionService(EgressGuard()).extract(
        narrative="患者李某，电话13800138000，左前臂病灶近期增大并出现变化。",
        age=45,
        gender="FEMALE",
        model_id="glm-5.3-flash",
        identity_values=["李某", "OP-001", "13800138000"],
    )
    serialized = json.dumps(captured["payload"], ensure_ascii=False)
    assert "李某" not in serialized
    assert "13800138000" not in serialized
    assert "[REDACTED_IDENTITY]" in serialized
    assert result.metadata["age"] == 45
    assert result.metadata["gender"] == "FEMALE"
    assert result.metadata["hurt"] is None
    assert result.missing_fields == ["hurt"]
    assert result.uncertain_fields == ["hurt"]


def test_ui_uses_narrative_extraction_before_multimodal_analysis() -> None:
    source = Path("ui/streamlit_app.py").read_text(encoding="utf-8")
    assert "病例自然语言描述" in source
    assert "/v1/clinical-metadata/extract" in source
    assert "结构化信息确认" in source
    assert "confirmed_metadata" in source
    assert 'st.checkbox("瘙痒")' not in source
    assert "未提取到的信息不会被自动补造" in source
