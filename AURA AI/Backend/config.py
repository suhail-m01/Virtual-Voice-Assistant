"""Central, validated configuration for AURA.

The original application loaded values from ``.env`` independently in nearly
 every module.  This module is the single configuration boundary.  It deliberately
 never prints secrets and it accepts the legacy variable names used by Aura 2024.

The project keeps a standard-library implementation so the capability layer can
still be imported on a clean Windows installation.  Deployments may replace this
with Pydantic Settings without changing callers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import base64
import os
from pathlib import Path
from typing import Mapping, Optional, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[1]
_REPO_DIR = PROJECT_DIR.parent


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse the small, non-expanding subset of dotenv used by AURA.

    ``python-dotenv`` remains a supported dependency, but parsing locally keeps
    imports safe when optional dependencies are not installed (for example during
    security tests).  Values from the process environment always win.
    """
    values: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].lstrip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]
                values[key] = value
    except FileNotFoundError:
        pass
    return values


def _environment(dotenv_path: Optional[Path] = None) -> dict[str, str]:
    paths = []
    if dotenv_path:
        paths.append(dotenv_path)
    paths.extend([Path.cwd() / ".env", PROJECT_DIR / ".env", _REPO_DIR / ".env"])
    values: dict[str, str] = {}
    for path in paths:
        values.update(_parse_dotenv(path))
    values.update({key: value for key, value in os.environ.items() if value is not None})
    return values


def _get(env: Mapping[str, str], name: str, *legacy: str, default: str = "") -> str:
    for candidate in (name, *legacy):
        value = env.get(candidate)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = _get(env, name, default="true" if default else "false").lower()
    return value in {"1", "true", "yes", "y", "on"}


def _int(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    value = _get(env, name, default=str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _path_list(raw: str, fallback: Tuple[Path, ...]) -> Tuple[Path, ...]:
    if not raw:
        return fallback
    separator = os.pathsep
    return tuple(Path(part).expanduser().resolve() for part in raw.split(separator) if part.strip()) or fallback


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings.

    Secrets are retained only in memory.  ``safe_summary`` is the only intended
    representation for diagnostics and intentionally excludes all secret values.
    """

    project_dir: Path = PROJECT_DIR
    data_dir: Path = PROJECT_DIR / "Data"
    runtime_dir: Path = PROJECT_DIR / "Runtime"
    database_path: Path = PROJECT_DIR / "Runtime" / "aura.db"
    username: str = "User"
    assistant_name: str = "AURA"
    input_language: str = "en-US"
    assistant_voice: str = "en-US-AriaNeural"

    llm_provider: str = "auto"
    llm_model: str = ""
    reasoning_provider: str = ""
    vision_provider: str = ""
    local_provider: str = "local"
    privacy_mode: str = "balanced"

    groq_api_key: str = field(default="", repr=False)
    cohere_api_key: str = field(default="", repr=False)
    stability_api_key: str = field(default="", repr=False)
    razorpay_key_id: str = field(default="", repr=False)
    razorpay_key_secret: str = field(default="", repr=False)
    razorpay_webhook_secret: str = field(default="", repr=False)
    jwt_secret: str = field(default="", repr=False)
    jwt_private_key: str = field(default="", repr=False)
    jwt_public_key: str = field(default="", repr=False)
    data_encryption_key: str = field(default="", repr=False)

    jwt_issuer: str = "aura-2026"
    jwt_audience: str = "aura-client"
    access_token_ttl_seconds: int = 600
    refresh_token_ttl_seconds: int = 2_592_000
    max_tool_calls: int = 12
    max_retries: int = 2
    max_planning_iterations: int = 4
    tool_timeout_seconds: int = 30
    payment_confirmation_seconds: int = 120
    payment_lock: bool = True
    razorpay_mode: str = "test"
    live_payment_acknowledgement: str = ""
    allow_plaintext_dev_storage: bool = False
    enable_legacy_chat_log: bool = True
    allowed_file_roots: Tuple[Path, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, dotenv_path: Optional[Path] = None) -> "Settings":
        env = _environment(dotenv_path)
        data_dir = Path(_get(env, "AURA_DATA_DIR", default=str(PROJECT_DIR / "Data"))).expanduser().resolve()
        runtime_dir = Path(_get(env, "AURA_RUNTIME_DIR", default=str(PROJECT_DIR / "Runtime"))).expanduser().resolve()
        database_path = Path(_get(env, "AURA_DATABASE_PATH", default=str(runtime_dir / "aura.db"))).expanduser().resolve()
        fallback_roots = (data_dir, Path.home().resolve())
        mode = _get(env, "RAZORPAY_MODE", default="test").lower()
        if mode not in {"test", "live"}:
            raise ValueError("RAZORPAY_MODE must be 'test' or 'live'")
        privacy = _get(env, "AURA_PRIVACY_MODE", default="balanced").lower()
        if privacy not in {"strict", "balanced", "off"}:
            raise ValueError("AURA_PRIVACY_MODE must be strict, balanced, or off")
        return cls(
            project_dir=PROJECT_DIR,
            data_dir=data_dir,
            runtime_dir=runtime_dir,
            database_path=database_path,
            username=_get(env, "AURA_USERNAME", "Username", default="User"),
            assistant_name=_get(env, "AURA_ASSISTANT_NAME", "Assistantname", default="AURA"),
            input_language=_get(env, "AURA_INPUT_LANGUAGE", "InputLanguage", default="en-US"),
            assistant_voice=_get(env, "AURA_ASSISTANT_VOICE", "AssistantVoice", default="en-US-AriaNeural"),
            llm_provider=_get(env, "LLM_PROVIDER", default="auto").lower(),
            llm_model=_get(env, "LLM_MODEL", default=""),
            reasoning_provider=_get(env, "REASONING_PROVIDER", default=""),
            vision_provider=_get(env, "VISION_PROVIDER", default=""),
            local_provider=_get(env, "LOCAL_PROVIDER", default="local"),
            privacy_mode=privacy,
            groq_api_key=_get(env, "GROQ_API_KEY", "GroqAPIKey"),
            cohere_api_key=_get(env, "COHERE_API_KEY", "CohereAPIKey"),
            stability_api_key=_get(env, "STABILITY_API_KEY", "StabilityAI_APIKey"),
            razorpay_key_id=_get(env, "RAZORPAY_KEY_ID"),
            razorpay_key_secret=_get(env, "RAZORPAY_KEY_SECRET"),
            razorpay_webhook_secret=_get(env, "RAZORPAY_WEBHOOK_SECRET"),
            jwt_secret=_get(env, "JWT_SECRET"),
            jwt_private_key=_get(env, "JWT_PRIVATE_KEY"),
            jwt_public_key=_get(env, "JWT_PUBLIC_KEY"),
            data_encryption_key=_get(env, "AURA_DATA_ENCRYPTION_KEY"),
            jwt_issuer=_get(env, "JWT_ISSUER", default="aura-2026"),
            jwt_audience=_get(env, "JWT_AUDIENCE", default="aura-client"),
            access_token_ttl_seconds=_int(env, "JWT_ACCESS_TTL_SECONDS", 600, 60, 3600),
            refresh_token_ttl_seconds=_int(env, "JWT_REFRESH_TTL_SECONDS", 2_592_000, 300, 31_536_000),
            max_tool_calls=_int(env, "AURA_MAX_TOOL_CALLS", 12, 1, 100),
            max_retries=_int(env, "AURA_MAX_RETRIES", 2, 0, 10),
            max_planning_iterations=_int(env, "AURA_MAX_PLANNING_ITERATIONS", 4, 1, 20),
            tool_timeout_seconds=_int(env, "AURA_TOOL_TIMEOUT_SECONDS", 30, 1, 600),
            payment_confirmation_seconds=_int(env, "PAYMENT_CONFIRMATION_SECONDS", 120, 15, 600),
            payment_lock=_bool(env, "PAYMENT_LOCK", True),
            razorpay_mode=mode,
            live_payment_acknowledgement=_get(env, "RAZORPAY_LIVE_ACKNOWLEDGEMENT"),
            allow_plaintext_dev_storage=_bool(env, "AURA_ALLOW_PLAINTEXT_DEV_STORAGE", False),
            enable_legacy_chat_log=_bool(env, "AURA_ENABLE_LEGACY_CHAT_LOG", True),
            allowed_file_roots=_path_list(_get(env, "AURA_ALLOWED_FILE_ROOTS"), fallback_roots),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def has_cloud_llm_credentials(self) -> bool:
        return bool(self.groq_api_key or self.cohere_api_key)

    @property
    def live_payments_enabled(self) -> bool:
        return self.razorpay_mode == "live" and self.live_payment_acknowledgement == "I_UNDERSTAND_LIVE_PAYMENTS"

    def decode_data_key(self) -> Optional[bytes]:
        if not self.data_encryption_key:
            return None
        raw = self.data_encryption_key.strip()
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("AURA_DATA_ENCRYPTION_KEY must be urlsafe base64") from exc
        if len(key) != 32:
            raise ValueError("AURA_DATA_ENCRYPTION_KEY must decode to 32 bytes")
        return key

    def safe_summary(self) -> dict[str, object]:
        return {
            "assistant_name": self.assistant_name,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model or "provider default",
            "privacy_mode": self.privacy_mode,
            "razorpay_mode": self.razorpay_mode.upper(),
            "payment_lock": self.payment_lock,
            "live_payments_enabled": self.live_payments_enabled,
            "has_cloud_llm_credentials": self.has_cloud_llm_credentials,
            "data_encryption_configured": bool(self.data_encryption_key),
            "allowed_file_roots": [str(path) for path in self.allowed_file_roots],
        }


# A function, rather than a module-level Settings instance, avoids importing the
# environment at test collection time and makes dependency injection explicit.
def load_settings(dotenv_path: Optional[Path] = None) -> Settings:
    settings = Settings.from_env(dotenv_path)
    settings.ensure_directories()
    return settings
