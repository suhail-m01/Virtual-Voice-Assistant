import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from Backend.Payments.models import Money, parse_inr_amount
from Backend.Payments.policy import PaymentLockedError, PaymentPolicy
from Backend.Payments.verification import WebhookReplayGuard, verify_payment_signature, verify_webhook_signature
from Backend.Security.ConfidentialExecution.provider import AttestationStatus, LocalDevelopmentProvider, SecretReleaseError


class PaymentAndTEETests(unittest.TestCase):
    def test_integer_money_and_validation(self):
        self.assertEqual(parse_inr_amount("2,500").minor, 250000)
        self.assertEqual(Money.from_major("750").minor, 75000)
        with self.assertRaises(ValueError):
            parse_inr_amount("free")
        with self.assertRaises(ValueError):
            Money(0)

    def test_payment_lock_and_mode(self):
        policy = PaymentPolicy(locked=True, mode="test")
        with self.assertRaises(PaymentLockedError):
            policy.assert_can_initiate()
        policy.set_lock(False)
        policy.assert_can_initiate()
        live = PaymentPolicy(locked=False, mode="live", live_acknowledged=False)
        with self.assertRaises(PaymentLockedError):
            live.assert_can_initiate()

    def test_razorpay_signatures_and_replay_guard(self):
        secret = "webhook-secret"
        sig = hmac.new(secret.encode(), b"order|payment", hashlib.sha256).hexdigest()
        self.assertTrue(verify_payment_signature("order", "payment", sig, secret))
        self.assertFalse(verify_payment_signature("order", "payment", sig, "wrong"))
        body = b'{"event":"payment.captured"}'
        webhook = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(body, webhook, secret))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "a.db")
            guard = WebhookReplayGuard(path)
            self.assertTrue(guard.accept_once("event-1"))
            self.assertFalse(guard.accept_once("event-1"))

    def test_local_provider_never_fakes_attestation_or_releases_secret(self):
        provider = LocalDevelopmentProvider()
        evidence = provider.attest()
        self.assertEqual(evidence.status, AttestationStatus.UNAVAILABLE)
        self.assertFalse(provider.verify_attestation(evidence))
        with self.assertRaises(SecretReleaseError):
            provider.release_secret("RAZORPAY_KEY_SECRET", evidence=evidence)


if __name__ == "__main__":
    unittest.main()
