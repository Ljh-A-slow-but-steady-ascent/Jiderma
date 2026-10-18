"""Render the measured DermFM smoke-test result as a standalone PNG."""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "artifacts" / "dermfm_smoke_result.json"
OUTPUT = ROOT / "artifacts" / "dermfm_smoke_visualization.png"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


def main() -> None:
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    inference = data["warm_inference"]
    predictions = inference["top_predictions"]
    source = Image.open(data["sample_image"]).convert("RGB")

    canvas = Image.new("RGB", (1600, 900), "#f6f8fb")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((45, 40, 1555, 860), radius=28, fill="white", outline="#dce3ec", width=2)
    draw.text((90, 78), "DermFM-Zero-Open | Official Sample Smoke Test", font=font(40, True), fill="#172033")
    draw.text(
        (90, 132),
        "Measured zero-shot class matching scores (not clinical probabilities)",
        font=font(22),
        fill="#657084",
    )

    image_box = (90, 205, 700, 720)
    target_w = image_box[2] - image_box[0]
    target_h = image_box[3] - image_box[1]
    source.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    x = image_box[0] + (target_w - source.width) // 2
    y = image_box[1] + (target_h - source.height) // 2
    draw.rounded_rectangle(image_box, radius=20, fill="#eef2f7")
    canvas.paste(source, (x, y))
    draw.text((90, 748), "Official example: PAT_8_15_820.png", font=font(20, True), fill="#273248")

    chart_x, chart_y, chart_w = 780, 230, 680
    colors = ("#2563eb", "#7c3aed", "#0f9f78")
    draw.text((chart_x, 190), "Top-3 candidates", font=font(28, True), fill="#172033")
    for rank, (item, color) in enumerate(zip(predictions, colors), start=1):
        row_y = chart_y + (rank - 1) * 145
        score = float(item["score"])
        draw.text((chart_x, row_y), f"{rank}. {item['label']}", font=font(24, True), fill="#273248")
        draw.text((chart_x + 470, row_y + 2), f"{score:.8g}", font=font(21), fill="#4b5567")

        # Log scale keeps the lower-ranked, very small scores visible.
        log_value = max(0.0, min(1.0, (math.log10(max(score, 1e-16)) + 16.0) / 16.0))
        bar_y = row_y + 48
        draw.rounded_rectangle((chart_x, bar_y, chart_x + chart_w, bar_y + 30), radius=15, fill="#e8edf4")
        width = max(8, int(chart_w * log_value))
        draw.rounded_rectangle((chart_x, bar_y, chart_x + width, bar_y + 30), radius=15, fill=color)
        draw.text((chart_x, bar_y + 42), "log10 scale", font=font(15), fill="#8993a4")

    env = data["environment"]
    peak_gib = data["memory"]["peak_gpu_vram_bytes"] / (1024 ** 3)
    info_y = 690
    draw.rounded_rectangle((760, info_y, 1485, 810), radius=18, fill="#f1f5fb")
    draw.text(
        (790, info_y + 20),
        f"Device: {env['gpu']}  |  CUDA: {env['torch_cuda_runtime']}",
        font=font(19, True),
        fill="#273248",
    )
    draw.text(
        (790, info_y + 58),
        f"Warm end-to-end latency: {inference['latency_ms']:.2f} ms  |  Peak VRAM: {peak_gib:.3f} GiB",
        font=font(19),
        fill="#4b5567",
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT, quality=95)
    print(OUTPUT)


if __name__ == "__main__":
    main()
