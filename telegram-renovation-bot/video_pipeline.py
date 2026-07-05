"""Turns the AI-rendered stage images into video clips and stitches them together.

Continuity comes from keyframing rather than frame-chaining: clip i is generated with
stage_images[i-1] as its first frame and stage_images[i] as its last frame (clip 0 has
no first frame - it opens on the bare-shell prompt itself). Since stage_images[-1] is
always the user's real reference photo, the final clip's last frame matches exactly.
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

import openrouter_client as orc

ProgressCallback = Optional[Callable[[int, int, str], None]]


def _probe_duration(video_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video_path],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


def generate_clips(
    cfg, stage_prompts: list[str], stage_image_paths: list[str], work_dir: str,
    progress_cb: ProgressCallback = None,
) -> list[str]:
    if len(stage_prompts) != len(stage_image_paths):
        raise ValueError("stage_prompts and stage_image_paths must have the same length")

    os.makedirs(work_dir, exist_ok=True)
    clip_paths = []
    total = len(stage_prompts)

    for i, prompt in enumerate(stage_prompts):
        if progress_cb:
            progress_cb(i + 1, total, "генерация видео")

        first_frame = orc.image_to_data_uri(stage_image_paths[i - 1]) if i > 0 else None
        last_frame = orc.image_to_data_uri(stage_image_paths[i])

        job_id = orc.create_video_job(
            cfg.openrouter_api_key,
            cfg.video_model,
            prompt,
            duration=cfg.clip_duration_sec,
            aspect_ratio=cfg.aspect_ratio,
            resolution=cfg.resolution,
            generate_audio=cfg.generate_audio,
            first_frame=first_frame,
            last_frame=last_frame,
        )
        video_url = orc.poll_video_job(cfg.openrouter_api_key, job_id)

        clip_path = os.path.join(work_dir, f"stage_{i + 1:02d}.mp4")
        orc.download_file(video_url, clip_path, api_key=cfg.openrouter_api_key)
        clip_paths.append(clip_path)

        if progress_cb:
            progress_cb(i + 1, total, "готово")

    return clip_paths


def stitch_with_crossfade(clip_paths: list[str], output_path: str, crossfade_sec: float = 0.6) -> str:
    if len(clip_paths) == 1:
        subprocess.run(["ffmpeg", "-y", "-i", clip_paths[0], "-c", "copy", output_path],
                        check=True, capture_output=True)
        return output_path

    durations = [_probe_duration(p) for p in clip_paths]
    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]

    filter_parts = []
    cumulative = durations[0]
    last_label = "0:v"
    for i in range(1, len(clip_paths)):
        offset = max(cumulative - crossfade_sec, 0.0)
        out_label = f"v{i}"
        filter_parts.append(
            f"[{last_label}][{i}:v]xfade=transition=fade:duration={crossfade_sec}:offset={offset}[{out_label}]"
        )
        last_label = out_label
        cumulative += durations[i] - crossfade_sec

    filter_complex = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{last_label}]",
        "-an",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path
