import os
import tempfile
import time
import unittest
from pathlib import Path

from Backend.Auth.jwt import JWTService, JWTValidationError
from Backend.Auth.service import AuthService, AuthenticationError
from Backend.Security.audit import AuditIntegrity, AuditLedger
from Backend.Security.consent import ConsentManager, ConsentStatus, RiskLevel, is_explicit_approval
from Backend.Security.privacy import CredentialLeakError, redact_sensitive


class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "aura.db")
        self.jwt = JWTService.from_secret("s" * 48, ttl_seconds=60)
        self.auth = AuthService(self.db, self.jwt)

    def tearDown(self):
        self.temp.cleanup()

    def test_password_hash_login_and_invalid_login(self):
        user_id = self.auth.register("User@example.com", "a-strong-password-123")
        self.assertTrue(user_id)
        with self.assertRaises(AuthenticationError):
            self.auth.login("User@example.com", "wrong-password-123")
        session = self.auth.login("User@example.com", "a-strong-password-123")
        self.assertEqual(self.auth.validate_access(session.access_token).user_id, user_id)

    def test_refresh_rotation_and_replay_revocation(self):
        self.auth.register("user@example.com", "a-strong-password-123")
        session = self.auth.login("user@example.com", "a-strong-password-123")
        rotated = self.auth.refresh(session.refresh_token)
        self.assertNotEqual(rotated.refresh_token, session.refresh_token)
        with self.assertRaises(AuthenticationError):
            self.auth.refresh(session.refresh_token)
        with self.assertRaises(AuthenticationError):
            self.auth.validate_access(rotated.access_token)

    def test_jwt_expiration_and_claim_validation(self):
        token = self.jwt.issue("u", session_id="s", role="USER", now=100)
        with self.assertRaises(JWTValidationError):
            self.jwt.decode_and_validate(token, now=161)
        token = self.jwt.issue("u", session_id="s", role="USER", now=100)
        with self.assertRaises(JWTValidationError):
            # issuer/audience are cryptographically bound to the service config.
            JWTService.from_secret("x" * 48, issuer="other").decode_and_validate(token, now=101)

    def test_credential_redaction_and_request_rejection_signal(self):
        result = redact_sensitive("Remember my UPI PIN 1234 and use it later")
        self.assertTrue(result.redacted)
        self.assertNotIn("1234", result.text)
        self.assertIn("REDACTED", result.text)

    def test_consent_is_exact_and_expiring(self):
        manager = ConsentManager(self.db, default_timeout_seconds=10)
        record = manager.create("u1", "create_payment_link", {"amount_minor": 250000}, RiskLevel.FINANCIAL, now=100)
        with self.assertRaises(ValueError):
            manager.approve(record.consent_id, "u1", "create_payment_link", {"amount_minor": 250001}, now=101)
        approved = manager.approve(record.consent_id, "u1", "create_payment_link", {"amount_minor": 250000}, now=101)
        self.assertEqual(approved.status, ConsentStatus.APPROVED)
        self.assertTrue(manager.validate(record.consent_id, "u1", "create_payment_link", {"amount_minor": 250000}, now=102))
        manager.consume(record.consent_id, "u1", "create_payment_link", {"amount_minor": 250000}, now=102)
        self.assertFalse(manager.validate(record.consent_id, "u1", "create_payment_link", {"amount_minor": 250000}, now=102))

    def test_generic_acknowledgements_are_not_approval(self):
        for phrase in ("okay", "fine", "continue", "maybe", "later"):
            self.assertFalse(is_explicit_approval(phrase, active_action="create_payment_link"))
        self.assertTrue(is_explicit_approval("yes", active_action="create_payment_link"))
        self.assertFalse(is_explicit_approval("yes", active_action=None))

    def test_audit_chain_detects_tampering(self):
        ledger = AuditLedger(self.db, installation_salt=b"test-salt")
        ledger.append(user_id="u1", action="login", outcome="SUCCESS", metadata={"ip": "127.0.0.1"})
        ledger.append(user_id="u1", action="consent", resource_ref="create_payment_link", outcome="APPROVED", metadata={"amount": 2500})
        self.assertEqual(ledger.verify_chain(), AuditIntegrity.VERIFIED)
        with ledger._connect() as db:  # tamper simulation, not production API
            db.execute("UPDATE audit_events SET outcome='CHANGED' WHERE sequence=1")
        self.assertEqual(ledger.verify_chain(), AuditIntegrity.BROKEN)


if __name__ == "__main__":
    unittest.main()
