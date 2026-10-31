"""Chooses a local answer, then dictionary/Wikipedia/Ollama, then an external API."""

import re

from agents.api_agent import ApiAgent
from agents.independent_agent import IndependentAgent, uncertain_subject
from agents.book_agent import BookAgent, looks_like_reasoning
from agents.knowledge_agent import detect_lookup, lookup_answer, ollama_answer
from agents.knowledge_agent import word_reference
from agents.knowledge_agent import looks_like_open_question, search_result_text
from agents.knowledge_agent import wikipedia_summary
from agents.reasoning_patterns import concept_terms, pattern_answer

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


_AFFIRM = re.compile(
    r"^(?:yes|yeah|yep|sure|absolutely|ok|okay|of course)(?:\s+please)?[.!]*$",
    re.IGNORECASE,
)
_DECLINE = re.compile(
    r"^(?:no|nope|not\s+now|no\s+thanks|no\s+thank\s+you)[.!]*$",
    re.IGNORECASE,
)
_REMEMBER = re.compile(
    r"^(?:please\s+)?(?:remember(?:\s+that)?|keep\s+in\s+mind(?:\s+that)?|"
    r"don['’]?t\s+forget(?:\s+that)?)\s+(.+)$",
    re.IGNORECASE,
)
_RESEARCH = re.compile(
    r"^(?:please\s+)?(?:research|investigate|look\s+into|find\s+information\s+"
    r"(?:about|on))\s+(.+?)[?.!]*$",
    re.IGNORECASE,
)
_PERSONAL_FACT = re.compile(
    r"^(?:(?:yes|yeah|yep|sure|absolutely|okay|ok)[,;:\s-]+)?"
    r"my\s+(.{1,60}?)\s+is\s+(.{1,200}?)[.!]*$",
    re.IGNORECASE,
)
_PERSONAL_QUESTION = re.compile(
    r"^(who|what|how|where|when|why)(?:'s|\s+is)\s+my\s+(.{1,60}?)[?!.]*$",
    re.IGNORECASE,
)


def _previous_message(history, current):
    messages = [str(item).strip() for item in (history or []) if str(item).strip()]
    if messages and messages[-1].casefold() == current.casefold():
        messages.pop()
    return messages[-1] if messages else ""


def _pending_personal_question(text, history):
    if not (_AFFIRM.match(text) or _DECLINE.match(text)):
        return None
    previous = _previous_message(history, text)
    return _PERSONAL_QUESTION.match(previous)


def _pending_research_subject(text, history):
    if not _AFFIRM.match(text):
        return None
    previous = _previous_message(history, text)
    personal_fact = _PERSONAL_FACT.match(previous)
    if not personal_fact:
        return None
    return personal_fact.group(1).strip(), personal_fact.group(2).strip()


def _accepted_definition(text, history, independent):
    """After the unsure offer, yes/sure/yeah loads the dictionary and Wikipedia."""
    if independent is None or not _AFFIRM.match((text or "").strip()):
        return None
    earlier = [str(item).strip() for item in history[:-1] if str(item).strip()]
    if not earlier:
        return None
    word = uncertain_subject(
        earlier[-1],
        independent.trained_knowledge,
        independent.word_meanings,
    )
    if not word:
        return None
    found = word_reference(word)
    if not found:
        return None
    return found


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
    research_match = _RESEARCH.match(text) if text and not has_file else None

    if text and not has_file:
        pending_personal = _pending_personal_question(text, history)
        if pending_personal:
            subject = pending_personal.group(2).strip()
            if _AFFIRM.match(text):
                return {
                    "response": _with_name(
                        f"Okay — tell me about your {subject}. "
                        f"You can say, “My {subject} is …,” and I’ll remember it.",
                        username,
                    ),
                    "source": "conversation",
                    "provider": "local",
                }
            return {
                "response": _with_name(
                    f"That’s okay — I won’t guess. We can leave your {subject} "
                    "unknown until you choose to share it.",
                    username,
                ),
                "source": "conversation",
                "provider": "local",
            }

        pending_research = _pending_research_subject(text, history)
        if pending_research:
            category, subject = pending_research
            if "music" in category.lower() and subject.upper() == "RNB":
                search_term = "R&B music"
            else:
                search_term = f"{subject} music" if "music" in category.lower() else subject
            summary = wikipedia_summary(search_term, search_term)
            if summary:
                return {
                    "response": _with_name(
                        f"Here’s what I found about {subject}:\n\n{summary}",
                        username,
                    ),
                    "source": "research",
                    "provider": "wikipedia",
                }
            local_research = ollama_answer(
                f"Research {search_term} and give a clear, factual overview."
            )
            if local_research:
                local_research["response"] = _with_name(
                    local_research["response"],
                    username,
                )
                local_research["source"] = "research"
                return local_research
            return {
                "response": _with_name(
                    f"I understood your yes as a request to research {subject}. "
                    "I couldn’t find a reliable source right now, but I can try again "
                    "when Wikipedia or Ollama is available.",
                    username,
                ),
                "source": "research",
                "provider": "local",
            }

        accepted = _accepted_definition(text, history, independent)
        if accepted:
            return {
                "response": _with_name(accepted, username),
                "source": "knowledge",
                "provider": "dictionary+wikipedia",
            }
        if _AFFIRM.match(text):
            return {
                "response": _with_name(
                    "Understood — yes. I’ll continue with that in mind.",
                    username,
                ),
                "source": "intent",
                "provider": "local",
            }
        remembered = _REMEMBER.match(text)
        if remembered:
            detail = remembered.group(1).strip(" .")
            return {
                "response": _with_name(
                    f"I’ll keep this in memory: {detail}. You can ask me about it later.",
                    username,
                ),
                "source": "memory",
                "provider": "local-sqlite",
            }
        personal_fact = _PERSONAL_FACT.match(text)
        if personal_fact:
            subject = personal_fact.group(1).strip()
            value = personal_fact.group(2).strip()
            return {
                "response": _with_name(
                    f"Great, I’ve got it — your {subject} is {value}. "
                    f"I’ll remember that. Would you like me to research {value} "
                    "or help you explore it further?",
                    username,
                ),
                "source": "memory",
                "provider": "local-sqlite",
            }
        personal_question = _PERSONAL_QUESTION.match(text)
        if personal_question:
            question_word = personal_question.group(1).lower()
            subject = personal_question.group(2).strip()
            return {
                "response": _with_name(
                    f"I’m not sure {question_word} your {subject} is yet, "
                    "and I don’t want to guess. "
                    "Would you like to tell me so I can remember?",
                    username,
                ),
                "source": "conversation",
                "provider": "local",
            }
        if research_match:
            subject = research_match.group(1).strip()
            summary = wikipedia_summary(subject, text)
            if summary:
                return {
                    "response": _with_name(summary, username),
                    "source": "research",
                    "provider": "wikipedia",
                }

    if text and not has_file and looks_like_reasoning(text):
        from_books = book_agent().answer(text)
        if from_books:
            from_books["response"] = _with_name(from_books["response"], username)
            return from_books

    if text and not has_file and independent is not None:
        local = independent.confident_answer(text, username, history)
        if local:
            return {"response": local, "source": "independent", "provider": "local"}

    if text and not has_file:
        terms = concept_terms(text)
        if terms is not None:
            notes = {term: wikipedia_summary(term, text) for term in terms[:2]}
            excerpts = book_agent().excerpts(text) if terms or looks_like_reasoning(text) else []
            patterned = pattern_answer(text, notes, excerpts)
            if patterned:
                patterned["response"] = _with_name(patterned["response"], username)
                return patterned

    if text and not has_file:
        found = detect_lookup(text)
        if found and found.get("kind") == "dictionary":
            meanings = independent.word_meanings if independent is not None else {}
            knowledge = lookup_answer(text, meanings)
            if knowledge:
                knowledge["response"] = _with_name(knowledge["response"], username)
                return knowledge

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

        from_books = book_agent().answer(text)
        if from_books and "local books yet" not in from_books["response"].lower():
            passages = book_agent().excerpts(text)
            if passages:
                from_books["response"] = _with_name(from_books["response"], username)
                return from_books

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
        "I’m not sure about that yet, and I don’t want to make up an answer. "
        "Could you tell me a little more, or ask me to research it?"
    )
    if independent is not None:
        meaning = independent.fallback(text, username, history)
        if meaning and "still learning" not in meaning.lower():
            fallback = meaning
    if text and looks_like_open_question(text):
        found = search_result_text(text)
        if found:
            return {"response": _with_name(found, username), "source": "search", "provider": "web"}
    if research_match:
        subject = research_match.group(1).strip()
        fallback = (
            f"I understand this is a research request about {subject}. "
            "I could not find enough reliable material in local memory or books yet. "
            "Add a relevant PDF or start Ollama, then ask me to research it again."
        )
    return {"response": fallback, "source": "independent", "provider": "local"}


def _with_name(text, username):
    if username and text:
        return f"{username}, {text}"
    return text
