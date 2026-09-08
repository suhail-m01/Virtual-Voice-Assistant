"""AURA 2026 desktop entry point.

The 2024 speech and capability adapters remain available, while the normal path
now uses the bounded structured agent and security gateway.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading
import time

from Backend.application import ApplicationServices, create_application
from Backend.SpeechToText import SpeechRecognition
from Backend.TextToSpeech import TextToSpeech
from Frontend.GUI import (
    GraphicalUserInterface,
    GetAssistantStatus,
    GetMicrophoneStatus,
    SetAsssistantStatus,
    SetMicrophoneStatus,
    ShowTextToScreen,
    TempDirectoryPath,
)

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "Data"
USERNAME = "User"
ASSISTANT_NAME = "AURA"
DEFAULT_MESSAGE = f"{USERNAME}: Hello {ASSISTANT_NAME}.\n{ASSISTANT_NAME}: Welcome. How may I help you?"


def _settings_values() -> tuple[str, str]:
    try:
        from Backend.config import load_settings
        settings = load_settings()
        return settings.username, settings.assistant_name
    except Exception:
        return USERNAME, ASSISTANT_NAME


def ShowDefaultChatIfNoChats() -> None:
    chat_path = DATA_DIR / "ChatLog.json"
    if not chat_path.exists() or not chat_path.read_text(encoding="utf-8").strip():
        chat_path.parent.mkdir(parents=True, exist_ok=True)
        chat_path.write_text("[]", encoding="utf-8")
        ShowTextToScreen(DEFAULT_MESSAGE)


def ReadChatLogJson() -> list[dict[str, str]]:
    try:
        value = json.loads((DATA_DIR / "ChatLog.json").read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def ChatLogIntegration() -> None:
    username, assistant = _settings_values()
    lines: list[str] = []
    for entry in ReadChatLogJson():
        if not isinstance(entry, dict) or not isinstance(entry.get("content"), str):
            continue
        label = username if entry.get("role") == "user" else assistant if entry.get("role") == "assistant" else entry.get("role", "Aura")
        lines.append(f"{label}: {entry['content']}")
    Path(TempDirectoryPath("Database.data")).write_text("\n".join(lines), encoding="utf-8")


def ShowChatOnGUI() -> None:
    try:
        content = Path(TempDirectoryPath("Database.data")).read_text(encoding="utf-8")
        if content:
            ShowTextToScreen(content)
    except OSError:
        pass


def InitialExecution() -> None:
    SetMicrophoneStatus("False")
    SetAsssistantStatus("Available...")
    ShowDefaultChatIfNoChats()
    ChatLogIntegration()
    ShowChatOnGUI()


def MainExecution(query: str | None = None, *, services: ApplicationServices | None = None) -> bool:
    services = services or create_application()
    username, assistant = _settings_values()
    try:
        SetAsssistantStatus("Listening...")
        if query is None:
            query = SpeechRecognition()
        if not query:
            return False
        ShowTextToScreen(f"{username}: {query}")
        SetAsssistantStatus("Understanding...")
        response = services.agent.handle(query, auth=services.local_context(), on_event=lambda event: SetAsssistantStatus(event.status or event.message or "Executing..."))
        ShowTextToScreen(f"{assistant}: {response.message}")
        SetAsssistantStatus("Awaiting approval..." if response.awaiting_approval else "Available...")
        # The TTS adapter already keeps long responses concise; technical detail
        # stays visible in the chat surface rather than being read aloud.
        TextToSpeech(response.message)
        return response.status.value not in {"FAILED"}
    except Exception:
        SetAsssistantStatus("Available...")
        ShowTextToScreen(f"{assistant}: I could not complete that safely.")
        return False


def FirstThread(services: ApplicationServices) -> None:
    while True:
        try:
            if GetMicrophoneStatus().lower() == "true":
                SetMicrophoneStatus("False")
                MainExecution(services=services)
            elif "Available" not in GetAssistantStatus():
                SetAsssistantStatus("Available...")
            time.sleep(0.1)
        except Exception:
            time.sleep(1)


def SecondThread(services: ApplicationServices) -> int:
    return GraphicalUserInterface(services)


def console_mode() -> None:
    services = create_application()
    print("AURA 2026 console mode. Type 'exit' to stop.")
    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query.lower() in {"exit", "quit"}:
            break
        response = services.agent.handle(query, auth=services.local_context())
        print(f"AURA: {response.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AURA 2026 secure voice-first assistant")
    parser.add_argument("--console", action="store_true", help="run without the PyQt5 shell")
    args = parser.parse_args()
    InitialExecution()
    if args.console:
        console_mode()
        return 0
    services = create_application()
    try:
        from PyQt5.QtWidgets import QApplication  # noqa: F401
    except ImportError:
        console_mode()
        return 0
    threading.Thread(target=FirstThread, args=(services,), daemon=True).start()
    return SecondThread(services)


if __name__ == "__main__":
    raise SystemExit(main())
