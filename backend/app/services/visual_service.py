from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Protocol

from backend.app.care.schemas import CandidatePrediction, VisualEvidence
from backend.app.database import CaseRepository
from backend.app.services.case_service import CaseService
from backend.app.services.vision.quality import assess_image_quality


DERMFM_PYTHON = Path(
    os.getenv("DERMAGUARD_VISION_PYTHON", "/home/lu/miniforge3/envs/dermfm-zero/bin/python")
)
WORKER = Path(__file__).resolve().parent / "frozen_dermfm_worker.py"


class VisualRunner(Protocol):
    def predict(self, image_path: Path, image_modality: str = "dermoscopic") -> dict: ...


class FrozenDermFMSubprocessRunner:
    """Calls the frozen provider in its isolated environment without modifying it."""

    def predict(self, image_path: Path, image_modality: str = "dermoscopic") -> dict:
        completed = subprocess.run(
            [
                str(DERMFM_PYTHON), str(WORKER), "--image", str(image_path),
                "--top-k", "5", "--image-modality", image_modality,
            ],
            cwd=str(Path(__file__).resolve().parents[3]),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"DermFM worker failed: {completed.stderr[-1000:]}")
        line = next(
            (item for item in reversed(completed.stdout.splitlines()) if item.startswith("DERMAGUARD_RESULT=")),
            None,
        )
        if line is None:
            raise RuntimeError("DermFM worker returned no structured result")
        return json.loads(line.removeprefix("DERMAGUARD_RESULT="))


class VisualService:
    def __init__(
        self,
        repository: CaseRepository | None = None,
        case_service: CaseService | None = None,
        runner: VisualRunner | None = None,
    ) -> None:
        self.repository = repository or CaseRepository()
        self.case_service = case_service or CaseService(self.repository)
        self.runner = runner or FrozenDermFMSubprocessRunner()

    def analyze(self, case_id: str, image_modality: str = "dermoscopic") -> VisualEvidence:
        image_path = self.case_service.get_local_image_path(case_id)
        quality, _ = assess_image_quality(image_path)
        try:
            raw = self.runner.predict(image_path, image_modality=image_modality)
        except TypeError:
            # Backward compatibility for injected deterministic test runners.
            raw = self.runner.predict(image_path)
        supervised = raw.get("prediction_mode") == "supervised_linear_probe"
        abstained = bool(raw.get("abstained", False))
        warnings = []
        if supervised:
            warnings.extend(
                [
                    "本地监督任务头用于皮肤镜图像辅助筛查，普通临床照片不适用。",
                    "任务头分数经过温度缩放，但仍不是确诊概率；病理检查和医生评估不可替代。",
                ]
            )
            if abstained:
                warnings.append("最高分低于验证集拒识阈值，本次监督任务头证据不足，未作高置信度判别。")
        else:
            warnings.extend(
                [
                    "候选分数是60类扩展候选集内的相对匹配分数，不是疾病概率或确诊结果。",
                    "扩展类别尚未在本项目逐类完成临床性能验证。",
                ]
            )
        result = VisualEvidence(
            case_id=case_id,
            model=str(raw.get("model_name", "DermFM-Zero-Open")),
            candidate_set=str(raw.get("candidate_set", "dermfm_extended_60_zh_en_v1")),
            top_predictions=[CandidatePrediction.model_validate(item) for item in raw["top_predictions"]],
            image_quality=quality,
            supports_triage=True,
            latency_ms=float(raw.get("latency_ms", 0.0)),
            local_only=True,
            warnings=warnings,
            prediction_mode=str(raw.get("prediction_mode", "zero_shot")),
            input_modality=str(raw.get("input_modality", image_modality)),
            confidence_threshold=raw.get("confidence_threshold"),
            abstained=abstained,
            zero_shot_predictions=[],
        )
        self.repository.save_visual(case_id, result)
        return result

    def get(self, case_id: str) -> VisualEvidence:
        raw = self.repository.get_visual(case_id)
        if raw is None:
            raise KeyError(f"visual result not found: {case_id}")
        return VisualEvidence.model_validate(raw)
