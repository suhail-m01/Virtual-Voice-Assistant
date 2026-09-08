# AURA 2026 implementation guide

This document is the hand-off for the upgrade of the original 2024 project. It
records what is enforced in code, what is a local-development implementation,
and what still requires production infrastructure. It does not claim that a
normal PyQt5 process is a TEE or that an optional provider is configured when it
is not.

## 1. Repository audit and architecture map

The original repository was a compact desktop application:

- `main.py` polled `Mic.data`, called Selenium speech recognition, sent text to
  `Model.FirstLayerDMM`, and routed labels to `Automation`.
- `Backend/Model.py` used Cohere for hard-coded labels (`general`, `realtime`,
  `open`, `close`, `play`, `system`, `content`, Google/YouTube search, image and
  reminder labels).
- `Chatbot.py` and `RealtimeSearchEngine.py` used Groq and the flat
  `Data/ChatLog.json` transcript.
- `Automation.py` contained the reusable computer/search/content/media adapters.
- `ImageGeneration.py` used Stability AI and an IPC marker file.
- `SpeechToText.py` used Selenium/Web Speech; `TextToSpeech.py` used Edge TTS and
  pygame.
- `Frontend/GUI.py` was a two-screen black PyQt5 shell with a GIF visualizer and
  file-based status polling.
- The original implementation loaded environment variables in each module,
  imported optional SDKs at module import time, used Windows-specific paths, and
  had no authentication, authorization, consent, payment, encrypted memory or
  tamper evidence.

### Current target flow

```text
Voice / text / future vision
          |
          v
Input + deterministic privacy filter
          |
          v
User-scoped context + bounded approved memory
          |
          v
Provider router (capability + privacy aware)
          |
          v
Aura Planner -> strict ActionPlan / ToolCall schemas
          |
          v
Security Gateway
  authentication -> permission -> risk -> payment lock -> exact consent
          |
          v
Tool Registry -> deterministic adapters
  files | applications | web | media | AI | volume | Razorpay
          |
          v
Bounded Executor -> timeout/retry/cancel -> observations
          |
          v
Verification + concise progress + tamper-evident audit
          |
          v
Safe response / voice response / user-controlled memory update
```

An LLM only proposes a validated structured plan. It never receives an executor
or Python namespace and it never authorizes itself.

### Old vs new

| 2024 | AURA 2026 |
| --- | --- |
| Provider-specific classification prompt | `Backend/AI` provider interface and capability router |
| Comma-separated command labels | Strict `ActionPlan`, `PlanStep`, `ToolCall` validation |
| `if startswith("open")` dispatch | `ToolRegistry` with schema, risk, permission, consent and timeout metadata |
| Automation called directly from the main loop | `Executor` calls deterministic adapters only after `PolicyGateway` |
| Flat global `ChatLog.json` | SQLite foundation + user-scoped `MemoryRepository`; legacy adapter retained |
| API keys loaded independently | immutable centralized `Settings` layer + `.env.example` |
| No login/session model | password hashing, access JWT, rotated refresh tokens, lockout and revocation |
| Client-side payment idea | Razorpay TEST/LIVE separation, minor units, signature/webhook verification and replay guard |
| GIF-only visual feedback | reusable stateful Aura visualizer and a seven-area shell |
| Raw/implicit approvals | expiring exact-parameter `ConsentRecord` |
| No integrity check | append-only hash chain with `verify_chain()` |
| No confidential computing story | explicit local provider + fail-closed attestation/secret-release interfaces |

## Preserved capability layer

The upgrade deliberately keeps the original working capability surface and assets:

- browser/Web Speech STT path and language translation hook;
- Edge TTS voice selection, concise spoken responses and pygame playback;
- Groq/Cohere conversational and real-time search adapters when their keys are configured;
- Google search, YouTube search and YouTube playback;
- AppOpener application open/close and deterministic system-volume controls;
- Stability image generation and the legacy `ImageGeneration.data` worker protocol;
- content generation to a local text file and the original Data/Frontend assets;
- legacy `FirstLayerDMM`, `Automation`, `ChatBot` and `RealtimeSearchEngine` imports.

The old JSON chat log is wrapped by `LegacyChatLog`; new agent context uses
user-scoped persistence. Existing flat files are not silently treated as a
secure database, and no unrelated asset cleanup was performed.

## 2. Implementation status

### Implemented

- Central configuration and legacy variable compatibility.
- Strict structured schemas without requiring Pydantic at import time.
- Bounded sequential planning/execution with maximum calls, retries, timeouts,
  plan steps, cancellation and useful tool events; no chain-of-thought UI.
- Tool registry and deterministic adapters for applications, files, web/search,
  YouTube/media, image/content compatibility, volume, clipboard and an
  allowlisted no-shell terminal path.
- Authentication service: account creation, Argon2id when `argon2-cffi` is
  installed, PBKDF2-SHA256 fallback, login, progressive lockout, logout, change
  password, reset-token architecture, access-token claim validation, refresh
  rotation and replay-family revocation.
- Roles `USER` and `ADMIN`, permission checks, risk classes and policy gateway.
- Exact-action, parameter-digest-bound, expiring consent records. Generic
  `okay`, `fine`, `continue`, `maybe` and `later` do not approve payment.
- Deterministic redaction before provider calls, memory, compatibility history,
  metadata and the ledger. Credential-bearing requests are blocked.
- SQLite migrations, user-scoped repositories and authenticated-encryption
  payload codec when `cryptography` plus a 32-byte key are configured.
- Append-only SHA-256 hash-chain audit ledger and integrity verification.
- Razorpay HTTP architecture, integer INR minor units, test/live policy, global
  payment lock, signature verification, webhook verification and replay guard.
- Local-development confidential-execution status that reports unavailable
  hardware attestation and refuses secret release.
- PyQt5 shell with Home, Assistant, Activity, Payments, Security, Settings and
  Profile surfaces, central state visualizer, worker-thread agent calls and Stop.
- Compatibility imports and public functions for the 2024 capability layer.
- Dependency-light regression/security tests.

### Development Mode

- The desktop shell uses an explicitly documented `local-development-user`
  context so the legacy single-user desktop can launch. A server or multi-user
  deployment must replace this with `AuthService.validate_access()`.
- If `JWT_SECRET` is absent, the local composition root generates an ephemeral
  process secret. It is not a hard-coded secret and all sessions expire on exit;
  production must configure a secret or an asymmetric adapter.
- `LocalDevelopmentProvider` reports `Mode: Local Development`,
  `Attestation: Unavailable`, `Secret Protection: Development`.
- Without `AURA_DATA_ENCRYPTION_KEY`, long-term encrypted memory is unavailable;
  it is not silently written as plaintext. An explicit
  `AURA_ALLOW_PLAINTEXT_DEV_STORAGE=true` is available only for local tests.
- Provider adapters are lazy. Without a configured provider, Aura returns a
  safe unavailable response rather than pretending to answer or routing private
  content to a cloud model.
- The local UI shows the payment lock and TEST MODE; it does not run a checkout.

### Infrastructure Required

- Install `argon2-cffi` and `cryptography` in production; protect the AES key
  with Windows DPAPI/credential manager, an HSM, or a managed secret store
  rather than placing it beside `aura.db`.
- Configure an asymmetric JWT signer/verifier at the backend boundary. The
  dependency-free HS256 implementation is for a controlled local deployment.
- Deploy Razorpay credentials server-side, configure a webhook endpoint over TLS,
  verify signatures and use an operational transaction outbox/idempotency plan.
- Provide a real email/SMS reset-token delivery service, session revocation UI,
  secure-cookie/API transport and rate-limit storage shared across instances.
- Provide a real TDX/SEV-SNP/confidential-VM attestation verifier and
  attestation-gated secret manager before displaying `TEE Ready` or `Verified`.
- Harden the Windows computer-control allowlists and run them under a least-
  privilege service account with endpoint security review.

### Future Extension

- PostgreSQL repository adapters, semantic memory retrieval/embeddings and user
  memory approval UI.
- Vision-capable screen understanding behind an explicit permission boundary.
- Permissioned-ledger anchoring of audit root hashes through `AuditAnchorAdapter`.
- Provider-specific native JSON/tool calling and local Ollama/llama.cpp adapter.
- Full account/login screens and a remote Aura backend/client split.

## 3. Module map

```text
Backend/
  config.py                         central Settings / dotenv compatibility
  application.py                    dependency-injected composition root
  Agent/
    agent.py                        bounded user-facing orchestration
    planner.py                      structured provider planning + safe fallback
    schemas.py                      strict untrusted-output validation
    context.py                      bounded user-scoped context
    tool_registry.py                tool metadata and parameter validation
    executor.py                     policy-gated sequential execution
    legacy.py                       2024 labels -> tool plan adapter
  AI/
    provider.py                     provider contract/capabilities
    provider_registry.py            capability/privacy routing
    providers/                      lazy Groq, Cohere, local adapters
  Auth/
    passwords.py, jwt.py, service.py, models.py
  Payments/
    models.py, policy.py, verification.py, razorpay_service.py
  Persistence/
    database.py, memory.py, legacy_chatlog.py
  Security/
    privacy.py, consent.py, policy.py, audit.py
    ConfidentialExecution/provider.py
  Tools/builtins.py                 deterministic capability adapters
```

`Automation.py`, `Chatbot.py`, `Model.py`, `RealtimeSearchEngine.py`,
`ImageGeneration.py`, `SpeechToText.py` and `TextToSpeech.py` remain public
compatibility modules but now defer optional SDK imports and delegate modern
routing to the new boundaries.

## 4. Database schema

SQLite migrations are initialized by `Persistence.Database` and the auth/payment
services add their domain tables. Production can replace repositories with
PostgreSQL adapters.

- `schema_migrations(version, applied_at)`
- `users(user_id, email, password_hash, role, permissions, failed_attempts,
  locked_until, created_at, updated_at)`
- `auth_sessions(session_id, user_id, created_at, expires_at, revoked_at)`
- `refresh_tokens(token_id, session_id, token_hash, family_id, created_at,
  expires_at, used_at, revoked_at)`
- `password_reset_tokens(token_hash, user_id, created_at, expires_at, used_at)`
- `conversations(conversation_id, user_id, created_at, updated_at, title)`
- `memory_items(memory_id, user_id, conversation_id, kind,
  content_ciphertext, created_at, approved)`
- `tool_executions(execution_id, user_id, tool_name, risk_level, status,
  started_at, completed_at, duration_ms, error_code)`
- `transactions(transaction_id, user_id, razorpay_order_id,
  razorpay_payment_id, payment_link_id, amount_minor, currency, description,
  status, approval_reference, created_at, updated_at)`
- `consent_records(consent_id, user_id, action, parameters_digest, risk_level,
  created_at, expires_at, status, approved_at)`
- `audit_events(sequence, event_id, previous_hash, timestamp, user_ref, action,
  resource_ref, outcome, metadata_digest, current_hash)`
- `processed_webhooks(event_id, received_at)`

The ledger and transaction records contain identifiers and digests only. They do
not contain passwords, PINs, CVVs, OTPs, raw chat or private documents.

## 5. Environment variables

Copy `.env.example` to `AURA AI/.env` for local development. The template has
names only; do not commit the real file.

- Identity/UI: `AURA_USERNAME`, `AURA_ASSISTANT_NAME`,
  `AURA_INPUT_LANGUAGE`, `AURA_ASSISTANT_VOICE`.
- Provider: `LLM_PROVIDER`, `LLM_MODEL`, `REASONING_PROVIDER`,
  `VISION_PROVIDER`, `GROQ_API_KEY`, `COHERE_API_KEY`, `STABILITY_API_KEY`.
- Security/storage: `JWT_SECRET` (development), `JWT_PRIVATE_KEY`,
  `JWT_PUBLIC_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE`,
  `AURA_DATA_ENCRYPTION_KEY` (URL-safe base64 encoding of exactly 32 bytes),
  `AURA_DATA_DIR`, `AURA_RUNTIME_DIR`, `AURA_DATABASE_PATH`,
  `AURA_ALLOWED_FILE_ROOTS`, `AURA_PRIVACY_MODE`.
- Limits: `AURA_MAX_TOOL_CALLS`, `AURA_MAX_RETRIES`,
  `AURA_MAX_PLANNING_ITERATIONS`, `AURA_TOOL_TIMEOUT_SECONDS`.
- Payments: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
  `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_MODE=test`,
  `RAZORPAY_LIVE_ACKNOWLEDGEMENT=I_UNDERSTAND_LIVE_PAYMENTS`,
  `PAYMENT_LOCK=true`, `PAYMENT_CONFIRMATION_SECONDS`.

`Settings.safe_summary()` is intended for diagnostics and excludes secrets. Do
not print a `Settings` object with its `repr` in an application log.

## 6. Razorpay TEST-mode setup

1. Install dependencies from `AURA AI/Requirements.txt`.
2. Create Razorpay test credentials in the Razorpay dashboard.
3. Put only test `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and the webhook
   secret in an untracked `.env`.
4. Keep `RAZORPAY_MODE=test`, `PAYMENT_LOCK=true`.
5. Create a `ConsentRecord` through the agent. The approval card binds the tool,
   amount in minor INR units, currency and description. The payment tool cannot
   execute without an authenticated user, `payments.create`, unlocked policy and
   exact fresh consent.
6. Use Razorpay's hosted checkout/payment link. Aura never requests UPI PIN,
   CVV, OTP, card PIN or banking password.
7. Verify `order_id|payment_id` HMAC signatures and webhook HMACs. The
   `WebhookReplayGuard` rejects a repeated event id.
8. Test failure, pending, duplicate and webhook replay paths before enabling any
   live configuration.
9. Live mode requires deliberate configuration acknowledgement and remains
   locked otherwise. Never infer LIVE from production-looking credentials.

The production payment endpoint must run on a backend, not expose the Razorpay
secret to the PyQt client. `PaymentService` stores only minimum transaction
metadata and integer minor units.

## 7. Authentication and authorization

`AuthService` stores a password hash, never a password. Argon2id is selected when
available; PBKDF2-SHA256 is a dependency-free fallback for controlled installs.
Failed attempts cause progressive lockout. Access tokens include and validate
issuer, audience, subject, session id, unique JWT id, issued-at, expiry and token
type. Refresh values are opaque, hashed, rotated and single-use; replay revokes
the family and session.

Roles start at `USER` and `ADMIN`. A valid login does not grant a tool. The
policy gate separately checks permission, risk, payment lock and consent.

## 8. Agent/tool architecture

`Planner` requests a JSON `ActionPlan` from a capability-compatible provider.
`ActionPlan.from_mapping` rejects unknown fields, invalid types, unknown step
dependencies and malformed tool names. `ToolSpec.validate_parameters` rejects
unknown/missing parameters and type/length/enum errors. `Executor` runs one
validated step at a time, never runs arbitrary code or shell text, and enforces
call/retry/timeout limits. Observation references such as
`$step_1.selected_path` are resolved only from deterministic tool results.

A multi-step request such as “find my latest resume and open it” becomes file
search followed by a selected-path open. File search executes with a user
permission; opening the private file requests an exact, expiring approval.
Ambiguous or unresolvable targets fail safely.

## 9. Confidential execution

The honest local status is:

```text
Confidential Computing
Mode: Local Development
Attestation: Unavailable
Secret Protection: Development
```

`LocalDevelopmentProvider.release_secret()` always raises. The future production
flow is:

```text
Windows Aura Client --TLS--> Confidential Aura Backend
  -> TDX/SEV-SNP/cloud-VM evidence
  -> independent verifier checks evidence + measurement
  -> attestation-gated secret manager releases a named secret
  -> sensitive operation -> Razorpay
```

The verifier must bind workload identity and measurement; a client claim is not
attestation. GUI, STT/TTS and ordinary low-risk controls stay outside the TEE.

## 10. Tamper-Evident Audit Ledger

Each security event hashes `event_id | previous_hash | timestamp | pseudonymous
user reference | action | resource reference | outcome | metadata digest`.
`AuditLedger.verify_chain()` returns `EMPTY`, `VERIFIED` or `BROKEN`. Updating an
old record breaks either its current hash or the next record's `previous_hash`.
Only safe metadata digests are stored. This is a local append-only integrity
control. The `AuditAnchorAdapter` is the future extension point for anchoring a
root hash to an enterprise/permissioned ledger; no public cryptocurrency or
blockchain is introduced.

## 11. Tests and run instructions

Dependency-light suite:

```bash
PYTHONPATH="AURA AI" python -m unittest discover -s tests -v
```

Optional installed-dependency suite:

```bash
python -m pip install -r "AURA AI/Requirements.txt"
PYTHONPATH="AURA AI" pytest -q
```

Desktop:

```bash
cd "AURA AI"
python main.py
```

Console smoke mode:

```bash
cd "AURA AI"
python main.py --console
```

The tests cover password hashing/login, invalid login, JWT expiry and issuer,
refresh rotation/replay, cross-action consent binding, generic approval refusal,
privacy redaction, audit tampering, unknown tools/malformed plans, loop and
consent limits, payment parsing/lock/signatures/replay and local TEE fail-closed
behavior. Regression tests import and translate the original capability modules.

## 12. Known limitations and production requirements

- Selenium Web Speech remains browser/driver-dependent and is not a robust
  production microphone service. A native Windows STT adapter and interruption
  handling are future work.
- The current PyQt5 shell uses a local development context and placeholder data
  cards for Activity/Payments/Security detail pages. The backend controls are
  real; full authenticated account screens and remote API wiring are not yet
  complete.
- Cloud provider response formats and native structured/tool calling differ by
  SDK version. Adapters fail safely; install and pin the configured SDK.
- `open_application` still delegates to the legacy AppOpener capability. Review
  its application allowlist before broad deployment.
- Terminal execution is a small no-shell allowlist, not universal computer
  control. Long-running services and arbitrary PowerShell are intentionally not
  supported.
- AES-GCM payload encryption requires `cryptography` and a protected key. The
  local fail-closed behavior is safer than silently storing private chat in clear.
- The dependency-free JWT signer is HS256. Production must use an audited
  asymmetric signing/verification deployment, TLS, secure cookies or headers,
  shared revocation storage and operational key rotation.
- Razorpay live operation, webhook endpoint hosting, reconciliation, refund
  controls and incident response require backend infrastructure and business
  approval.
- Real TEE attestation, secret release and optional audit anchoring are not
  simulated and are therefore classified Infrastructure Required/Future
  Extension rather than complete features.
