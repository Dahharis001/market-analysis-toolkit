"""Generates one AI still image per renovation stage, chained forward stage-by-stage
so the progression is cumulative instead of everything being a separate edit of the
same finished photo.

Image-edit models are good at *adding* things to a photo (pipes, tiles, fixtures) but
bad at *stripping* a finished room back down to bare concrete - if every stage edits
the original finished reference photo independently, later "earlier" stages tend to
still look almost finished, because the model keeps biasing back toward the input it
was given. So only stage 1 edits the real reference photo (unavoidable - it's the only
source image there is); every stage after that edits the *previous stage's own
generated image*, which is a much smaller, more natural additive change for the model
to make. These images are sent to the user as a preview album and then used as
keyframes for the video pipeline: clip i animates from stage_image[i-1] to
stage_image[i]. The last stage image is always the user's real reference photo (never
AI-generated), guaranteeing the timelapse ends on an exact match.
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

    # Only stage 1 edits the real reference photo (the only source image we have).
    # Every later stage edits the *previous stage's own generated image*, so each
    # step is a small additive change instead of another attempt to strip the
    # finished room back down to bare concrete from scratch.
    anchor_data_uri = reference_data_uri
    for i, prompt in enumerate(stage_prompts[:-1]):
        if progress_cb:
            progress_cb(i + 1, total)
        image_data_uri = orc.generate_stage_image(
            cfg.openrouter_api_key, cfg.image_model, prompt, anchor_data_uri
        )
        out_path = os.path.join(work_dir, f"stage_{i + 1:02d}.png")
        _save_data_uri(image_data_uri, out_path)
        paths.append(out_path)
        anchor_data_uri = image_data_uri

    # The final stage is the user's own photo - always an exact match, never regenerated.
    paths.append(reference_image_path)
    if progress_cb:
        progress_cb(total, total)

    return paths
