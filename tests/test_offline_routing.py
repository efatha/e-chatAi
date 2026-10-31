import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents import router
from agents.independent_agent import IndependentAgent


class OfflineRoutingTests(unittest.TestCase):
    def test_book_evidence_precedes_generic_local_fallback(self):
        books = SimpleNamespace(
            answer=lambda _question: {
                "response": "Evidence from a local book.",
                "source": "book",
                "provider": "local-books",
            }
        )
        independent = SimpleNamespace(
            confident_answer=lambda *_args: self.fail(
                "Generic fallback must not override retrieved book evidence"
            )
        )
        with (
            patch.object(router, "_book_agent", books),
            patch.object(router, "_independent_agent", independent),
        ):
            result = router.answer_question("Explain this book topic")

        self.assertEqual(result["source"], "book")
        self.assertEqual(result["provider"], "local-books")
        self.assertEqual(result["response"], "Evidence from a local book.")

    def test_unavailable_local_evidence_is_reported_without_online_fallback(self):
        books = SimpleNamespace(answer=lambda _question: None)
        independent = SimpleNamespace(confident_answer=lambda *_args: None)
        with (
            patch.object(router, "_book_agent", books),
            patch.object(router, "_independent_agent", independent),
        ):
            result = router.answer_question("Explain an unsupported obscure topic")

        self.assertEqual(result["source"], "independent")
        self.assertEqual(result["provider"], "local")
        self.assertIn("offline build", result["response"])
        self.assertNotIn("research it", result["response"])

    def test_unknown_definition_does_not_prompt_for_a_follow_up(self):
        agent = IndependentAgent([], {})

        result = agent.confident_answer("Do you know about quibbleton?")

        self.assertIn("offline build", result)
        self.assertNotIn("Would you like", result)


if __name__ == "__main__":
    unittest.main()
