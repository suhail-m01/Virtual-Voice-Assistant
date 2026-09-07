"""Existing Stability image capability without import-time network loops."""
from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path
from random import randint
from time import sleep
from typing import Optional


def _settings():
    from .config import load_settings
    return load_settings()


def open_images(prompt: str) -> None:
    from PIL import Image
    settings = _settings()
    safe = prompt.replace(" ", "_")
    path = settings.data_dir / f"{safe}1.png"
    try:
        Image.open(path).show()
    except OSError:
        return


async def generate_single_image_stability(prompt: str, image_number: int, *, api_key: Optional[str] = None) -> Optional[Path]:
    settings = _settings()
    key = api_key or settings.stability_api_key
    if not key:
        raise RuntimeError("Image generation provider is not configured")
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is required for image generation") from exc
    payload = {"text_prompts": [{"text": f"{prompt}, 4k, high-resolution, photorealistic"}], "cfg_scale": 7, "height": 1024, "width": 1024, "samples": 1, "steps": 30, "seed": randint(0, 4294967295)}
    response = await asyncio.to_thread(requests.post, "https://api.stability.ai/v1/generation/stable-diffusion-v1-6/text-to-image", headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {key}"}, json=payload, timeout=90)
    if response.status_code != 200:
        raise RuntimeError("Image provider request failed")
    artifacts = response.json().get("artifacts", [])
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    output: Optional[Path] = None
    for artifact in artifacts:
        output = settings.data_dir / f"{prompt.replace(' ', '_')}{image_number}.png"
        output.write_bytes(base64.b64decode(artifact["base64"]))
    return output


async def generate_images_stability(prompt: str) -> list[Path]:
    result = await generate_single_image_stability(prompt, 1)
    return [result] if result else []


def GenerateImages(prompt: str):
    paths = asyncio.run(generate_images_stability(prompt))
    open_images(prompt)
    return paths


def legacy_worker() -> None:
    """Compatibility worker for the old ImageGeneration.data protocol."""
    settings = _settings()
    marker = settings.project_dir / "Frontend" / "Files" / "ImageGeneration.data"
    try:
        prompt, status = marker.read_text(encoding="utf-8").split(",", 1)
    except (OSError, ValueError):
        return
    if status.strip().lower() == "true":
        try:
            GenerateImages(prompt)
        finally:
            marker.write_text("False, False", encoding="utf-8")


if __name__ == "__main__":
    legacy_worker()
