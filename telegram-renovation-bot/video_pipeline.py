"""Orchestrates per-stage video generation and stitches the clips into one timelapse.

Continuity trick: the last frame of each generated clip is extracted with ffmpeg and
fed back in as the first-frame image of the next stage's generation request, so the
room doesn't visually "jump" between stages. The very last stage additionally gets the
user's own reference photo as its last-frame target, so the final frame matches exactly.
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

import openrouter_client as orc

ProgressCallback = Optional[Callable[[int, int, str], None]]


def _extract_last_frame(video_path: str, out_jpg: str) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-1", "-i", video_path, "-update", "1", "-q:v", "2", out_jpg],
        check=True,
        capture_output=True,
    )
    return orc.image_to_data_uri(out_jpg)


def _probe_duration(video_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video_path],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


def generate_clips(cfg, reference_image_path: str, stage_prompts: list[str], work_dir: str,
                    progress_cb: ProgressCallback = None) -> list[str]:
    os.makedirs(work_dir, exist_ok=True)
    reference_data_uri = orc.image_to_data_uri(reference_image_path)
    clip_paths = []
    prev_last_frame = None
    total = len(stage_prompts)

    for i, prompt in enumerate(stage_prompts):
        is_last = i == total - 1
        if progress_cb:
            progress_cb(i + 1, total, "генерация")

        job_id = orc.create_video_job(
            cfg.openrouter_api_key,
            cfg.video_model,
            prompt,
            duration=cfg.clip_duration_sec,
            aspect_ratio=cfg.aspect_ratio,
            resolution=cfg.resolution,
            generate_audio=cfg.generate_audio,
            first_frame=prev_last_frame,
            last_frame=reference_data_uri if is_last else None,
        )
        video_url = orc.poll_video_job(cfg.openrouter_api_key, job_id)

        clip_path = os.path.join(work_dir, f"stage_{i + 1:02d}.mp4")
        orc.download_file(video_url, clip_path)
        clip_paths.append(clip_path)

        if not is_last:
            frame_path = os.path.join(work_dir, f"stage_{i + 1:02d}_lastframe.jpg")
            prev_last_frame = _extract_last_frame(clip_path, frame_path)

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
