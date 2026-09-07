import asyncio
import tempfile
import unittest
from pathlib import Path

from Backend.Agent.executor import ExecutionLimits, ExecutionStatus, Executor
from Backend.Agent.planner import Planner
from Backend.Agent.schemas import ActionPlan, PlanStep, ToolCall, ValidationError
from Backend.Agent.tool_registry import ToolRegistry, ToolSpec, ToolValidationError
from Backend.Auth.models import AuthContext
from Backend.Persistence.database import EncryptedPayloadCodec, EncryptionUnavailable
from Backend.Security.consent import ConsentManager, RiskLevel
from Backend.Security.policy import PolicyGateway


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "aura.db")
        self.registry = ToolRegistry()
        self.calls = []
        self.registry.register(ToolSpec("answer_question", "answer", {"type": "object", "properties": {"query": {"type": "string", "maxLength": 100}}, "required": ["query"]}, RiskLevel.LOW, None, False, 5, {"type": "object"}, lambda query: self.calls.append(query) or {"answer": query}))
        self.registry.register(ToolSpec("delete_file", "delete", {"type": "object", "properties": {"path": {"type": "string", "maxLength": 200}}, "required": ["path"]}, RiskLevel.DESTRUCTIVE, "files.write", True, 5, {"type": "object"}, lambda path: True))
        self.consent = ConsentManager(self.db)
        self.policy = PolicyGateway(self.consent, payment_lock=False)
        self.executor = Executor(self.registry, self.policy, self.consent, limits=ExecutionLimits(3, 0, 2, 5))

    def tearDown(self):
        self.temp.cleanup()

    def test_malformed_tool_output_and_unknown_tool_rejected(self):
        with self.assertRaises(ValidationError):
            ActionPlan.from_mapping({"goal": "x", "steps": [{"tool": "answer_question", "parameters": {}, "bad": 1}]})
        with self.assertRaises(ToolValidationError):
            self.registry.validate_call("not_registered", {})
        with self.assertRaises(ToolValidationError):
            self.registry.validate_call("answer_question", {"query": "x", "unexpected": True})

    def test_low_risk_tool_executes_without_consent(self):
        outcome = asyncio.run(self.executor.execute(ActionPlan("answer", (PlanStep("one", ToolCall("answer_question", {"query": "hello"}), "answer"),)), auth=AuthContext("u1", permissions=())))
        self.assertEqual(outcome.status, ExecutionStatus.COMPLETE)
        self.assertEqual(self.calls, ["hello"])

    def test_destructive_tool_waits_for_consent(self):
        context = AuthContext("u1", permissions=("files.write",))
        plan = ActionPlan("delete", (PlanStep("one", ToolCall("delete_file", {"path": "x"}), "delete"),))
        outcome = asyncio.run(self.executor.execute(plan, auth=context))
        self.assertEqual(outcome.status, ExecutionStatus.WAITING_APPROVAL)
        self.assertIsNotNone(outcome.consent_id)
        record = self.consent.get(outcome.consent_id)
        self.consent.approve(outcome.consent_id, "u1", "delete_file", {"path": "x"})
        complete = asyncio.run(self.executor.execute(plan, auth=context, consent_id=outcome.consent_id))
        self.assertEqual(complete.status, ExecutionStatus.COMPLETE)

    def test_plaintext_sensitive_storage_fails_closed(self):
        codec = EncryptedPayloadCodec(None)
        with self.assertRaises(EncryptionUnavailable):
            codec.encrypt("private conversation", associated_data="u1")
        dev = EncryptedPayloadCodec(None, allow_plaintext_dev=True)
        self.assertEqual(dev.decrypt(dev.encrypt("dev", associated_data="u1"), associated_data="u1"), "dev")


if __name__ == "__main__":
    unittest.main()
