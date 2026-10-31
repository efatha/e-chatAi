import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents.api_agent import ApiAgent
from agents import router


class ApiAgentTests(unittest.TestCase):
    def test_grok_uses_bearer_auth_and_complete_conversation(self):
        key = "xai-test-token"
        response = SimpleNamespace(
            ok=True,
            json=lambda: {
                "choices": [{"message": {"content": "Answer received."}}],
            },
        )
        history = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Current question"},
        ]
        with (
            patch.dict(os.environ, {"XAI_API_KEY": key}, clear=True),
            patch("agents.api_agent.requests.post", return_value=response) as post,
        ):
            result = ApiAgent().retrieve("Current question", history)

        self.assertEqual(result["response"], "Answer received.")
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            f"Bearer {key}",
        )
        self.assertEqual(
            post.call_args.kwargs["json"]["messages"][1:],
            [
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
                {"role": "user", "content": "Current question"},
            ],
        )

    def test_gemini_receives_assistant_turns_as_model_messages(self):
        response = SimpleNamespace(
            ok=True,
            json=lambda: {
                "candidates": [{
                    "content": {"parts": [{"text": "Answer received."}]},
                }],
            },
        )
        history = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Current question"},
        ]
        with (
            patch.dict(
                os.environ,
                {"API_BASE_URL": "https://provider.example/generate"},
                clear=True,
            ),
            patch("agents.api_agent.requests.post", return_value=response) as post,
        ):
            result = ApiAgent().retrieve("Current question", history)

        self.assertEqual(result["response"], "Answer received.")
        self.assertEqual(
            post.call_args.kwargs["json"]["contents"],
            [
                {"role": "user", "parts": [{"text": "First question"}]},
                {"role": "model", "parts": [{"text": "First answer"}]},
                {"role": "user", "parts": [{"text": "Current question"}]},
            ],
        )

    def test_router_forwards_full_conversation_to_online_provider(self):
        conversation = [
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
        ]
        received = []

        def retrieve(message, history, file):
            received.append((message, history, file))
            return {
                "response": "Online answer",
                "source": "api",
                "provider": "grok",
            }

        api = SimpleNamespace(
            retrieve=retrieve,
        )
        books = SimpleNamespace(
            answer=lambda *_args: None,
            excerpts=lambda *_args: [],
        )
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_api_agent", api),
            patch.object(router, "_book_agent", books),
            patch.object(router, "wikipedia_summary", return_value=None),
            patch.object(router, "ollama_answer", return_value=None),
            patch.object(router, "detect_lookup", return_value=None),
            patch.object(router, "lookup_answer", return_value=None),
            patch.object(router, "search_result_text", return_value=None),
        ):
            result = router.answer_question(
                "Explain quantum entanglement",
                history=["Earlier question"],
                conversation=conversation,
            )

        self.assertEqual(result["response"], "Online answer")
        self.assertEqual(result["provider"], "grok")
        self.assertEqual(received[0][1], conversation)


if __name__ == "__main__":
    unittest.main()
