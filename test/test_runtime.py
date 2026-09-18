import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime import DesktopSession, RuntimeErrorSafe, StalePage, action_space, fingerprint, high_impact, origin, receipt, validate_choice
from server import configured_origins


class RuntimeContracts(unittest.TestCase):
    def test_origin_rejects_userinfo_and_non_http(self):
        self.assertEqual(origin("https://example.com/path"), "https://example.com")
        for value in ("file:///tmp/x", "https://user@example.com", "not-a-url"):
            with self.assertRaises(RuntimeErrorSafe):
                origin(value)

    def test_action_space_only_exposes_observed_targets(self):
        elements, targets, controls = action_space([
            {"id": "a1", "node": 1, "kind": "click", "label": "Search", "role": "button"},
            {"id": "a2", "node": 2, "kind": "fill", "label": "Where to", "role": "textbox"},
            {"id": "a3", "node": 3, "kind": "select", "label": "Economy", "role": "select", "value": "economy"},
        ])
        self.assertEqual([item["index"] for item in elements], ["1", "2", "3"])
        self.assertEqual(set(targets), {"CLICK", "TYPE_TEXT", "SELECT"})
        self.assertEqual(targets["CLICK"]["1"]["id"], "a1")
        self.assertEqual(targets["SELECT"]["3:1"]["id"], "a3")
        self.assertIn("WAIT", controls)

    def test_choice_requires_a_complete_probability_distribution(self):
        ids = {"CLICK": "click", "DONE": "done"}
        accepted = {"choice": "CLICK", "confidence": 0.8, "probabilities": {"CLICK": 0.8, "DONE": 0.2}}
        self.assertEqual(validate_choice(accepted, ids)["choice"], "CLICK")
        rejected = {"choice": "CLICK", "confidence": 0.8, "probabilities": {"CLICK": 1.0}}
        with self.assertRaises(RuntimeErrorSafe):
            validate_choice(rejected, ids)

    def test_fingerprint_changes_when_the_observed_page_changes(self):
        one = {"url": "https://example.com", "title": "One", "text": "result", "actions": [], "marker": "a"}
        two = {**one, "text": "different", "marker": "b"}
        self.assertNotEqual(fingerprint(one), fingerprint(two))

    def test_high_impact_actions_require_review(self):
        self.assertTrue(high_impact({"label": "Confirm purchase"}))
        self.assertTrue(high_impact({"label": "Delete account"}))
        self.assertFalse(high_impact({"label": "Search flights"}))

    def test_receipt_preserves_executed_action_when_observation_was_uncertain(self):
        class Session:
            session_id = "session-1"
            initial_origin = "https://example.com"
            page = {"url": "https://example.com", "title": "Example", "fingerprint": "before"}
            history = [{"step": 1, "action": "Search", "kind": "click", "url": "https://example.com", "page_changed": None, "model": "typesafe"}]
            created_at = 0

        output = receipt(Session(), "uncertain", detail="Post-action observation failed.")
        self.assertEqual(output["status"], "uncertain")
        self.assertEqual(output["actions"][0]["action"], "Search")
        self.assertIsNone(output["actions"][0]["pageChanged"])

    def test_logged_in_requires_explicit_bare_origins_before_contacting_the_companion(self):
        self.assertEqual(configured_origins(["https://example.com"]), ["https://example.com"])
        with self.assertRaises(RuntimeErrorSafe):
            configured_origins(["https://example.com/path"])
        with self.assertRaises(RuntimeErrorSafe):
            DesktopSession.start("local-1", "https://outside.example", {
                "desktopCompanionToken": "x" * 32,
                "loggedInOrigins": ["https://example.com"],
            })

    def test_stale_page_is_a_safe_non_execution_failure(self):
        self.assertTrue(issubclass(StalePage, RuntimeErrorSafe))


if __name__ == "__main__":
    unittest.main()
