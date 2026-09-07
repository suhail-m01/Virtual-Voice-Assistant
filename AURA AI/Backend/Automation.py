"""Aura 2024 capability adapters.

The 2026 agent wraps these deterministic functions as registry tools.  They are
kept as public functions so existing integrations and old command labels continue
to work, but they are no longer the intelligence/routing layer.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import os
import platform
import re
import subprocess
from typing import Any
from urllib.parse import quote_plus
import webbrowser


def GoogleSearch(topic: str) -> bool:
    if not topic.strip():
        return False
    try:
        from googlesearch import search
        list(search(topic, num_results=5))
    except Exception:
        webbrowser.open("https://www.google.com/search?q=" + quote_plus(topic))
    return True


def Content(topic: str) -> bool:
    """Generate content through the provider-independent Chatbot adapter."""
    clean_topic = re.sub(r"^content\s*", "", topic, flags=re.I).strip()
    if not clean_topic:
        return False
    try:
        from .Chatbot import ChatBot
        content = ChatBot(clean_topic)
    except Exception:
        return False
    try:
        data_dir = Path(__file__).resolve().parents[1] / "Data"
        data_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", clean_topic.lower()).strip("_")[:80] or "aura_content"
        path = data_dir / f"{safe_name}.txt"
        path.write_text(content, encoding="utf-8")
        if platform.system() == "Windows":
            try:
                subprocess.Popen(["notepad.exe", str(path)], shell=False)
            except OSError:
                pass
        return True
    except OSError:
        return False


def YouTubeSearch(topic: str) -> bool:
    if not topic.strip():
        return False
    webbrowser.open("https://www.youtube.com/results?search_query=" + quote_plus(topic))
    return True


def PlayYoutube(query: str) -> bool:
    try:
        from pywhatkit import playonyt
        playonyt(query)
        return True
    except Exception:
        return YouTubeSearch(query)


def OpenApp(app: str, *args: Any, **kwargs: Any) -> bool:
    if not app.strip() or "\n" in app or "\r" in app:
        return False
    if re.match(r"^https?://", app, re.I):
        return bool(webbrowser.open(app))
    try:
        from AppOpener import open as appopen
        appopen(app, match_closest=True, output=True, throw_error=True)
        return True
    except Exception:
        # Do not search the internet for an arbitrary executable. Only use the
        # platform's explicitly registered application opener as a fallback.
        if platform.system() == "Windows":
            try:
                os.startfile(app)  # type: ignore[attr-defined]
                return True
            except Exception:
                return False
        return False


def CloseApp(app: str) -> bool:
    if not app.strip():
        return False
    try:
        from AppOpener import close
        close(app, match_closest=True, output=True, throw_error=True)
        return True
    except Exception:
        if app.lower() == "chrome" and platform.system() == "Windows":
            try:
                subprocess.run(["taskkill", "/f", "/im", "chrome.exe"], check=True, shell=False, capture_output=True)
                return True
            except Exception:
                return False
        return False


def System(command: str) -> bool:
    allowed = {"mute", "unmute", "volume up", "volume down"}
    command = command.lower().strip()
    if command not in allowed:
        return False
    try:
        import keyboard
        keyboard.press_and_release("volume mute" if command in {"mute", "unmute"} else command)
        return True
    except Exception:
        return False


async def TranslateAndExecute(commands: list[str]):
    """Compatibility executor for old labels; no shell or arbitrary Python."""
    from .Agent.legacy import parse_legacy_labels
    from .Agent.tool_registry import ToolRegistry
    from .Tools.builtins import build_default_registry
    from .config import load_settings
    settings = load_settings()
    registry = build_default_registry(settings)
    plan = parse_legacy_labels(commands)
    results = []
    for step in plan.steps:
        spec = registry.maybe_get(step.tool_call.name)
        if not spec:
            continue
        try:
            params = spec.validate_parameters(step.tool_call.parameters)
            value = spec.handler(**params)
            if asyncio.iscoroutine(value):
                value = await value
            results.append(value)
        except Exception as exc:
            results.append(exc)
        yield results[-1]


async def Automation(commands: list[str]):
    results = []
    async for result in TranslateAndExecute(commands):
        results.append(result)
    return bool(results) or not commands
