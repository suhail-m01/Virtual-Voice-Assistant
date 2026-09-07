"""Deterministic adapters for Aura's existing capability layer."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Optional
from urllib.parse import quote_plus
import webbrowser

from ..Agent.tool_registry import ToolRegistry, ToolSpec
from ..Security.consent import RiskLevel


class ToolUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FileToolConfig:
    roots: tuple[Path, ...]
    data_dir: Path

    def safe(self, raw: str, *, must_exist: bool = False) -> Path:
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 1000:
            raise ValueError("A valid path is required")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.data_dir / path
        resolved = path.resolve(strict=False)
        if not any(resolved == root or root in resolved.parents for root in self.roots):
            raise PermissionError("Path is outside Aura's approved file roots")
        if must_exist and not resolved.exists():
            raise FileNotFoundError("File not found")
        return resolved


def _legacy_automation(name: str, *args):
    try:
        from .. import Automation
        function = getattr(Automation, name)
        return function(*args)
    except ImportError as exc:
        raise ToolUnavailable("Computer automation dependencies are not installed") from exc


def open_application(app_name: str) -> dict[str, Any]:
    if not app_name.strip() or len(app_name) > 120:
        raise ValueError("Application name is invalid")
    if re.search(r"[\r\n]", app_name):
        raise ValueError("Application name contains invalid characters")
    # Existing AppOpener behavior is reused through an adapter. URL opening is
    # kept deterministic and does not use a shell.
    if re.match(r"^https?://", app_name, re.I):
        webbrowser.open(app_name)
        return {"opened": app_name, "kind": "url"}
    result = _legacy_automation("OpenApp", app_name)
    return {"opened": app_name, "result": bool(result)}


def close_application(app_name: str) -> dict[str, Any]:
    result = _legacy_automation("CloseApp", app_name)
    return {"closed": app_name, "result": bool(result)}


def search_web(query: str) -> dict[str, Any]:
    if not query.strip() or len(query) > 500:
        raise ValueError("Search query is invalid")
    try:
        from ..RealtimeSearchEngine import GoogleSearch
        result = GoogleSearch(query)
        return {"query": query, "results": result}
    except Exception:
        url = "https://www.google.com/search?q=" + quote_plus(query)
        webbrowser.open(url)
        return {"query": query, "opened": url}


def google_search(query: str) -> dict[str, Any]:
    return search_web(query)


def youtube_search(query: str) -> dict[str, Any]:
    if not query.strip() or len(query) > 500:
        raise ValueError("Search query is invalid")
    url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    webbrowser.open(url)
    return {"query": query, "opened": url}


def play_media(query: str) -> dict[str, Any]:
    if not query.strip() or len(query) > 300:
        raise ValueError("Media query is invalid")
    result = _legacy_automation("PlayYoutube", query)
    return {"query": query, "played": bool(result)}


def system_volume(command: str) -> dict[str, Any]:
    allowed = {"mute", "unmute", "volume up", "volume down"}
    command = command.lower().strip()
    if command not in allowed:
        raise ValueError("Unsupported volume action")
    result = _legacy_automation("System", command)
    return {"command": command, "success": bool(result)}


def generate_content(topic: str) -> dict[str, Any]:
    if not topic.strip() or len(topic) > 500:
        raise ValueError("Content topic is invalid")
    result = _legacy_automation("Content", topic)
    return {"topic": topic, "success": bool(result)}


def generate_image(prompt: str) -> dict[str, Any]:
    if not prompt.strip() or len(prompt) > 500:
        raise ValueError("Image prompt is invalid")
    try:
        from ..ImageGeneration import GenerateImages
        GenerateImages(prompt)
        return {"prompt": prompt, "success": True}
    except ImportError as exc:
        raise ToolUnavailable("Image generation dependencies are not installed") from exc


def search_files(query: str, sort: str = "modified_desc", limit: int = 10, *, config: FileToolConfig) -> dict[str, Any]:
    if not query.strip() or len(query) > 200:
        raise ValueError("File search query is invalid")
    if sort not in {"modified_desc", "name_asc"} or not 1 <= limit <= 50:
        raise ValueError("Invalid file search options")
    terms = [term.lower() for term in re.findall(r"[\w.-]+", query) if term]
    candidates: list[tuple[float, Path]] = []
    for root in config.roots:
        if not root.exists():
            continue
        try:
            iterator = root.rglob("*")
            for path in iterator:
                if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
                    continue
                if terms and not all(term in path.name.lower() or term in str(path.parent).lower() for term in terms):
                    continue
                try:
                    candidates.append((path.stat().st_mtime, path))
                except OSError:
                    continue
        except (OSError, PermissionError):
            continue
    candidates.sort(key=(lambda item: (-item[0], item[1].name.lower())) if sort == "modified_desc" else (lambda item: item[1].name.lower()))
    selected = candidates[:limit]
    paths = [str(path) for _, path in selected]
    return {"query": query, "count": len(paths), "candidates": paths, "selected_path": paths[0] if paths else None}


def open_file(path: str, *, config: FileToolConfig) -> dict[str, Any]:
    safe_path = config.safe(path, must_exist=True)
    if not safe_path.is_file():
        raise ValueError("Only files can be opened")
    if hasattr(os, "startfile"):
        os.startfile(str(safe_path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(safe_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(safe_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        return {"path": str(safe_path), "opened": False, "message": "Desktop file opener is unavailable on this host"}
    return {"path": str(safe_path), "opened": True}


def read_file(path: str, *, config: FileToolConfig, max_bytes: int = 100_000) -> dict[str, Any]:
    safe_path = config.safe(path, must_exist=True)
    if not safe_path.is_file() or safe_path.stat().st_size > max_bytes:
        raise ValueError("File is unavailable or too large")
    return {"path": str(safe_path), "content": safe_path.read_text(encoding="utf-8", errors="replace")}


def create_file(path: str, content: str, *, config: FileToolConfig) -> dict[str, Any]:
    safe_path = config.safe(path)
    if safe_path.exists():
        raise FileExistsError("File already exists")
    if len(content) > 500_000:
        raise ValueError("Content is too large")
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_text(content, encoding="utf-8")
    return {"path": str(safe_path), "created": True}


def create_folder(path: str, *, config: FileToolConfig) -> dict[str, Any]:
    safe_path = config.safe(path)
    if safe_path.exists():
        raise FileExistsError("Folder already exists")
    safe_path.mkdir(parents=True, exist_ok=False)
    return {"path": str(safe_path), "created": True}


def open_folder(path: str, *, config: FileToolConfig) -> dict[str, Any]:
    safe_path = config.safe(path, must_exist=True)
    if not safe_path.is_dir():
        raise ValueError("Only folders can be opened")
    if hasattr(os, "startfile"):
        os.startfile(str(safe_path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(safe_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(safe_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        return {"path": str(safe_path), "opened": False, "message": "Desktop folder opener is unavailable on this host"}
    return {"path": str(safe_path), "opened": True}


def move_file(source: str, destination: str, *, config: FileToolConfig) -> dict[str, Any]:
    source_path = config.safe(source, must_exist=True)
    destination_path = config.safe(destination)
    if destination_path.exists():
        raise FileExistsError("Destination already exists")
    shutil.move(str(source_path), str(destination_path))
    return {"source": str(source_path), "destination": str(destination_path), "moved": True}


def rename_file(path: str, new_name: str, *, config: FileToolConfig) -> dict[str, Any]:
    source_path = config.safe(path, must_exist=True)
    if not re.fullmatch(r"[^\\/:*?\"<>|]{1,200}", new_name):
        raise ValueError("Invalid file name")
    destination = config.safe(str(source_path.parent / new_name))
    if destination.exists():
        raise FileExistsError("Destination already exists")
    source_path.rename(destination)
    return {"old_path": str(source_path), "new_path": str(destination), "renamed": True}


def read_clipboard() -> dict[str, Any]:
    try:
        import pyperclip
        return {"content": pyperclip.paste()[:100_000]}
    except Exception as exc:
        raise ToolUnavailable("Clipboard access is unavailable") from exc


def run_approved_terminal_command(executable: str, args: list[str], *, cwd: Optional[str] = None, config: FileToolConfig) -> dict[str, Any]:
    """Run a small allowlist without a shell; arbitrary command execution is not exposed."""
    executable = Path(executable).name.lower()
    allowed = {"git", "python", "python3", "pytest", "npm", "node"}
    if executable not in allowed or not isinstance(args, list) or len(args) > 20 or any(not isinstance(arg, str) or len(arg) > 300 for arg in args):
        raise PermissionError("Terminal command is not on Aura's approved allowlist")
    if any(token in " ".join(args) for token in ("&&", "||", ";", "|", ">", "<", "`", "$", "\n", "\r")):
        raise PermissionError("Shell operators are not allowed")
    if executable == "python" or executable == "python3":
        if not args or args[0] in {"-c", "-u", "-i"}:
            raise PermissionError("Inline or interactive Python is not approved")
        if args[0] == "-m" and (len(args) < 2 or args[1] not in {"pytest", "http.server"}):
            raise PermissionError("Python module is not approved")
        if args[0] not in {"--version", "--help", "-m"}:
            raise PermissionError("Python script execution is not approved")
    if executable == "npm" and (not args or args[0] != "run" or len(args) < 2 or args[1] not in {"start", "test", "build"}):
        raise PermissionError("npm script is not approved")
    if executable == "git" and args and args[0] not in {"status", "diff", "log"}:
        raise PermissionError("Git subcommand is not approved")
    working = config.safe(cwd) if cwd else config.roots[0]
    if not working.is_dir():
        raise ValueError("Working directory is invalid")
    completed = subprocess.run([executable, *args], cwd=str(working), capture_output=True, text=True, timeout=30, shell=False)
    return {"return_code": completed.returncode, "stdout": completed.stdout[-20_000:], "stderr": completed.stderr[-20_000:]}


def answer_question(query: str, *, provider_router=None, realtime: bool = False) -> dict[str, Any]:
    if not query.strip() or len(query) > 4000:
        raise ValueError("Question is invalid")
    if realtime:
        result = search_web(query)
        return {"answer": result.get("results", result), "realtime": True}
    if provider_router is None:
        return {"answer": "I can help with that when an AI provider is configured."}
    try:
        response = provider_router.generate(query)
        return {"answer": response.text, "provider": response.provider}
    except Exception:
        return {"answer": "I am ready, but no conversational AI provider is configured yet."}


def build_default_registry(settings, *, provider_router=None, payment_service=None) -> ToolRegistry:
    registry = ToolRegistry()
    file_config = FileToolConfig(tuple(settings.allowed_file_roots), settings.data_dir)
    add = registry.register
    string = lambda maximum=500: {"type": "string", "maxLength": maximum}
    add(ToolSpec("open_application", "Open a named application or approved URL.", {"type": "object", "properties": {"app_name": string(120)}, "required": ["app_name"]}, RiskLevel.LOW, None, False, 30, {"type": "object"}, open_application))
    add(ToolSpec("close_application", "Close a named application.", {"type": "object", "properties": {"app_name": string(120)}, "required": ["app_name"]}, RiskLevel.LOW, None, False, 30, {"type": "object"}, close_application))
    add(ToolSpec("search_web", "Search the web using the existing search capability.", {"type": "object", "properties": {"query": string()}, "required": ["query"]}, RiskLevel.LOW, None, False, 30, {"type": "object"}, search_web))
    add(ToolSpec("google_search", "Search Google using the existing capability.", {"type": "object", "properties": {"query": string()}, "required": ["query"]}, RiskLevel.LOW, None, False, 30, {"type": "object"}, google_search))
    add(ToolSpec("youtube_search", "Search YouTube.", {"type": "object", "properties": {"query": string()}, "required": ["query"]}, RiskLevel.LOW, None, False, 30, {"type": "object"}, youtube_search))
    add(ToolSpec("play_media", "Play requested media through the existing YouTube capability.", {"type": "object", "properties": {"query": string(300)}, "required": ["query"]}, RiskLevel.LOW, None, False, 45, {"type": "object"}, play_media))
    add(ToolSpec("system_volume", "Mute or adjust system volume.", {"type": "object", "properties": {"command": {"type": "string", "enum": ["mute", "unmute", "volume up", "volume down"]}}, "required": ["command"]}, RiskLevel.LOW, "computer.volume", False, 15, {"type": "object"}, system_volume))
    add(ToolSpec("generate_content", "Generate content with Aura's existing content capability.", {"type": "object", "properties": {"topic": string()}, "required": ["topic"]}, RiskLevel.LOW, None, False, 60, {"type": "object"}, generate_content))
    add(ToolSpec("generate_image", "Generate an image with the existing image provider.", {"type": "object", "properties": {"prompt": string()}, "required": ["prompt"]}, RiskLevel.LOW, None, False, 180, {"type": "object"}, generate_image))
    add(ToolSpec("search_files", "Search approved local roots and return candidates plus the newest selected path.", {"type": "object", "properties": {"query": string(200), "sort": {"type": "string", "enum": ["modified_desc", "name_asc"]}, "limit": {"type": "integer"}}, "required": ["query"]}, RiskLevel.SENSITIVE, "files.read", False, 30, {"type": "object"}, lambda query, sort="modified_desc", limit=10: search_files(query, sort, limit, config=file_config)))
    add(ToolSpec("open_file", "Open an approved local file.", {"type": "object", "properties": {"path": string(1000)}, "required": ["path"]}, RiskLevel.SENSITIVE, "files.read", True, 30, {"type": "object"}, lambda path: open_file(path, config=file_config)))
    add(ToolSpec("open_folder", "Open an approved local folder.", {"type": "object", "properties": {"path": string(1000)}, "required": ["path"]}, RiskLevel.SENSITIVE, "files.read", True, 30, {"type": "object"}, lambda path: open_folder(path, config=file_config)))
    add(ToolSpec("read_file", "Read an approved local text file.", {"type": "object", "properties": {"path": string(1000)}, "required": ["path"]}, RiskLevel.SENSITIVE, "files.read", True, 30, {"type": "object"}, lambda path: read_file(path, config=file_config)))
    add(ToolSpec("create_file", "Create a file inside approved roots.", {"type": "object", "properties": {"path": string(1000), "content": string(500000)}, "required": ["path", "content"]}, RiskLevel.SENSITIVE, "files.write", True, 30, {"type": "object"}, lambda path, content: create_file(path, content, config=file_config)))
    add(ToolSpec("create_folder", "Create a folder inside approved roots.", {"type": "object", "properties": {"path": string(1000)}, "required": ["path"]}, RiskLevel.SENSITIVE, "files.write", True, 30, {"type": "object"}, lambda path: create_folder(path, config=file_config)))
    add(ToolSpec("move_file", "Move a file inside approved roots.", {"type": "object", "properties": {"source": string(1000), "destination": string(1000)}, "required": ["source", "destination"]}, RiskLevel.DESTRUCTIVE, "files.write", True, 30, {"type": "object"}, lambda source, destination: move_file(source, destination, config=file_config)))
    add(ToolSpec("rename_file", "Rename a file inside approved roots.", {"type": "object", "properties": {"path": string(1000), "new_name": string(200)}, "required": ["path", "new_name"]}, RiskLevel.DESTRUCTIVE, "files.write", True, 30, {"type": "object"}, lambda path, new_name: rename_file(path, new_name, config=file_config)))
    add(ToolSpec("read_clipboard", "Read the current clipboard through an installed clipboard adapter.", {"type": "object", "properties": {}, "required": []}, RiskLevel.SENSITIVE, "clipboard.read", True, 15, {"type": "object"}, read_clipboard))
    add(ToolSpec("run_approved_terminal_command", "Run only an allowlisted executable without a shell.", {"type": "object", "properties": {"executable": string(80), "args": {"type": "array"}, "cwd": string(1000)}, "required": ["executable", "args"]}, RiskLevel.SENSITIVE, "terminal.execute", True, 30, {"type": "object"}, lambda executable, args, cwd=None: run_approved_terminal_command(executable, args, cwd=cwd, config=file_config)))
    add(ToolSpec("answer_question", "Answer a general question with a configured provider.", {"type": "object", "properties": {"query": string(4000), "realtime": {"type": "boolean"}}, "required": ["query"]}, RiskLevel.LOW, None, False, 90, {"type": "object"}, lambda query, realtime=False: answer_question(query, provider_router=provider_router, realtime=realtime)))

    if payment_service is not None:
        def create_link(amount_minor: int, currency: str, description: str, user_id: str = "", approval_reference: str = ""):
            from ..Payments.models import Money, PaymentIntent
            intent = PaymentIntent(user_id or "unknown", Money(amount_minor, currency), description, "CREATE_PAYMENT_LINK", approval_reference or None)
            return payment_service.create_payment_link(intent).to_public_dict()

        def create_order(amount_minor: int, currency: str, description: str, user_id: str = "", approval_reference: str = ""):
            from ..Payments.models import Money, PaymentIntent
            intent = PaymentIntent(user_id or "unknown", Money(amount_minor, currency), description, "CREATE_ORDER", approval_reference or None)
            return payment_service.create_order(intent).to_public_dict()

        def check_status(reference: str, user_id: str = ""):
            record = payment_service.latest_for_user(user_id or "unknown")
            return {"reference": reference, "record": record.to_public_dict() if record else None}

        add(ToolSpec("create_payment_link", "Create a Razorpay payment link after exact fresh approval.", {"type": "object", "properties": {"amount_minor": {"type": "integer"}, "currency": {"type": "string", "enum": ["INR"]}, "description": string(255)}, "required": ["amount_minor", "currency", "description"]}, RiskLevel.FINANCIAL, "payments.create", True, 30, {"type": "object"}, create_link))
        add(ToolSpec("create_razorpay_order", "Create a Razorpay order after exact fresh approval.", {"type": "object", "properties": {"amount_minor": {"type": "integer"}, "currency": {"type": "string", "enum": ["INR"]}, "description": string(255)}, "required": ["amount_minor", "currency", "description"]}, RiskLevel.FINANCIAL, "payments.create", True, 30, {"type": "object"}, create_order))
        add(ToolSpec("check_payment_status", "Check the authenticated user's latest payment status.", {"type": "object", "properties": {"reference": string(100)}, "required": ["reference"]}, RiskLevel.SENSITIVE, "payments.read", False, 30, {"type": "object"}, check_status))

        def list_transactions(limit: int = 10, user_id: str = ""):
            records = payment_service.recent_for_user(user_id or "unknown", limit=limit)
            return {"transactions": [record.to_public_dict() for record in records]}

        add(ToolSpec("list_recent_transactions", "List the authenticated user's recent payment metadata.", {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}, RiskLevel.SENSITIVE, "payments.read", False, 30, {"type": "object"}, list_transactions))
    return registry
