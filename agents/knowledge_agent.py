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
    """Return {'kind': 'dictionary'|'topic', 'term': ...} for lookup questions."""
    text = (message or "").strip()
    if not text or len(text) > 180:
        return None

    dictionary_match = DICTIONARY_RE.match(text)
    if dictionary_match:
        term = _clean_term(dictionary_match.group(1))
        if _usable_term(term) and not _looks_like_math(term):
            kind = "dictionary" if len(term.split()) == 1 else "topic"
            return {"kind": kind, "term": term}

    topic_match = TOPIC_RE.match(text)
    if topic_match:
        term = _clean_term(topic_match.group(1))
        if not _usable_term(term) or _looks_like_math(term):
            return None
        kind = "dictionary" if len(term.split()) == 1 else "topic"
        return {"kind": kind, "term": term}
    return None


def lookup_answer(message, local_meanings=None):
    """Combine dictionary, Wikipedia, and Ollama results for a lookup."""
    found = detect_lookup(message)
    if not found:
        return None

    term = found["term"]
    single_word = len(term.split()) == 1
    local = _local_meaning(term, local_meanings or {}) if single_word else None
    if local and found["kind"] == "dictionary":
        return {"response": local, "source": "independent", "provider": "local"}
    dictionary = dictionary_entry(term) if single_word else None
    wiki = None
    if found["kind"] == "topic" or (not dictionary and not local):
        wiki = wikipedia_summary(term)

    notes = _reference_notes(dictionary, wiki)
    ollama_text = ask_ollama(message, notes) if ollama_is_active() else None
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
        response = requests.get(
            DICTIONARY_URL.format(word=requests.utils.quote(word)),
            timeout=4,
        )
        if response.status_code == 404:
            return None
        if not response.ok:
            logger.warning("Dictionary request failed with status %s", response.status_code)
            return None
        return _format_dictionary(response.json())
    except requests.RequestException as exc:
        logger.warning("Dictionary request failed: %s", type(exc).__name__)
        return None


def word_reference(word):
    """A definition plus a Wikipedia article, skipping a bare disambiguation page."""
    term = (word or "").strip().lower()
    if not term or " " in term:
        return None
    definition = dictionary_entry(term) or _wiktionary_definition(term)
    wiki = wikipedia_summary(term, term)
    if not wiki or "may refer to" in wiki.lower():
        title = _disambiguation_target(term)
        if title:
            better = wikipedia_summary(title, title)
            if better and "may refer to" not in better.lower():
                wiki = better
    parts = [part for part in (definition, wiki) if part]
    return "\n\n".join(parts) if parts else None


def _wiktionary_definition(word):
    try:
        response = requests.get(
            "https://en.wiktionary.org/api/rest_v1/page/definition/"
            + requests.utils.quote(word),
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=6,
        )
        if not response.ok:
            return None
        lines = [f"📖 {word}"]
        count = 0
        for block in (response.json() or {}).get("en") or []:
            part = block.get("partOfSpeech") or ""
            for item in block.get("definitions") or []:
                count += 1
                if count > 2:
                    break
                text = re.sub(r"<[^>]+>", "", item.get("definition") or "")
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    label = f"{count}. ({part}) " if part else f"{count}. "
                    lines.append(label + text)
            if count > 2:
                break
        return "\n".join(lines) if count else None
    except requests.RequestException as exc:
        logger.warning("Wiktionary request failed: %s", type(exc).__name__)
        return None


def _disambiguation_target(word):
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "explaintext": 1,
                "exchars": 600,
                "titles": word,
                "format": "json",
                "redirects": 1,
            },
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=8,
        )
        if not response.ok:
            return None
        pages = (response.json().get("query") or {}).get("pages") or {}
        text = ""
        for page in pages.values():
            text = page.get("extract") or ""
        if "may refer to" not in text.lower():
            return None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("=") or "may refer to" in line.lower():
                continue
            title = line.split(",")[0].strip()
            if title and title.lower() != word.lower():
                return title
    except requests.RequestException as exc:
        logger.warning("Wikipedia disambiguation lookup failed: %s", type(exc).__name__)
    return None


def wikipedia_summary(term, question=""):
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
        page = _page_in_sense(wiki, term, question)
        if page is None:
            return None
        summary = _trim((page.summary or "").strip(), 700)
        return f"Wikipedia — {page.title}\n{summary}" if summary else None
    except Exception as exc:
        logger.warning("Wikipedia request failed: %s", type(exc).__name__)
        return None


def _page_in_sense(wiki, term, question):
    """Prefer the sense the question is comparing, not a disambiguation or a place."""
    primary = wiki.page(term)
    if not primary.exists():
        primary = None
    if primary is not None and not _wrong_sense(primary.summary or "", question):
        return primary
    titled = term[:1].upper() + term[1:]
    for suffix in ("programming language", "software"):
        alt = wiki.page(f"{titled} ({suffix})")
        if alt.exists() and (alt.summary or "").strip():
            return alt
    return primary


def _wrong_sense(summary, question):
    head = (summary or "")[:240].lower()
    question = (question or "").lower()
    if "may refer to" in head or "disambiguation" in head:
        return True
    off = ("island", "snake", "genus", "species", "river", "mountain", "album", "film")
    return any(word in head for word in off) and not any(
        word in question for word in off
    )


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
                        "content": (
                            "You are e-Chat, an assistant created by Efatha Rutakaza. "
                            "Answer directly."
                        ),
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
    return "\n".join(lines) if count else None


def _reference_notes(dictionary, wiki):
    return "\n\n".join(part for part in (dictionary, wiki) if part)


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
    return f"📖 {term.capitalize()}: {meaning}" if meaning else None


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
    if not text or len(text) <= limit:
        return text or ""
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "..."


def looks_like_open_question(text):
    """An opinion or imagined situation, after the books have nothing to cite."""
    lowered = (text or "").lower()
    marks = (
        "what do you think",
        "imagine ",
        "suppose ",
        "what would you",
        "in your opinion",
    )
    return any(mark in lowered for mark in marks)


def search_result_text(question):
    """Retrieve public snippets and retain only those matching the question."""
    query = re.sub(r"\s+", " ", (question or "")).strip()
    if not query:
        return None
    wanted = _question_words(query)
    found = _duckduckgo_snippets(query)
    lines = _matching(found, wanted) or found[:2]
    if not lines:
        content = [
            word for word in wanted
            if word not in _NUMBER_WORDS and not word.isdigit()
        ]
        lines = _matching(_wikipedia_snippet(query), content, minimum=2)
    if not lines:
        return None
    return "Search result:\n" + "\n".join(lines[:2])


_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}


def _forms(word):
    forms = [word]
    if word in _NUMBER_WORDS:
        forms.append(_NUMBER_WORDS[word])
    for name, digit in _NUMBER_WORDS.items():
        if word == digit:
            forms.append(name)
    return forms


def _word_hits(text, words):
    lowered = (text or "").lower()
    hits = 0
    for word in words:
        if any(re.search(rf"\b{re.escape(form)}s?\b", lowered) for form in _forms(word)):
            hits += 1
    return hits


def _question_words(query):
    skip = {
        "imagine", "suppose", "what", "think", "would", "your", "opinion",
        "then", "have", "with", "this", "that", "from", "about", "should",
        "does", "they", "them", "into", "when", "where", "which",
    }
    words = []
    for word in re.findall(r"[A-Za-z0-9]+", (query or "").lower()):
        if word in skip:
            continue
        if word.isdigit() or word in _NUMBER_WORDS or len(word) >= 4:
            words.append(word)
    return words


def _matching(lines, words, minimum=2):
    """Rank by the question's own words, especially a changed number."""
    numbers = [word for word in words if word.isdigit() or word in _NUMBER_WORDS]
    ranked = []
    for line in lines or []:
        hits = _word_hits(line, words)
        number_hits = _word_hits(line, numbers) if numbers else 0
        if hits >= minimum or number_hits:
            ranked.append((number_hits, hits, line))
    if numbers and any(item[0] for item in ranked):
        ranked = [item for item in ranked if item[0]]
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    kept = []
    for _numbers, _hits, line in ranked:
        if line not in kept:
            kept.append(line)
        if len(kept) == 2:
            break
    return kept


def _duckduckgo_snippets(query):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    }
    attempts = (
        ("post", "https://html.duckduckgo.com/html/", {"q": query[:300]}),
        ("get", "https://html.duckduckgo.com/html/", {"q": query[:300]}),
        ("get", "https://duckduckgo.com/html/", {"q": query[:300]}),
    )
    for method, url, params in attempts:
        try:
            if method == "post":
                response = requests.post(url, data=params, headers=headers, timeout=8)
            else:
                response = requests.get(url, params=params, headers=headers, timeout=8)
            response.raise_for_status()
        except requests.RequestException:
            continue
        snippets = re.findall(r'result__snippet"[^>]*>(.*?)</a>', response.text, re.S)
        lines = _clean_snippets(snippets)
        if lines:
            return lines
    return []


def _wikipedia_snippet(query):
    """Works from a hosted server when the search page is blocked."""
    words = _question_words(query)
    topic = " ".join(words[:6]) or query
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": topic,
                "gsrlimit": 1,
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "format": "json",
            },
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=8,
        )
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except (requests.RequestException, ValueError):
        return []
    for page in pages.values():
        extract = _finish_at_stop(
            re.sub(r"\s+", " ", page.get("extract") or "").strip()
        )
        title = page.get("title") or ""
        if len(extract) > 40:
            return [f"{title}. {extract}"]
    return []


def _clean_snippets(snippets):
    lines = []
    for raw in snippets:
        clean = re.sub(r"<[^>]+>", "", raw)
        clean = clean.replace("&amp;", "&").replace("&quot;", '"')
        clean = clean.replace("&#39;", "'").replace("&#x27;", "'")
        clean = re.sub(r"\s+", " ", clean).strip()
        clean = _finish_at_stop(clean)
        if len(clean) > 40 and clean not in lines:
            lines.append(clean)
        if len(lines) == 2:
            break
    return lines


def _finish_at_stop(text):
    """End on the last full sentence and drop a trailing fragment."""
    original = text or ""
    cut = re.sub(r"(?:\s*(?:\.\.\.|…))+\s*$", "", original).strip()
    stops = list(re.finditer(r"[.!?]", cut))
    if stops:
        return cut[:stops[-1].end()].strip()
    if re.search(r"(?:\.\.\.|…)\s*$", original):
        return ""
    if not cut:
        return ""
    return cut.rstrip(" ,;:-") + "."
