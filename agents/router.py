"""Route questions to deterministic reasoning and locally indexed knowledge."""

import re
from datetime import date

from agents.image_agent import explain_saved_image, image_question, interpret_image
from agents.independent_agent import (
    IndependentAgent,
    arithmetic_reply,
    code_reply,
    uncertain_subject,
)
from agents.book_agent import BookAgent
from agents.knowledge_agent import (
    detect_lookup,
    looks_like_open_question,
    search_result_text,
    commons_image,
    picture_request,
    wikidata_current,
    wikidata_image,
    wikidata_research,
    how_to_reply,
    translate_reply,
    weather_reply,
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


def _remembered_focus(text, focus, conversation):
    """Use the saved subject, or the last weather or fact answer in this chat."""
    found = dict(focus or {})
    if found.get("place") or found.get("person") or found.get("topic"):
        return found
    for item in reversed(conversation or []):
        content = str(item.get("content") or "")
        if "Open-Meteo" in content or "Last reading" in content or "Tomorrow" in content:
            match = re.search(r"([A-Z][A-Za-z .'-]{2,40}) is \d", content)
            if match:
                found["place"] = match.group(1).split(",")[0].strip()
                return found
        if "capital of" in content.lower():
            match = re.search(r"capital of ([A-Z][A-Za-z .'-]+)", content)
            if match:
                found["place"] = match.group(1).strip(" .")
                found["topic"] = found["place"]
                return found
    return found


def _reuse_subject(text, focus):
    """A short follow-up keeps the last city, person, or topic."""
    lowered = re.sub(r"\s+", " ", (text or "").lower()).strip(" ?!.")
    place = (focus or {}).get("place")
    if place and lowered in {
        "and tomorrow", "tomorrow", "what about tomorrow", "tomorrows weather",
        "and tonight", "tonight",
    }:
        when = "tomorrow" if "tomorrow" in lowered else "tonight"
        return f"what is the weather {when} in {place}"
    person = (focus or {}).get("person")
    if person and lowered in {"who is that", "and him", "and her", "and them"}:
        return f"who is {person}"
    topic = (focus or {}).get("topic")
    if topic and lowered in {"tell me more", "more", "and that", "what about it"}:
        return f"what is {topic}"
    return None


def _capital_place(text):
    from agents.knowledge_agent import _CAPITAL, _CAPITAL_BARE, _CAPITAL_CITY, _CAPITAL_OWN
    match = (
        _CAPITAL.match(text or "")
        or _CAPITAL_CITY.match(text or "")
        or _CAPITAL_OWN.match(text or "")
        or _CAPITAL_BARE.match(text or "")
    )
    return match.group(1).strip() if match else ""


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


def answer_question(
    message, username=None, history=None, file=None, conversation=None,
    previous_image="", previous_reply="", focus=None,
):
    """Answer only from local rules, curated knowledge, memory, or indexed books."""
    independent = _independent_agent
    history = history or []
    has_file = bool(file and file.get("data"))
    text = (message or "").strip()
    focus = focus if isinstance(focus, dict) else {}
    continued = _reuse_subject(text, _remembered_focus(text, focus, conversation))
    if continued:
        text = continued
    if has_file:
        seen = interpret_image(file, text)
        if isinstance(seen, dict) and seen.get("response"):
            body = seen["response"]
            return {
                "response": _with_name(body, username),
                "source": "vision",
                "provider": "local-pixels",
                "image_text": seen.get("lines") or "",
                "image_reply": body,
            }
    if text and not has_file and image_question(text) and (previous_image or previous_reply):
        return {
            "response": _with_name(
                explain_saved_image(text, previous_image, previous_reply),
                username,
            ),
            "source": "vision",
            "provider": "local-pixels",
            "image_text": previous_image,
            "image_reply": previous_reply,
        }
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
        translated = translate_reply(text)
        if translated:
            result = {
                "response": translated["text"],
                "source": "knowledge",
                "provider": "translate",
            }
            if translated.get("card"):
                result["translation"] = translated["card"]
            return result
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

    if text and not has_file:
        coded = code_reply(text)
        if coded:
            return {
                "response": _with_name(coded, username),
                "source": "reasoning",
                "provider": "local-rules",
            }

    if text and not has_file:
        solved = arithmetic_reply(text, username)
        if solved:
            return {
                "response": solved,
                "source": "reasoning",
                "provider": "local-rules",
            }

    if text and not has_file:
        known = _local_knowledge(text, independent, username)
        if known:
            return known

    if text and not has_file:
        weather = weather_reply(text)
        if weather:
            result = {
                "response": _with_name(weather["text"], username),
                "source": "knowledge",
                "provider": "open-meteo",
            }
            if weather.get("card"):
                result["weather"] = weather["card"]
                result["focus"] = {
                    "place": weather["card"].get("query") or weather["card"].get("place"),
                    "kind": "weather",
                }
            return result

    if text and not has_file:
        current = wikidata_current(text) or wikidata_research(text)
        if current:
            result = {
                "response": _with_name(current["text"], username),
                "source": "knowledge",
                "provider": "wikidata",
            }
            if current.get("commons"):
                result["commons"] = current["commons"]
            place = _capital_place(text)
            if place:
                result["focus"] = {"place": place, "topic": place, "kind": "fact"}
            return result

    if text and not has_file:
        pictured = picture_request(text)
        if pictured:
            photo = commons_image(pictured)
            if photo:
                reply = _with_name(
                    f"Here is a picture of {pictured} from Wikimedia Commons.",
                    username,
                )
                return {
                    "response": reply,
                    "source": "knowledge",
                    "provider": "commons",
                    "commons": photo,
                    "focus": {"topic": pictured, "kind": "picture"},
                }
            return {
                "response": _with_name(
                    f"I couldn’t find a free picture of {pictured} on Wikimedia Commons.",
                    username,
                ),
                "source": "knowledge",
                "provider": "commons",
            }

    if text and not has_file and _book_first(text):
        from_books = book_agent().answer(text)
        if from_books:
            from_books["response"] = _with_name(from_books["response"], username)
            return from_books

    if text and not has_file and detect_lookup(text):
        defined = _definition_from_local_or_wikipedia(text, independent, username)
        if defined:
            return defined
        return {
            "response": _with_name(
                "I couldn't confirm that from the public sources.",
                username,
            ),
            "source": "knowledge",
            "provider": "wikipedia",
        }

    if text and not has_file:
        guided = how_to_reply(text)
        if guided:
            return {
                "response": _with_name(guided, username),
                "source": "knowledge",
                "provider": "duckduckgo" if "Source:" not in guided else "guide",
                "focus": {"topic": text, "kind": "howto"},
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
            reply = from_books["response"]
            from_books["response"] = _with_name(reply, username)
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
            "I can read an uploaded PNG or JPEG image. This file is not one of those, "
            "so I will not guess what it shows."
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


def _local_knowledge(text, independent, username):
    """Prefer a saved fact, such as who Efatha is, over a web definition."""
    knowledge = getattr(independent, "trained_knowledge", None) or []
    lowered = (text or "").lower()
    best = None
    best_length = 0
    for item in knowledge:
        for keyword in item.get("keywords") or []:
            word = str(keyword).lower()
            if word and word in lowered and len(word) > best_length:
                best = item.get("response")
                best_length = len(word)
    if not best:
        return None
    result = {
        "response": _with_name(best, username),
        "source": "knowledge",
        "provider": "data.json",
    }
    if "efatha" in lowered:
        result["portrait"] = "/static/images/efatha.jpg"
        result["projects"] = [{
            "name": "e-Chat",
            "url": "https://e-chatai.onrender.com/",
            "icon": "/static/images/artificial-intelligence.png",
            "note": "Live research assistant.",
        }]
        result["followups"] = [
            "What does Efatha explore?",
            "How does Efatha spend his leisure?",
            "What else has Efatha built?",
        ]
    return result


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
    result = {
        "response": _with_name(external, username),
        "source": "knowledge",
        "provider": "wikipedia",
    }
    photo = wikidata_image(found["term"]) or commons_image(found["term"])
    if photo:
        result["commons"] = photo
    return result


def _image_lines(response):
    return "\n".join(
        line[2:].strip()
        for line in str(response or "").splitlines()
        if line.startswith("• ")
    )


def _book_first(text):
    """Proof, definition, and why questions in mathematics come from the local books."""
    lowered = (text or "").lower()
    if re.search(r"\b(prove|proof)\b", lowered):
        return True
    if re.search(r"\b(define|why)\b", lowered) and re.search(
        r"\b(theorem|lemma|logic|set|vector|matrix|probability|convex|quantifier|integer|prime|function|basis|null|axiom)\b",
        lowered,
    ):
        return True
    return False


def passages_source(reply):
    match = re.search(r"_([^_\n]+), p\. (\d+)_", reply or "")
    if not match:
        return ""
    return f"Source: {match.group(1)}, p. {match.group(2)}."


def _with_name(text, username):
    if username and text:
        return f"{username}, {text}"
    return text
