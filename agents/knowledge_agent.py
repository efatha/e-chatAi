"""Word meanings and topic lookups.

A meaning question goes to the Free Dictionary API. A broader topic goes to
Wikipedia. When Ollama is running, Flask asks it to explain those notes and
returns both together.
"""

import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

DICTIONARY_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
WIKI_USER_AGENT = os.getenv(
    "WIKI_USER_AGENT",
    "e-Chat/1.0 (local educational chatbot)",
)

DICTIONARY_RE = re.compile(
    r"^(?:what(?:'s| is) the meaning of|what does|meaning of|definition of|define)"
    r"\s+(.+?)(?:\s+mean)?\s*[?.!]*$",
    re.IGNORECASE,
)
TOPIC_RE = re.compile(
    r"^(?:what(?:'s| is)|who(?:'s| is)|tell me about|explain|do you know(?: about)?)"
    r"\s+(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
SKIP_TERMS = {"the", "a", "an", "my", "your", "this", "that", "it", "me", "you"}


def detect_lookup(message):
    """Return {'kind': 'dictionary'|'topic', 'term': ...} when the user is looking something up."""
    text = (message or "").strip()
    if not text or len(text) > 180:
        return None

    dictionary_match = DICTIONARY_RE.match(text)
    if dictionary_match:
        term = _clean_term(dictionary_match.group(1))
        if _usable_term(term) and not _looks_like_math(term):
            return {"kind": "dictionary", "term": term}

    topic_match = TOPIC_RE.match(text)
    if topic_match:
        term = _clean_term(topic_match.group(1))
        if not _usable_term(term):
            return None
        if _looks_like_math(term):
            return None
        kind = "dictionary" if len(term.split()) == 1 else "topic"
        return {"kind": kind, "term": term}
    return None


def lookup_answer(message, local_meanings=None):
    """Dictionary, Wikipedia, and Ollama combined. None when this is not a lookup."""
    found = detect_lookup(message)
    if not found:
        return None

    term = found["term"]
    single_word = len(term.split()) == 1
    local = _local_meaning(term, local_meanings or {}) if single_word else None
    dictionary = dictionary_entry(term) if single_word else None
    # A meaning question should not fall through to a Wikipedia disambiguation
    # page when this project already has a definition for that word.
    wiki = None
    if found["kind"] == "topic" or (not dictionary and not local):
        wiki = wikipedia_summary(term)

    notes = _reference_notes(dictionary, wiki)
    ollama_text = None
    if ollama_is_active():
        ollama_text = ask_ollama(message, notes)

    combined = _combine(ollama_text, dictionary, wiki, include_wiki=not ollama_text)
    if combined:
        providers = []
        if dictionary:
            providers.append("dictionary")
        if wiki and not ollama_text:
            providers.append("wikipedia")
        if ollama_text:
            providers.append("ollama")
        return {
            "response": combined,
            "source": "knowledge",
            "provider": "+".join(providers),
        }

    if local:
        return {"response": local, "source": "independent", "provider": "local"}
    return None


def ollama_answer(message):
    """General reply from the local model when Ollama is running."""
    if not message or not ollama_is_active():
        return None
    text = ask_ollama(message, "")
    if not text:
        return None
    return {"response": text, "source": "independent", "provider": "ollama"}


def dictionary_entry(term):
    word = term.strip().lower()
    if " " in word or not word:
        return None
    try:
        response = requests.get(DICTIONARY_URL.format(word=requests.utils.quote(word)), timeout=4)
        if response.status_code == 404:
            return None
        if not response.ok:
            logger.warning("Dictionary request failed with status %s", response.status_code)
            return None
        return _format_dictionary(response.json())
    except requests.RequestException as exc:
        logger.warning("Dictionary request failed: %s", type(exc).__name__)
        return None


def wikipedia_summary(term):
    try:
        import wikipediaapi
    except ImportError:
        logger.warning("wikipedia-api is not installed")
        return None

    try:
        wiki = wikipediaapi.Wikipedia(
            user_agent=WIKI_USER_AGENT,
            language="en",
            extract_format=wikipediaapi.ExtractFormat.WIKI,
            max_retries=0,
            timeout=8,
        )
        page = wiki.page(term)
        if not page.exists():
            return None
        summary = (page.summary or "").strip()
        if not summary:
            return None
        summary = _trim(summary, 700)
        titles = [section.title for section in page.sections[:3] if section.title]
        lines = [f"Wikipedia — {page.title}", summary]
        if titles:
            lines.append("Sections: " + ", ".join(titles))
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("Wikipedia request failed: %s", type(exc).__name__)
        return None


def ollama_is_active():
    try:
        response = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=1.5)
        return response.ok and bool((response.json() or {}).get("models"))
    except requests.RequestException:
        return False


def ask_ollama(message, notes):
    model = _ollama_model()
    if not model:
        return None
    prompt = message
    if notes:
        prompt = (
            "Use the reference notes when they help. "
            "Answer in a short paragraph. Do not invent a pronunciation.\n\n"
            f"Reference notes:\n{notes}\n\nQuestion: {message}"
        )
    try:
        response = requests.post(
            f"{OLLAMA_BASE}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are e-Chat, an assistant created by Efatha Rutakaza. Answer directly.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=40,
        )
        if not response.ok:
            logger.warning("Ollama request failed with status %s", response.status_code)
            return None
        text = (response.json().get("message") or {}).get("content", "")
        return text.strip() or None
    except requests.RequestException as exc:
        logger.warning("Ollama request failed: %s", type(exc).__name__)
        return None


def _ollama_model():
    chosen = os.getenv("OLLAMA_MODEL")
    if chosen:
        return chosen
    try:
        response = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=1.5)
        models = (response.json() or {}).get("models") or []
        if models:
            return models[0].get("name")
    except requests.RequestException:
        return None
    return None


def _format_dictionary(payload):
    if not isinstance(payload, list) or not payload:
        return None
    entry = payload[0]
    word = entry.get("word") or ""
    phonetic = entry.get("phonetic") or ""
    if not phonetic:
        for item in entry.get("phonetics") or []:
            if item.get("text"):
                phonetic = item["text"]
                break
    lines = [f"📖 {word}" + (f"  {phonetic}" if phonetic else "")]
    count = 0
    for meaning in entry.get("meanings") or []:
        part = meaning.get("partOfSpeech") or ""
        for definition in meaning.get("definitions") or []:
            count += 1
            if count > 2:
                break
            label = f"{count}. ({part}) " if part else f"{count}. "
            lines.append(label + (definition.get("definition") or "").strip())
            example = (definition.get("example") or "").strip()
            if example:
                lines.append(f"   Example: {example}")
        if count > 2:
            break
    if count == 0:
        return None
    return "\n".join(lines)


def _reference_notes(dictionary, wiki):
    parts = [part for part in (dictionary, wiki) if part]
    return "\n\n".join(parts)


def _combine(ollama_text, dictionary, wiki, include_wiki):
    parts = []
    if ollama_text:
        parts.append(ollama_text.strip())
    if dictionary:
        parts.append(dictionary)
    if include_wiki and wiki:
        parts.append(wiki)
    return "\n\n".join(parts).strip()


def _local_meaning(term, word_meanings):
    if " " in term:
        return None
    meaning = word_meanings.get(term.lower())
    if not meaning:
        return None
    return f"📖 {term.capitalize()}: {meaning}"


def _clean_term(term):
    cleaned = re.sub(r"\s+", " ", (term or "").strip(" \t\"'"))
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _looks_like_math(term):
    lowered = term.lower()
    if re.search(r"\d", lowered) and re.search(
        r"[+\-*/^%]|\b(plus|minus|times|multiply|divide|divided|sum|add|subtract)\b",
        lowered,
    ):
        return True
    return False


def _usable_term(term):
    if not term or term.lower() in SKIP_TERMS:
        return False
    if re.fullmatch(r"[\d\s+\-*/().%^]+", term):
        return False
    return bool(re.search(r"[A-Za-z]", term))


def _trim(text, limit):
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "..."
