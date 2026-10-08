"""Chooses a local answer, then dictionary/Wikipedia/Ollama, then an external API."""

from agents.api_agent import ApiAgent
from agents.independent_agent import IndependentAgent
from agents.book_agent import BookAgent, looks_like_reasoning
from agents.knowledge_agent import lookup_answer, ollama_answer
from agents.linear_algebra import answer as linear_answer

_api_agent = None
_independent_agent = None
_book_agent = None


def configure(trained_knowledge, word_meanings):
    global _api_agent, _independent_agent, _book_agent
    _independent_agent = IndependentAgent(trained_knowledge, word_meanings)
    _api_agent = ApiAgent()
    _book_agent = BookAgent()


def book_agent():
    global _book_agent
    if _book_agent is None:
        _book_agent = BookAgent()
    return _book_agent


def api_agent():
    return _api_agent or ApiAgent()


def answer_question(message, username=None, history=None, file=None):
    """
    Math, greetings, and trained facts stay local.
    A word or topic lookup uses the dictionary and Wikipedia, and Ollama
    when that local model is running. Flask returns those pieces together.
    Other questions use Ollama if it is active, otherwise Gemini or Grok.
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

    if text and not has_file:
        numeric = linear_answer(text)
        if numeric:
            numeric["response"] = _with_name(numeric["response"], username)
            return numeric

    if text and not has_file and looks_like_reasoning(text):
        from_books = book_agent().answer(text)
        if from_books:
            from_books["response"] = _with_name(from_books["response"], username)
            return from_books

    if text and not has_file:
        meanings = independent.word_meanings if independent is not None else {}
        knowledge = lookup_answer(text, meanings)
        if knowledge:
            knowledge["response"] = _with_name(knowledge["response"], username)
            return knowledge

        local_model = ollama_answer(text)
        if local_model:
            local_model["response"] = _with_name(local_model["response"], username)
            return local_model

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

    fallback = (
        "I don't have a matching page in the local books yet. "
        "Say a bit more about what you want to prove or look up, and I will work from that."
    )
    if independent is not None:
        meaning = independent.fallback(text, username, history)
        if meaning and "still learning" not in meaning.lower():
            fallback = meaning
    return {"response": fallback, "source": "independent", "provider": "local"}


def _with_name(text, username):
    if username and text:
        return f"{username}, {text}"
    return text
