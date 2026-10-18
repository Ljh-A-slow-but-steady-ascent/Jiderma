"""Inference-only provider for the official DermFM-Zero-Open checkpoint."""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import torch
from PIL import Image


DEFAULT_CLASSNAMES = (
    "nevus",
    "basal cell carcinoma",
    "actinic keratosis",
    "seborrheic keratosis",
    "squamous cell carcinoma",
    "melanoma",
)


class DermFMZeroProvider:
    """A narrow image-to-zero-shot-score adapter with no triage logic."""

    MODEL_ID = "hf-hub:redlessone/DermFM-Zero"
    ARCHITECTURE_NAME = "PanDerm-large-v2-w-PubMed-256"
    MODEL_NAME = "DermFM-Zero-Open"
    SOURCE = "SiyuanYan1/DermFM-Zero"

    def __init__(
        self,
        repo_dir: Optional[Path] = None,
        checkpoint_path: Optional[Path] = None,
        device: str = "auto",
        classnames: Sequence[str] = DEFAULT_CLASSNAMES,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        self.repo_dir = Path(repo_dir or root / "third_party" / "DermFM-Zero").resolve()
        self.checkpoint_path = Path(
            checkpoint_path
            or root / "weights" / "DermFM-Zero-Open" / "open_clip_pytorch_model.bin"
        ).resolve()
        self.classnames = tuple(classnames)
        if len(self.classnames) != 6:
            raise ValueError("The smoke-test provider requires exactly six candidate labels.")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false.")
        self.device = torch.device(device)
        self.model = None
        self.preprocess = None
        self.tokenizer = None
        self.open_clip_path: Optional[str] = None
        self.load_time_ms: Optional[float] = None
        self.checkpoint_missing_keys = None
        self.checkpoint_unexpected_keys = None
        self._text_features = None

    def _import_bundled_open_clip(self):
        src_dir = (self.repo_dir / "src").resolve()
        if not src_dir.is_dir():
            raise FileNotFoundError(f"Bundled source directory not found: {src_dir}")
        src_string = str(src_dir)
        if src_string not in sys.path:
            sys.path.insert(0, src_string)

        import open_clip  # pylint: disable=import-outside-toplevel

        module_path = Path(open_clip.__file__).resolve()
        try:
            module_path.relative_to(src_dir)
        except ValueError as exc:
            raise RuntimeError(
                f"Refusing non-bundled open_clip import: {module_path}; expected under {src_dir}"
            ) from exc
        self.open_clip_path = str(module_path)
        return open_clip

    def load(self) -> "DermFMZeroProvider":
        if self.model is not None:
            return self

        if not self.checkpoint_path.is_file():
            raise FileNotFoundError(
                f"Permanent checkpoint not found: {self.checkpoint_path}. "
                "Download it only from redlessone/DermFM-Zero."
            )
        open_clip = self._import_bundled_open_clip()

        if self.device.type == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(self.device)
        started = time.perf_counter()
        model, _, preprocess = open_clip.create_model_and_transforms(
            self.ARCHITECTURE_NAME,
            device=self.device,
            pretrained_hf=False,
        )
        missing, unexpected = open_clip.utils.load_dermfm_checkpoint(
            model,
            str(self.checkpoint_path),
        )
        tokenizer = open_clip.get_tokenizer(self.ARCHITECTURE_NAME)
        model.eval()
        model.requires_grad_(False)
        self.model = model
        self.preprocess = preprocess
        self.tokenizer = tokenizer
        self.checkpoint_missing_keys = tuple(missing)
        self.checkpoint_unexpected_keys = tuple(unexpected)
        self.load_time_ms = (time.perf_counter() - started) * 1000.0
        self._prepare_text_features()
        return self

    def _prepare_text_features(self) -> None:
        prompts = [f"This is a skin image of {label}" for label in self.classnames]
        tokens = self.tokenizer(prompts).to(self.device)
        with torch.inference_mode():
            features = self.model.encode_text(tokens)
            self._text_features = features / features.norm(dim=-1, keepdim=True)

    def predict(self, image_path: Path, top_k: int = 3) -> Dict[str, Any]:
        if self.model is None:
            raise RuntimeError("Provider is not loaded. Call load() first.")
        if not 1 <= top_k <= len(self.classnames):
            raise ValueError(f"top_k must be between 1 and {len(self.classnames)}")
        image_path = Path(image_path)
        if not image_path.is_file():
            raise FileNotFoundError(image_path)

        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        started = time.perf_counter()
        with Image.open(image_path) as source_image:
            image = self.preprocess(source_image.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            image_features = self.model.encode_image(image)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            scores = (100.0 * image_features @ self._text_features.T).softmax(dim=-1)[0]
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        latency_ms = (time.perf_counter() - started) * 1000.0

        values, indices = scores.topk(top_k)
        predictions = [
            {"label": self.classnames[index], "score": float(value)}
            for value, index in zip(values.cpu().tolist(), indices.cpu().tolist())
        ]
        if not all(math.isfinite(item["score"]) for item in predictions):
            raise RuntimeError("Model returned a non-finite zero-shot score.")
        return {
            "model_name": self.MODEL_NAME,
            "source": self.SOURCE,
            "top_predictions": predictions,
            "latency_ms": latency_ms,
            "device": self.device.type,
            "metadata": {
                "task": "zero_shot_classification",
                "training": False,
            },
        }

    def health_check(self) -> Dict[str, Any]:
        loaded = self.model is not None
        return {
            "healthy": loaded and not self.model.training,
            "loaded": loaded,
            "model_name": self.MODEL_NAME,
            "device": self.device.type,
            "training": None if not loaded else self.model.training,
            "grad_enabled_for_parameters": None
            if not loaded
            else any(parameter.requires_grad for parameter in self.model.parameters()),
            "open_clip_path": self.open_clip_path,
            "checkpoint_path": str(self.checkpoint_path),
            "checkpoint_is_file": self.checkpoint_path.is_file(),
            "checkpoint_is_symlink": self.checkpoint_path.is_symlink(),
            "checkpoint_missing_keys": self.checkpoint_missing_keys,
            "checkpoint_unexpected_keys": self.checkpoint_unexpected_keys,
            "load_time_ms": self.load_time_ms,
        }

    def peak_gpu_vram_bytes(self) -> int:
        if self.device.type != "cuda":
            return 0
        return int(torch.cuda.max_memory_allocated(self.device))
