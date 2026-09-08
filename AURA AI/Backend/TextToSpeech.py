"""Non-blocking-friendly TTS adapter retaining the existing Edge TTS voice."""
from __future__ import annotations

import asyncio
from pathlib import Path
import random
from typing import Callable

from .config import load_settings


async def TextToAudioFile(text: str) -> None:
    settings = load_settings()
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed") from exc
    output = settings.data_dir / "speech.mp3"
    communicate = edge_tts.Communicate(text, settings.assistant_voice, pitch="+5Hz", rate="+13%")
    await communicate.save(str(output))


def TTS(text: str, func: Callable = lambda *_: True):
    try:
        asyncio.run(TextToAudioFile(text))
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(str(load_settings().data_dir / "speech.mp3"))
            pygame.mixer.music.play()
            clock = pygame.time.Clock()
            while pygame.mixer.music.get_busy():
                if not func():
                    break
                clock.tick(10)
            return True
        finally:
            try:
                func(False)
            except Exception:
                pass
            try:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
            except Exception:
                pass
    except Exception:
        return False


def TextToSpeech(text: str, func: Callable = lambda *_: True):
    parts = str(text).split(".")
    if len(parts) > 4 and len(str(text)) >= 250:
        text = " ".join(parts[:2]) + ". The rest of the answer is on the chat screen."
    return TTS(text, func)


if __name__ == "__main__":
    while True:
        TextToSpeech(input("Enter the text: "))
