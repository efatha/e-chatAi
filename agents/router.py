"""Route questions to deterministic reasoning and locally indexed knowledge."""

import re

from agents.independent_agent import IndependentAgent, uncertain_subject
from agents.book_agent import BookAgent
from agents.knowledge_agent import (
    detect_lookup,
    looks_like_open_question,
    search_result_text,
    wikipedia_definition,
    wikipedia_summary,
)
from agents.reasoning_patterns import concept_terms, pattern_answer

_independent_agent = None
_book_agent = None


def configure(trained_knowledge, word_meanings):
    global _independent_agent, _book_agent
    _independent_agent = IndependentAgent(trained_knowledge, word_meanings)
    _book_agent = BookAgent()


def book_agent():
    global _book_agent
    if _book_agent is None:
        _book_agent = BookAgent()
    return _book_agent


_AFFIRM = re.compile(
    r"^(?:yes|yeah|yep|sure|absolutely|ok|okay|of course|good|fine|amazing)"
    r"(?:\s+please)?[.!]*$",
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
_GREETING = re.compile(
    r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening))(?:\s+there)?[!.,]*$",
    re.IGNORECASE,
)
_NAME_QUESTION = re.compile(
    r"^(?:what(?:'s|\s+is)\s+my\s+name|who(?:'s|\s+is)\s+my\s+name|who\s+am\s+i)[?.!]*$",
    re.IGNORECASE,
)
_PLANS = re.compile(
    r"^(?:what(?:'s|\s+is|\s+have|\s+are)?\s+)?"
    r"(?:you\s+)?(?:have\s+)?"
    r"(?:got\s+)?"
    r"(?:planned|planning|doing)\b.*$",
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


def _last_assistant(conversation):
    for item in reversed(conversation or []):
        if isinstance(item, dict) and item.get("role") == "assistant":
            return str(item.get("content") or "").strip()
    return ""


_NAME_CONFIRM = re.compile(r"your name is\s+(.+?),\s+right\?", re.IGNORECASE)
_REMEMBER_OFFER = re.compile(r"would you like to tell me so i can remember", re.IGNORECASE)
_TELL_ME = re.compile(r"tell me about your\s+(.+?)\.", re.IGNORECASE)


def _accepted_definition(text, history, independent):
    """Resolve an accepted definition offer from the curated local glossary only."""
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
    meaning = independent.word_meanings.get(word)
    if not meaning:
        return None
    return f"{word}: {meaning}"


def answer_question(message, username=None, history=None, file=None, conversation=None):
    """Answer only from local rules, curated knowledge, memory, or indexed books."""
    independent = _independent_agent
    history = history or []
    has_file = bool(file and file.get("data"))
    text = (message or "").strip()
    research_match = _RESEARCH.match(text) if text and not has_file else None

    if text and not has_file:
        if _AFFIRM.match(text) or _DECLINE.match(text):
            reply = _yes_no_reply(text, history, conversation, username)
            if reply:
                return reply

        accepted = _accepted_definition(text, history, independent)
        if accepted:
            return {
                "response": _with_name(accepted, username),
                "source": "knowledge",
                "provider": "curated-local",
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
                    f"😄 Great, I’ve got it — your {subject} is {value}. I’ll remember that.",
                    username,
                ),
                "source": "memory",
                "provider": "local-sqlite",
            }
        if _GREETING.match(text):
            greeting = (
                f"👋😄 Hello {username}! How can I help you today?"
                if username
                else "👋😄 Hello! How can I help you today?"
            )
            return {
                "response": greeting,
                "source": "conversation",
                "provider": "local",
            }
        if _NAME_QUESTION.match(text):
            if username:
                reply = f"😊 Your name is {username}, right?"
            else:
                reply = "🤔 I don’t know your name yet. Add it on the access form and I’ll remember you."
            return {
                "response": reply,
                "source": "conversation",
                "provider": "local",
            }
        if _PLANS.match(text):
            return {
                "response": _with_name(
                    "I don’t keep a personal schedule. I’m here for whatever "
                    "you want to work on — a question, a proof, or something "
                    "from the local books.",
                    username,
                ),
                "source": "conversation",
                "provider": "local",
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
    if text and not has_file:
        terms = concept_terms(text)
        if terms and len(terms) == 2:
            notes = {}
            for term in terms:
                note = wikipedia_summary(term, text)
                if note:
                    notes[term] = note
            patterned = pattern_answer(text, notes=notes)
            if patterned and notes:
                patterned["response"] = _with_name(patterned["response"], username)
                patterned["provider"] = "wikipedia+reasoning-pattern"
                return patterned
            patterned = pattern_answer(text)
            if patterned:
                patterned["response"] = _with_name(patterned["response"], username)
                return patterned
            fallback = _with_name(
                "I couldn’t find reliable source information for both sides of that "
                "comparison, so I can’t compare them accurately.",
                username,
            )
            return {"response": fallback, "source": "independent", "provider": "local"}

    if text and not has_file and detect_lookup(text):
        defined = _definition_from_local_or_wikipedia(text, independent, username)
        if defined:
            return defined
        return {
            "response": _with_name(
                "I couldn’t retrieve a Wikipedia definition for that. "
                "I won’t answer a definition from an unrelated book passage.",
                username,
            ),
            "source": "knowledge",
            "provider": "wikipedia",
        }

    if text and not has_file and looks_like_open_question(text):
        reflected = search_result_text(text)
        if reflected:
            return {
                "response": _with_name(reflected, username),
                "source": "knowledge",
                "provider": "wikipedia",
            }

    if text and not has_file:
        from_books = book_agent().answer(text)
        if from_books:
            from_books["response"] = _with_name(from_books["response"], username)
            return from_books

    if text and not has_file:
        patterned = pattern_answer(text)
        if patterned:
            patterned["response"] = _with_name(patterned["response"], username)
            return patterned

    if text and not has_file and independent is not None:
        local = independent.confident_answer(text, username, history)
        if local:
            return {"response": local, "source": "independent", "provider": "local"}

    if has_file and not text:
        fallback = (
            "I can’t interpret this file in offline mode because no local vision "
            "or document reader is configured."
        )
        if username:
            fallback = f"{username}, {fallback}"
        return {"response": fallback, "source": "independent", "provider": "local"}

    if research_match:
        subject = research_match.group(1).strip()
        fallback = (
            f"I couldn’t find enough supporting material about {subject} in the "
            "curated knowledge or indexed books. This build does not use external "
            "services, so it won’t invent or fetch an answer."
        )
    else:
        fallback = (
            "I couldn’t find enough support in the curated local knowledge or "
            "indexed books to answer this reliably. This offline build won’t "
            "invent an answer."
        )
    fallback = _with_name(fallback, username)
    return {"response": fallback, "source": "independent", "provider": "local"}


def _yes_no_reply(text, history, conversation, username):
    """Answer yes or no from the line e-Chat just said."""
    previous_bot = _last_assistant(conversation)
    affirmed = bool(_AFFIRM.match(text))
    name_confirm = _NAME_CONFIRM.search(previous_bot)
    if name_confirm:
        name = name_confirm.group(1).strip()
        if affirmed:
            reply = f"😄 Glad that's you — I'll keep calling you {name}."
        else:
            reply = "🙂 Okay. What should I call you? You can say, “My name is ….”"
        return {"response": reply, "source": "conversation", "provider": "local"}

    offer = _REMEMBER_OFFER.search(previous_bot)
    prompt = _TELL_ME.search(previous_bot)
    pending = _pending_personal_question(text, history)
    subject = None
    if prompt:
        subject = prompt.group(1).strip()
    elif pending:
        subject = pending.group(2).strip()
    elif offer:
        subject = "that"
    if subject:
        if subject == "that":
            reply = (
                "Okay — tell me, and I’ll remember it."
                if affirmed
                else "🙂 That’s okay — I won’t guess until you choose to share it."
            )
        elif affirmed:
            reply = (
                f"Okay — tell me about your {subject}. "
                f"You can say, “My {subject} is …,” and I’ll remember it."
            )
        else:
            reply = (
                f"🙂 That’s okay — I won’t guess. We can leave your {subject} "
                "unknown until you choose to share it."
            )
        return {
            "response": _with_name(reply, username),
            "source": "conversation",
            "provider": "local",
        }
    if affirmed:
        reply = "👍 Understood — yes. I’ll continue with that in mind."
    else:
        reply = "🙂 Okay — I’ll leave that there."
    return {
        "response": _with_name(reply, username),
        "source": "conversation",
        "provider": "local",
    }


def _definition_from_local_or_wikipedia(text, independent, username):
    """Definition questions go straight to Wikipedia."""
    del independent
    found = detect_lookup(text)
    if not found:
        return None
    external = wikipedia_definition(found["term"], text)
    if not external:
        return None
    return {
        "response": _with_name(external, username),
        "source": "knowledge",
        "provider": "wikipedia",
    }


def _with_name(text, username):
    if username and text:
        return f"{username}, {text}"
    return text
