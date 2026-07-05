"""Generates one AI still image per renovation stage, all anchored on the user's
reference photo (image-to-image edit) so the room's geometry and camera angle stay
consistent across stages. These images are sent to the user as a preview album and
then used as keyframes for the video pipeline: clip i animates from
stage_image[i-1] to stage_image[i]. The last stage image is always the user's real
reference photo (never AI-generated), guaranteeing the timelapse ends on an exact match.
"""
from __future__ import annotations

import base64
import os
from typing import Callable, Optional

import openrouter_client as orc

ProgressCallback = Optional[Callable[[int, int], None]]


def _save_data_uri(data_uri: str, out_path: str) -> None:
    _, b64 = data_uri.split(",", 1)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))


def generate_stage_images(
    cfg, reference_image_path: str, stage_prompts: list[str], work_dir: str,
    progress_cb: ProgressCallback = None,
) -> list[str]:
    os.makedirs(work_dir, exist_ok=True)
    reference_data_uri = orc.image_to_data_uri(reference_image_path)
    total = len(stage_prompts)
    paths: list[str] = []

    # Every stage except the last gets its own AI-rendered still image.
    for i, prompt in enumerate(stage_prompts[:-1]):
        if progress_cb:
            progress_cb(i + 1, total)
        image_data_uri = orc.generate_stage_image(
            cfg.openrouter_api_key, cfg.image_model, prompt, reference_data_uri
        )
        out_path = os.path.join(work_dir, f"stage_{i + 1:02d}.png")
        _save_data_uri(image_data_uri, out_path)
        paths.append(out_path)

    # The final stage is the user's own photo - always an exact match, never regenerated.
    paths.append(reference_image_path)
    if progress_cb:
        progress_cb(total, total)

    return paths
