"""Subprocess bridge to the frozen DermFM Provider; do not put business rules here."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import torch
from PIL import Image
from torch import nn
from torchvision import transforms
from torchvision.transforms import InterpolationMode


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# All model/tokenizer artifacts are already permanent local files. Prevent
# availability checks from introducing proxy/network delays during inference.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from src.dermfm_provider import DermFMZeroProvider  # noqa: E402
from backend.app.services.dermfm_candidate_sets import (  # noqa: E402
    EXTENDED_CANDIDATE_SET_ID,
    EXTENDED_CLASSNAMES,
)


HAM7_HEAD = ROOT / "artifacts" / "training" / "ham7_linear_head" / "ham7_linear_head.pt"


def predict_ham7(provider: DermFMZeroProvider, image_path: Path, top_k: int) -> dict:
    """Apply the local HAM7 head without changing the frozen DermFM backbone."""
    checkpoint = torch.load(HAM7_HEAD, map_location="cpu", weights_only=False)
    if checkpoint.get("base_checkpoint_frozen") is not True:
        raise RuntimeError("HAM7 checkpoint does not declare a frozen base checkpoint")
    feature_dim = int(checkpoint["feature_dim"])
    class_names = list(checkpoint["class_names"])
    head = nn.Linear(feature_dim, len(class_names)).to(provider.device)
    head.load_state_dict(checkpoint["state_dict"], strict=True)
    head.eval().requires_grad_(False)
    preprocess = transforms.Compose(
        [
            transforms.Resize(256, interpolation=InterpolationMode.BICUBIC),
            transforms.CenterCrop(224),
            transforms.Lambda(lambda image: image.convert("RGB")),
            transforms.ToTensor(),
            transforms.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)),
        ]
    )
    started = time.perf_counter()
    with Image.open(image_path) as source_image:
        image = preprocess(source_image).unsqueeze(0).to(provider.device)
    with torch.inference_mode():
        if provider.device.type == "cuda":
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                features = provider.model.encode_image(image)
        else:
            features = provider.model.encode_image(image)
        features = torch.nn.functional.normalize(features.float(), dim=-1)
        logits = head(features) / float(checkpoint["temperature"])
        probabilities = logits.softmax(dim=-1)[0]
    confidence = float(probabilities.max().cpu())
    threshold = float(checkpoint["abstention_threshold"])
    values, indices = probabilities.topk(min(top_k, len(class_names)))
    predictions = [
        {"label": class_names[index], "score": float(value)}
        for value, index in zip(values.cpu().tolist(), indices.cpu().tolist())
    ]
    if not all(math.isfinite(item["score"]) for item in predictions):
        raise RuntimeError("HAM7 head returned a non-finite score")
    return {
        "model_name": "DermFM-Zero-Open + HAM7 Linear Head",
        "candidate_set": "ham7_supervised_7_v1",
        "top_predictions": predictions,
        "prediction_mode": "supervised_linear_probe",
        "input_modality": "dermoscopic",
        "confidence_threshold": threshold,
        "abstained": confidence < threshold,
        "latency_ms": (time.perf_counter() - started) * 1000.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument(
        "--image-modality", choices=("dermoscopic", "clinical"), default="dermoscopic"
    )
    args = parser.parse_args()
    # Keep src/dermfm_provider.py and the checkpoint frozen. Only replace the
    # external zero-shot text prompt profile before model loading.
    provider = DermFMZeroProvider()
    provider.classnames = EXTENDED_CLASSNAMES
    provider.load()
    if args.image_modality == "dermoscopic" and HAM7_HEAD.is_file():
        result = predict_ham7(provider, Path(args.image), args.top_k)
    else:
        result = provider.predict(Path(args.image), top_k=args.top_k)
        result["candidate_set"] = EXTENDED_CANDIDATE_SET_ID
        result["candidate_count"] = len(EXTENDED_CLASSNAMES)
        result["prediction_mode"] = "zero_shot"
        result["input_modality"] = args.image_modality
        result["abstained"] = False
    print("DERMAGUARD_RESULT=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
