"""Run the one-image DermFM-Zero smoke test and persist machine-readable facts."""

from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

import psutil
import torch
import torchvision

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dermfm_provider import DermFMZeroProvider


SAMPLE_IMAGE = ROOT / "third_party" / "DermFM-Zero" / "examples" / "PAT_8_15_820.png"
RESULT_PATH = ROOT / "artifacts" / "dermfm_smoke_result.json"


def main() -> None:
    process = psutil.Process()
    rss_before = process.memory_info().rss
    provider = DermFMZeroProvider()
    provider.load()
    rss_after_load = process.memory_info().rss

    # The first pass includes CUDA/context warm-up; the second is the warm result.
    first = provider.predict(SAMPLE_IMAGE)
    warm_started = time.perf_counter()
    warm = provider.predict(SAMPLE_IMAGE)
    warm_call_wall_ms = (time.perf_counter() - warm_started) * 1000.0
    result = {
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "torchvision": torchvision.__version__,
            "torch_cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "provider_health": provider.health_check(),
        "sample_image": str(SAMPLE_IMAGE),
        "first_inference": first,
        "warm_inference": warm,
        "warm_call_wall_ms": warm_call_wall_ms,
        "memory": {
            "rss_before_load_bytes": rss_before,
            "rss_after_load_bytes": rss_after_load,
            "rss_after_inference_bytes": process.memory_info().rss,
            "peak_gpu_vram_bytes": provider.peak_gpu_vram_bytes(),
        },
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
