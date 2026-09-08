import sys
import unittest


class RegressionTests(unittest.TestCase):
    def test_legacy_capability_modules_import_without_optional_keys(self):
        import Backend.Automation
        import Backend.Chatbot
        import Backend.ImageGeneration
        import Backend.Model
        import Backend.RealtimeSearchEngine
        import Backend.SpeechToText
        import Backend.TextToSpeech

    def test_legacy_command_adapter_preserves_capabilities(self):
        from Backend.Agent.legacy import parse_legacy_labels
        plan = parse_legacy_labels(["open calculator", "google search secure python", "system volume up"])
        names = [step.tool_call.name for step in plan.steps]
        self.assertEqual(names, ["open_application", "google_search", "system_volume"])


if __name__ == "__main__":
    unittest.main()
