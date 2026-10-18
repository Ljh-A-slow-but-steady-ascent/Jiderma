import math
from pathlib import Path

import pytest
import torch

from src.dermfm_provider import DermFMZeroProvider


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_IMAGE = ROOT / "third_party" / "DermFM-Zero" / "examples" / "PAT_8_15_820.png"


@pytest.fixture(scope="session")
def provider():
    instance = DermFMZeroProvider()
    instance.load()
    return instance


@pytest.fixture(scope="session")
def prediction(provider):
    return provider.predict(SAMPLE_IMAGE)


def test_provider_load(provider):
    assert provider.model is not None
    assert Path(provider.open_clip_path).is_relative_to(provider.repo_dir / "src")
    assert provider.checkpoint_path.is_file()
    assert not provider.checkpoint_path.is_symlink()


def test_provider_health(provider):
    assert provider.health_check()["healthy"] is True


def test_single_image_inference(prediction):
    assert prediction["model_name"] == "DermFM-Zero-Open"
    assert prediction["metadata"]["task"] == "zero_shot_classification"


def test_topk_output(prediction):
    assert len(prediction["top_predictions"]) == 3
    assert all(set(item) == {"label", "score"} for item in prediction["top_predictions"])


def test_score_is_finite(prediction):
    assert all(math.isfinite(item["score"]) for item in prediction["top_predictions"])


def test_no_training_enabled(provider):
    assert provider.model.training is False
    assert provider.health_check()["training"] is False


def test_provider_does_not_require_grad(provider, prediction):
    assert torch.is_grad_enabled() is True  # global state was not mutated
    assert not any(parameter.requires_grad for parameter in provider.model.parameters())
    assert prediction["metadata"]["training"] is False
