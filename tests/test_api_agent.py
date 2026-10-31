import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents.api_agent import ApiAgent


class ApiAgentTests(unittest.TestCase):
    def test_grok_uses_bearer_auth_and_complete_conversation(self):
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
            patch.dict(os.environ, {"XAI_API_KEY": "xai-test-token"}, clear=True),
            patch("agents.api_agent.requests.post", return_value=response) as post,
        ):
            result = ApiAgent().retrieve("Current question", history)

        self.assertEqual(result["response"], "Answer received.")
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "******",
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


if __name__ == "__main__":
    unittest.main()
