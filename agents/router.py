"""Chooses the independent agent, then the API agent when that API is active."""

from agents.api_agent import ApiAgent
from agents.independent_agent import IndependentAgent

_api_agent = None
_independent_agent = None


def configure(trained_knowledge, word_meanings):
    global _api_agent, _independent_agent
    _independent_agent = IndependentAgent(trained_knowledge, word_meanings)
    _api_agent = ApiAgent()


def api_agent():
    return _api_agent or ApiAgent()


def answer_question(message, username=None, history=None, file=None):
    """
    Confident local answers stay on this machine.
    Anything else is retrieved from the API when Gemini or Grok responds.
    If the API is not active, the independent agent answers on its own.
    """
    independent = _independent_agent
    api = api_agent()
    history = history or []
    has_file = bool(file and file.get("data"))
    text = (message or "").strip()

    if text and not has_file and independent is not None:
        local = independent.confident_answer(text, username, history)
        if local:
            return {"response": local, "source": "independent", "provider": "local"}

    prompt = text or "Describe this image."
    api_result = api.retrieve(prompt, history, file if has_file else None)
    if api_result:
        return api_result

    if has_file and not text:
        fallback = (
            "I can read images when the API is active. "
            "Right now I'm running on local knowledge only."
        )
        if username:
            fallback = f"{username}, {fallback}"
        return {"response": fallback, "source": "independent", "provider": "local"}

    fallback = "I don't know yet. I'm still learning!"
    if independent is not None:
        fallback = independent.fallback(text, username, history)
    return {"response": fallback, "source": "independent", "provider": "local"}
