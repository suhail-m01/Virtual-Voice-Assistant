"""Dependency-injected application composition for the desktop shell and tests."""
from __future__ import annotations

from dataclasses import dataclass
import secrets
from pathlib import Path

from .config import Settings, load_settings
from .AI.provider_registry import ProviderRouter, registry_from_settings
from .Agent.agent import AuraAgent
from .Agent.context import ContextBuilder
from .Agent.executor import ExecutionLimits, Executor
from .Agent.planner import Planner
from .Auth.jwt import JWTService
from .Auth.models import AuthContext
from .Auth.service import AuthService
from .Payments.policy import PaymentPolicy
from .Payments.razorpay_service import PaymentService, RazorpayHTTPClient
from .Persistence.database import Database, EncryptedPayloadCodec, EncryptionUnavailable
from .Persistence.memory import MemoryRepository
from .Security.ConfidentialExecution.provider import LocalDevelopmentProvider
from .Security.audit import AuditLedger
from .Security.consent import ConsentManager
from .Security.policy import PolicyGateway
from .Tools.builtins import build_default_registry


@dataclass
class ApplicationServices:
    settings: Settings
    database: Database
    auth: AuthService
    consent: ConsentManager
    audit: AuditLedger
    payment_policy: PaymentPolicy
    payments: PaymentService
    providers: ProviderRouter
    agent: AuraAgent
    memory: MemoryRepository | None
    confidential_execution: LocalDevelopmentProvider
    development_jwt: bool = False

    def local_context(self, user_id: str = "local-development-user") -> AuthContext:
        """Context for the legacy desktop shell only.

        It is explicitly a local development session, not a substitute for login.
        Server deployments must obtain AuthContext from AuthService.validate_access.
        """
        return AuthContext(user_id, "USER", ("files.read", "files.write", "computer.volume", "clipboard.read", "terminal.execute", "payments.read", "payments.create"), authenticated=True)

    def security_status(self) -> dict[str, str]:
        attestation = self.confidential_execution.attest()
        return {
            "confidential_mode": "Local Development",
            "attestation": attestation.status.value,
            "secret_protection": "Development",
            "payment_mode": self.payment_policy.display_mode,
            "payment_lock": "PAYMENTS LOCKED" if self.payment_policy.locked else "Payments enabled",
            "audit_integrity": self.audit.verify_chain().value,
            "jwt_mode": "Ephemeral development secret" if self.development_jwt else "Configured secret",
        }


def create_application(settings: Settings | None = None) -> ApplicationServices:
    settings = settings or load_settings()
    settings.ensure_directories()
    database = Database(str(settings.database_path))
    jwt_secret = settings.jwt_secret or secrets.token_urlsafe(48)
    development_jwt = not bool(settings.jwt_secret)
    jwt = JWTService.from_secret(jwt_secret, settings.jwt_issuer, settings.jwt_audience, settings.access_token_ttl_seconds)
    auth = AuthService(str(settings.database_path), jwt, refresh_ttl_seconds=settings.refresh_token_ttl_seconds)
    consent = ConsentManager(str(settings.database_path), default_timeout_seconds=settings.payment_confirmation_seconds)
    audit = AuditLedger(str(settings.database_path))

    payment_policy = PaymentPolicy(
        locked=settings.payment_lock,
        mode=settings.razorpay_mode,
        live_acknowledged=settings.live_payments_enabled,
    )
    client = None
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        client = RazorpayHTTPClient(settings.razorpay_key_id, settings.razorpay_key_secret, mode=settings.razorpay_mode)
    payments = PaymentService(str(settings.database_path), payment_policy, client=client, webhook_secret=settings.razorpay_webhook_secret)

    provider_registry = registry_from_settings(settings)
    providers = ProviderRouter(provider_registry, preferred=settings.llm_provider)
    registry = build_default_registry(settings, provider_router=providers, payment_service=payments)
    planner = Planner(registry, providers)
    policy = PolicyGateway(consent, payment_lock=payment_policy.locked)
    executor = Executor(
        registry,
        policy,
        consent,
        audit=audit,
        limits=ExecutionLimits(settings.max_tool_calls, settings.max_retries, settings.max_planning_iterations, settings.tool_timeout_seconds),
    )

    memory = None
    try:
        codec = EncryptedPayloadCodec(settings.decode_data_key(), allow_plaintext_dev=settings.allow_plaintext_dev_storage)
        if codec.encrypted or settings.allow_plaintext_dev_storage:
            memory = MemoryRepository(database, codec)
    except (EncryptionUnavailable, ValueError):
        # The UI can run without long-term memory, but it must not silently fall
        # back to plaintext for private data.
        memory = None
    agent = AuraAgent(planner, executor, consent, context_builder=ContextBuilder(memory), limits=executor.limits)
    return ApplicationServices(settings, database, auth, consent, audit, payment_policy, payments, providers, agent, memory, LocalDevelopmentProvider(), development_jwt)
