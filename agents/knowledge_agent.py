"""Word meanings and topic lookups.

A meaning question goes to the Free Dictionary API. A broader topic goes to
Wikipedia. When Ollama is running, Flask asks it to explain those notes and
returns both together.
"""

import html
import json
import logging
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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


PICTURE_RE = re.compile(
    r"^(?:please\s+)?(?:show|give|find|display|get)(?:\s+me)?(?:\s+a|\s+an|\s+the)?"
    r"\s+(?:picture|photo|photograph|image)s?\s+of\s+(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)


def picture_request(message):
    """Return the topic when the user asks to see a picture."""
    match = PICTURE_RE.match((message or "").strip())
    if not match:
        return None
    term = _clean_term(match.group(1))
    return term if _usable_term(term) else None


def commons_image(term):
    """One free image from Wikimedia Commons, with credit and a license."""
    subject = (term or "").strip()
    if not subject:
        return None
    photo = _fresh_commons_image(subject)
    if photo:
        _remember_image(subject, photo)
        return photo
    return _remembered_image(subject)


def _fresh_commons_image(subject):
    try:
        response = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": subject,
                "gsrnamespace": 6,
                "gsrlimit": 8,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime",
                "iiurlwidth": 640,
            },
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=16,
        )
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Commons search failed: %s", type(exc).__name__)
        return None
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0] or {}
        mime = (info.get("mime") or "").lower()
        thumb = info.get("thumburl") or ""
        if mime not in {"image/jpeg", "image/png", "image/webp"} or not thumb:
            continue
        meta = info.get("extmetadata") or {}
        title = page.get("title") or subject
        slug = title.replace(" ", "_")
        return {
            "thumbnail": thumb,
            "page": "https://commons.wikimedia.org/wiki/" + requests.utils.quote(slug),
            "title": title.replace("File:", ""),
            "creator": _meta_text(meta, "Artist") or "Unknown creator",
            "license": _meta_text(meta, "LicenseShortName") or "See the Commons page",
            "license_url": _meta_text(meta, "LicenseUrl"),
        }
    return None


_OFFICE = re.compile(
    r"^(?:who(?:'s| is))\s+(?:the\s+)?(?:current\s+)?"
    r"(president|prime minister|king|queen|chancellor|head of state)\s+of\s+(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_CAPITAL = re.compile(
    r"^(?:(?:what|which)(?:'s| is)|where(?:'s| is)|name|tell me)\s+"
    r"(?:the\s+)?(?:current\s+)?capital(?:\s+city)?\s+of\s+(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_CAPITAL_CITY = re.compile(
    r"^(?:what|which)\s+city\s+is\s+(?:the\s+)?(?:current\s+)?capital(?:\s+city)?\s+of\s+(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_CAPITAL_OWN = re.compile(
    r"^(?:what|which)(?:'s| is)\s+(.+?)(?:'s)\s+(?:current\s+)?capital(?:\s+city)?\s*[?.!]*$",
    re.IGNORECASE,
)
_CAPITAL_BARE = re.compile(
    r"^(?:the\s+)?capital(?:\s+city)?\s+of\s+(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_FLAG = re.compile(
    r"^(?:(?:show|give|display)(?:\s+me)?\s+)?(?:the\s+)?flag\s+of\s+(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_OFFICE_PROPERTY = {
    "president": "P35",
    "head of state": "P35",
    "king": "P35",
    "queen": "P35",
    "prime minister": "P6",
    "chancellor": "P6",
}


def wikidata_current(message):
    """The fact that is true today, plus the picture Wikidata points to."""
    text = (message or "").strip()
    office = _OFFICE.match(text)
    capital = _CAPITAL.match(text) or _CAPITAL_CITY.match(text) or _CAPITAL_OWN.match(text) or _CAPITAL_BARE.match(text)
    flag = _FLAG.match(text)
    if office:
        role = office.group(1).lower()
        place = _clean_term(office.group(2))
        return _current_office(place, role, _OFFICE_PROPERTY[role])
    if capital:
        return _current_capital(_clean_term(capital.group(1)))
    if flag:
        return _current_flag(_clean_term(flag.group(1)))
    return None


_WHO = re.compile(
    r"^who\s+(?:was|is|were|are|'s)?\s*(?:the\s+)?(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_WHEN = re.compile(
    r"^when\s+(?:did|was|were|is|'s)?\s*(?:the\s+)?(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_WIN = re.compile(
    r"^when\s+did\s+(.+?)\s+(?:win|won)\s+(?:the\s+)?(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_WHO_WORDS = (
    "invented", "discovered", "created", "founded", "designed", "wrote",
    "written", "built", "developed", "painted", "composed", "directed",
)
_WHEN_WORDS = (
    "start", "started", "begin", "began", "happen", "happened",
    "colonized", "colonised", "invented", "discovered", "founded",
)
_WHO_PROPS = (
    ("P61", "invented by"),
    ("P170", "created by"),
    ("P178", "developed by"),
    ("P287", "designed by"),
    ("P112", "founded by"),
    ("P50", "written by"),
    ("P57", "directed by"),
    ("P86", "composed by"),
)
_WHEN_PROPS = (
    ("P580", "started"),
    ("P571", "began"),
    ("P575", "was discovered"),
    ("P585", "took place"),
    ("P1619", "opened"),
    ("P577", "was published"),
)


def wikidata_research(message):
    """Who and when questions, answered from the public record for that topic."""
    text = _normalize_question(message)
    won = _WIN.match(text)
    if won:
        found = _research_win(_clean_term(won.group(1)), _clean_term(won.group(2)))
        return found or _never_won_reply(_clean_term(won.group(1)), _clean_term(won.group(2)))
    who = _WHO.match(text)
    if who:
        found = _research_who(who.group(1), text)
        if not found and re.match(r"^who\s+(?:is|was)\b", text, re.IGNORECASE):
            found = _wiki_who(who.group(1))
            if not found:
                return {"text": f"I couldn't find a public record for {_clean_term(who.group(1))}."}
        return found or _who_directive(who.group(1), text)
    when = _WHEN.match(text)
    if when:
        return _research_when(when.group(1), text) or _when_directive(when.group(1), text)
    return None


def _research_who(rest, original):
    coach = _coach_answer(rest)
    if coach:
        return coach
    topic = _research_topic(rest)
    item = (_wikidata_item(topic) or _wikidata_item(rest)) if topic else None
    if item and _is_human(item):
        return _person_answer(item)
    if item:
        for prop in ("P1308", "P35", "P6"):
            people = _preferred_people(item, prop)
            if people and _is_human(people[0]["entity"]):
                return _person_answer(people[0]["entity"])
        for prop, phrase in _WHO_PROPS:
            people = _claim_people(item, prop)
            if people:
                names = _join_names(person["name"] for person in people[:3])
                photo = _commons_file(_claim_filename(people[0]["entity"], "P18"))
                return {
                    "text": _who_sentence(names, _label(item), original, phrase),
                    "commons": photo,
                }
    suggested = _suggested_item(topic or rest)
    if suggested and suggested is not item:
        if _is_human(suggested):
            return _person_answer(suggested)
        for prop in ("P1308", "P35", "P6"):
            people = _preferred_people(suggested, prop)
            if people and _is_human(people[0]["entity"]):
                return _person_answer(people[0]["entity"])
    if "moon" in original.lower():
        landing = _wikidata_item("Apollo 11")
        crew = _claim_labels(landing, "P1029") or _claim_labels(landing, "P710")
        if crew:
            return {
                "text": _moon_sentence(crew[0]),
                "commons": wikidata_image(crew[0]),
            }
    if item and "first" in original.lower() and _description(item):
        return {
            "text": _first_sentence(_label(item), _description(item)),
            "commons": _commons_file(_claim_filename(item, "P18")),
        }
    return None


def _coach_answer(rest):
    if not re.search(r"\b(coach|manager)\b", rest or "", re.IGNORECASE):
        return None
    place = re.sub(r"^.*\b(?:of|for)\s+", "", rest, count=1, flags=re.IGNORECASE).strip(" ?.!")
    place = _expand_name(_clean_term(place))
    if not place:
        return None
    team = (
        _wikidata_item(f"{place} national football team", "football")
        or _wikidata_from_title(f"{place} national football team")
        or _wikidata_from_title(f"{place} men's national football team")
    )
    people = _preferred_people(team, "P286")
    if people and _is_human(people[0]["entity"]):
        return _person_answer(people[0]["entity"])
    return None


def _suggested_item(term):
    for guess in _name_guesses(term):
        title = _wiki_suggest(guess)
        item = _wikidata_from_title(title) or (_wikidata_item(title) if title else None)
        if item:
            return item
    return None


def _name_guesses(term):
    text = (term or "").strip()
    guesses = [text] if text else []
    if text[:1].lower() == "c":
        guesses.append("S" + text[1:])
    elif text[:1].lower() == "s":
        guesses.append("C" + text[1:])
    return guesses


def _wikidata_from_title(title):
    if not title:
        return None
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": title,
                "prop": "pageprops",
                "ppprop": "wikibase_item",
                "redirects": 1,
                "format": "json",
            },
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=12,
        )
        response.raise_for_status()
        pages = ((response.json().get("query") or {}).get("pages") or {}).values()
    except (requests.RequestException, ValueError):
        return None
    for page in pages:
        item_id = (page.get("pageprops") or {}).get("wikibase_item")
        if item_id:
            return _wikidata_by_id(item_id)
    return None


def _wiki_suggest(term):
    if not term:
        return ""
    titled = " ".join(part[:1].upper() + part[1:] if part else part for part in term.split())
    for guess in (term, titled):
        title = _opensearch_title(guess)
        if title:
            return title
    return ""


def _wiki_who(rest):
    for guess in _name_guesses(rest):
        title = _wiki_suggest(guess)
        extract = _wiki_extract(title)
        if not extract:
            continue
        sentence = extract.split(". ")[0].strip().rstrip(".")
        if len(sentence) < 40:
            continue
        item = _wikidata_from_title(title)
        photo = _commons_file(_claim_filename(item, "P18")) if item else None
        result = {"text": sentence + "."}
        if photo:
            result["commons"] = photo
        return result
    return None


def _wiki_extract(title):
    if not title:
        return ""
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "redirects": 1,
                "titles": title,
                "format": "json",
            },
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=12,
        )
        response.raise_for_status()
        pages = ((response.json().get("query") or {}).get("pages") or {}).values()
    except (requests.RequestException, ValueError):
        return ""
    for page in pages:
        text = (page.get("extract") or "").strip()
        if text and "may refer to" not in text.lower():
            return text
    return ""


def _opensearch_title(term):
    if not term:
        return ""
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "opensearch", "search": term, "limit": 1, "namespace": 0, "format": "json"},
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=12,
        )
        response.raise_for_status()
        titles = response.json()[1]
    except (requests.RequestException, ValueError, IndexError, KeyError):
        return ""
    return titles[0] if titles else ""


def _preferred_people(entity, prop):
    if not entity:
        return []
    ranked = []
    for claim in (entity.get("claims") or {}).get(prop) or []:
        rank = claim.get("rank")
        if rank == "deprecated":
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        item_id = value.get("id") if isinstance(value, dict) else None
        if not item_id:
            continue
        person = _wikidata_by_id(item_id) or {}
        if not _label(person) or _label(person) == "that subject":
            continue
        ranked.append((0 if rank == "preferred" else 1, {"name": _label(person), "entity": person}))
    ranked.sort(key=lambda item: item[0])
    return [person for _, person in ranked]


def _research_when(rest, original):
    topic = _research_topic(rest)
    if not topic:
        return None
    guesses = [topic]
    lowered = original.lower()
    if "colon" in lowered:
        guesses = [f"colonisation of {topic}", f"colonization of {topic}", f"{topic} Protectorate", topic]
    elif any(word in lowered for word in ("start", "begin", "began")):
        guesses = [f"{topic} pandemic", topic, f"{topic}-19 pandemic"]
    for guess in guesses:
        item = _wikidata_item(guess)
        if not item:
            continue
        for prop, phrase in _WHEN_PROPS:
            moments = _claim_times(item, prop)
            if moments:
                return {
                    "text": _when_sentence(_label(item), moments[0], original, phrase),
                    "commons": _commons_file(_claim_filename(item, "P18")) or _commons_file(_claim_filename(item, "P41")),
                }
    return None


def _research_win(team_text, event_text):
    team_text = _expand_name(team_text)
    team = None
    for guess in (f"{team_text} national football team", f"{team_text} football team", team_text):
        found = _wikidata_item(guess, "football")
        if found and "team" in _description(found).lower():
            team = found
            break
    team = team or _wikidata_item(team_text, "football")
    if not team:
        return None
    team_id = team.get("id")
    words = [word for word in re.findall(r"[a-z]{4,}", event_text.lower())]
    query = f"""
    SELECT ?eventLabel ?date WHERE {{
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
      ?event wdt:P1346 wd:{team_id} .
      ?event wdt:P585 ?date .
      ?event rdfs:label ?eventLabel .
      FILTER(LANG(?eventLabel) = "en")
    }}
    ORDER BY ?date
    LIMIT 20
    """
    rows = _sparql(query)
    if rows is None:
        return None
    picked = []
    for row in rows:
        label = ((row.get("eventLabel") or {}).get("value") or "")
        if words and not any(word in label.lower() for word in words):
            continue
        picked.append((label, _format_time((row.get("date") or {}).get("value"))))
    if not picked:
        return None
    editions = [row for row in picked if not row[0].lower().endswith("final")]
    picked = editions or picked
    lines = "; ".join(f"{name} ({when})" for name, when in picked[:4] if when)
    return {
        "text": _win_sentence(_label(team), event_text, picked),
        "commons": _commons_file(_claim_filename(team, "P41")) or _commons_file(_claim_filename(team, "P154")),
    }


_NAME_ALIASES = {
    "drc": "DR Congo",
    "dr congo": "DR Congo",
    "usa": "United States",
    "us": "United States",
    "uk": "United Kingdom",
    "uae": "United Arab Emirates",
}


_WORD_FIXES = {
    "inveted": "invented",
    "inventd": "invented",
    "invened": "invented",
    "inveted": "invented",
    "creatd": "created",
    "craeted": "created",
    "developped": "developed",
    "developd": "developed",
    "fonded": "founded",
    "coah": "coach",
    "winned": "won",
}


def _normalize_question(message):
    text = re.sub(r"\s+", " ", (message or "").strip())
    def fix(match):
        return _WORD_FIXES.get(match.group(0).lower(), match.group(0))
    text = re.sub(r"[A-Za-z]+", fix, text)
    text = re.sub(r"\bafcon\b", "Africa Cup of Nations", text, flags=re.IGNORECASE)
    text = re.sub(r"\bai\b", "artificial intelligence", text, flags=re.IGNORECASE)
    return text


def _expand_name(text):
    return _NAME_ALIASES.get((text or "").strip().lower(), text)


def _never_won_reply(team_text, event_text):
    """Say the win is absent only after the other public sources also omit it."""
    place = _expand_name(team_text)
    place = place[:1].upper() + place[1:] if place else "That team"
    event = event_text or "that competition"
    verdict = _public_win_check(place, event)
    if verdict is True:
        return None
    if re.search(r"africa|nations", event, re.IGNORECASE):
        sentence = f"{place} has never won any AFCON."
    else:
        thing = _the(event)
        sentence = f"{place} has never won {thing[0].lower() + thing[1:]}."
    if verdict is None:
        sentence = f"I couldn't confirm that {place} has won { _the(event)[0].lower() + _the(event)[1:] }."
    return {"text": sentence}


def _public_win_check(team, event):
    """True if a public snippet credits the win, False if sources answered without one, None if they were silent."""
    query = f"{team} won {event}"
    lines = list(_wikipedia_snippet(query) or [])
    lines.extend(_duckduckgo_snippets(query) or [])
    if not lines:
        return None
    blob = " ".join(lines).lower()
    team_word = team.lower().split()[0]
    if team_word not in blob:
        return False
    if any(mark in blob for mark in ("never won", "has not won", "have not won", "did not win", "yet to win")):
        return False
    if any(mark in blob for mark in ("won the", "winners", "champions", "lifted the trophy", "won afcon")):
        return True
    return False


def _who_directive(rest, original):
    topic = _research_topic(rest) or _clean_term(rest)
    if not topic:
        return None
    thing = "Artificial intelligence" if topic.lower() == "artificial intelligence" else _the(topic)
    active, _passive = _asked_verb(original, "developed by")
    verb = "developed" if active == "invented" else active
    lead = f"{thing} was {verb} by many people, not by one inventor."
    intro = _intro_sentence(topic)
    if intro:
        lead = f"{lead} {intro}"
    return {"text": lead, "commons": wikidata_image(topic)}


def _when_directive(rest, original):
    topic = _research_topic(rest) or _clean_term(rest)
    if not topic:
        return None
    intro = _intro_sentence(topic)
    thing = _the(topic)
    if intro:
        return {"text": f"{thing} does not have one simple date. {intro}"}
    return {"text": f"I couldn't find a date for when {thing[0].lower() + thing[1:]} happened."}


def _intro_sentence(topic):
    summary = _wikipedia_plain_summary(topic) or ""
    body = summary.split("\n", 1)[-1].strip()
    if not body or "may refer to" in body.lower():
        return ""
    sentence = body.split(". ")[0].strip().rstrip(".")
    if len(sentence) < 40:
        return ""
    return sentence + "."


def _join_names(names):
    names = [name for name in names if name]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + ", and " + names[-1]


_VERB_FORMS = (
    ("invented", "invented", "was invented by"),
    ("discovered", "discovered", "was discovered by"),
    ("created", "created", "was created by"),
    ("founded", "founded", "was founded by"),
    ("designed", "designed", "was designed by"),
    ("written", "wrote", "was written by"),
    ("wrote", "wrote", "was written by"),
    ("built", "built", "was built by"),
    ("developed", "developed", "was developed by"),
    ("painted", "painted", "was painted by"),
    ("composed", "composed", "was composed by"),
    ("directed", "directed", "was directed by"),
    ("colonized", "colonized", "was colonized"),
    ("colonised", "colonised", "was colonised"),
    ("started", "started", "started"),
    ("start", "started", "started"),
    ("began", "began", "began"),
    ("begin", "began", "began"),
    ("opened", "opened", "was opened"),
    ("published", "published", "was published"),
    ("won", "won", "was won by"),
    ("win", "won", "was won by"),
)


def _asked_verb(text, fallback=""):
    """The verb the person used, as an active form and a passive form."""
    lowered = (text or "").lower()
    for word, active, passive in _VERB_FORMS:
        if re.search(rf"\b{word}\b", lowered):
            return active, passive
    cleaned = (fallback or "").replace(" by", "").strip()
    if not cleaned:
        return "is linked with", "is linked with"
    return cleaned, f"was {cleaned} by" if not cleaned.startswith("was ") else cleaned


def _the(label):
    name = (label or "").strip()
    if not name:
        return name
    if re.match(r"^(the|a|an)\b", name, re.IGNORECASE):
        return name[0].upper() + name[1:]
    second = name[1:2]
    if name[0].isupper() and (second.isupper() or second.isdigit()):
        shown = name
    elif name[0].isupper():
        shown = name[0].lower() + name[1:]
    else:
        shown = name
    return "The " + shown


def _who_sentence(names, subject, original, property_phrase):
    active, passive = _asked_verb(original, property_phrase)
    thing = _the(subject)
    if random.choice((True, False)):
        return f"{names} {active} {thing[0].lower() + thing[1:]}."
    return f"{thing} {passive} {names}."


def _when_sentence(subject, moment, original, property_phrase):
    active, passive = _asked_verb(original, property_phrase)
    thing = _the(subject)
    soft = thing[0].lower() + thing[1:]
    if "colon" in (original or "").lower():
        if random.choice((True, False)):
            return f"{subject} was colonized on {moment}."
        return f"The colonization of {subject} began on {moment}."
    if passive.startswith("was "):
        if random.choice((True, False)):
            return f"{thing} {passive} on {moment}."
        return f"{moment} is when {soft} {passive}."
    if random.choice((True, False)):
        return f"{thing} {active} on {moment}."
    return f"{moment} is when {soft} {active}."


def _win_sentence(team, event_text, picked):
    event = _the(event_text)
    years = []
    for _name, moment in picked[:4]:
        year = (moment or "").split()[-1]
        if year and year not in years:
            years.append(year)
    when = " and ".join(years)
    if random.choice((True, False)):
        return f"{team} won {event[0].lower() + event[1:]} in {when}."
    return f"{event} was won by {team} in {when}."


def _moon_sentence(name):
    if random.choice((True, False)):
        return f"{name} was the first person to walk on the Moon."
    return "The first person to walk on the Moon was " + name + "."


def _first_sentence(name, detail):
    if random.choice((True, False)):
        return f"{name} is the match for that question. {detail}."
    return f"The match for that question is {name}. {detail}."


def _research_topic(rest):
    text = _expand_name(_clean_term(rest))
    text = re.sub(
        r"^(?:invented|discovered|created|founded|designed|wrote|written|built|developed|painted|composed|directed)\s+(?:the\s+)?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:start|started|begin|began|happen|happened|colonized|colonised|invented|discovered|founded)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_term(text)


def _person_answer(item):
    name = _label(item)
    detail = _description(item)
    if detail:
        sentence = random.choice((
            f"{name} is {detail}.",
            f"{detail[:1].upper()}{detail[1:]}: {name}.",
        ))
    else:
        sentence = name + "."
    return {
        "text": sentence,
        "commons": _commons_file(_claim_filename(item, "P18")),
    }


def _is_human(entity):
    for claim in ((entity.get("claims") or {}).get("P31") or []):
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        if value.get("id") == "Q5":
            return True
    return False


def _description(entity):
    if not entity:
        return ""
    return ((entity.get("descriptions") or {}).get("en") or {}).get("value") or ""


def _claim_people(entity, prop):
    people = []
    seen = set()
    if not entity:
        return people
    for claim in (entity.get("claims") or {}).get(prop) or []:
        if claim.get("rank") == "deprecated":
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        item_id = value.get("id") if isinstance(value, dict) else None
        if not item_id or item_id in seen:
            continue
        person = _wikidata_by_id(item_id) or {}
        named = _label(person)
        if not named or named == "that subject":
            continue
        seen.add(item_id)
        people.append({"name": named, "entity": person})
    return people


def _claim_labels(entity, prop):
    return [person["name"] for person in _claim_people(entity, prop)]


def _claim_times(entity, prop):
    found = []
    for claim in (entity.get("claims") or {}).get(prop) or []:
        if claim.get("rank") == "deprecated":
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict) and value.get("time"):
            shown = _format_time(value["time"])
            if shown and shown not in found:
                if claim.get("rank") == "preferred":
                    return [shown]
                found.append(shown)
    return found


def _format_time(raw):
    match = re.match(r"\+?(\d{4})-(\d{2})-(\d{2})", raw or "")
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    months = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    if not month:
        return str(year)
    if not day:
        return f"{months[month - 1]} {year}"
    return f"{day} {months[month - 1]} {year}"


def _sparql(query):
    try:
        response = requests.get(
            "https://query.wikidata.org/sparql",
            params={"query": query, "format": "json"},
            headers={"User-Agent": WIKI_USER_AGENT, "Accept": "application/sparql-results+json"},
            timeout=22,
        )
        response.raise_for_status()
        return ((response.json().get("results") or {}).get("bindings") or [])
    except (requests.RequestException, ValueError):
        return None


def wikidata_image(term):
    """The lead picture Wikidata stores for a topic, or the last saved one."""
    subject = (term or "").strip()
    item = _wikidata_item(subject) if subject else None
    filename = _claim_filename(item, "P18") or _claim_filename(item, "P41") if item else None
    photo = _commons_file(filename) if filename else None
    if photo:
        _remember_image(subject, photo)
        return photo
    return _remembered_image(subject)


_IMAGE_CACHE = Path(__file__).resolve().parent.parent / "image_cache.json"


def _remember_image(term, photo):
    key = (term or "").strip().lower()
    if not key or not photo or not photo.get("thumbnail"):
        return
    saved = _image_store()
    saved[key] = photo
    try:
        _IMAGE_CACHE.write_text(json.dumps(saved), encoding="utf-8")
    except OSError:
        return


def _remembered_image(term):
    key = (term or "").strip().lower()
    if not key:
        return None
    photo = _image_store().get(key)
    return photo if isinstance(photo, dict) and photo.get("thumbnail") else None


def _image_store():
    try:
        saved = json.loads(_IMAGE_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _current_office(place, role, prop):
    country = _wikidata_item(place)
    if not country:
        return None
    holder_id = _current_item_id(country, prop)
    if not holder_id:
        return None
    holder = _wikidata_by_id(holder_id)
    if not holder:
        return None
    name = _label(holder)
    country_name = _label(country)
    photo = _commons_file(_claim_filename(holder, "P18"))
    return {
        "text": random.choice((
            f"The current {role} of {country_name} is {name}.",
            f"{name} is the current {role} of {country_name}.",
        )),
        "commons": photo,
    }


def _current_capital(place):
    country = _wikidata_item(place)
    if not country:
        return None
    capital_id = _current_item_id(country, "P36")
    if not capital_id:
        return None
    capital = _wikidata_by_id(capital_id)
    if not capital:
        return None
    photo = _commons_file(_claim_filename(capital, "P18")) or _commons_file(_claim_filename(country, "P41"))
    return {
        "text": random.choice((
            f"The capital of {_label(country)} is {_label(capital)}.",
            f"{_label(capital)} is the capital of {_label(country)}.",
        )),
        "commons": photo,
    }


def _current_flag(place):
    country = _wikidata_item(place)
    if not country:
        return None
    photo = _commons_file(_claim_filename(country, "P41"))
    if not photo:
        return None
    return {
        "text": random.choice((
            f"This is the flag of {_label(country)}.",
            f"The flag of {_label(country)} is shown here.",
        )),
        "commons": photo,
    }


def _wikidata_get(params):
    last_error = None
    for _attempt in range(2):
        try:
            response = requests.get(
                "https://www.wikidata.org/w/api.php",
                params=params,
                headers={"User-Agent": WIKI_USER_AGENT},
                timeout=16,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            last_error = error
    if last_error:
        return None
    return None


def _wikidata_item(term, hint=""):
    found = _wikidata_search(term, hint)
    if not found:
        return None
    return _wikidata_by_id(found)


def _wikidata_search(term, hint=""):
    payload = _wikidata_get({
        "action": "wbsearchentities",
        "search": term,
        "language": "en",
        "format": "json",
        "limit": 8,
    })
    hits = (payload or {}).get("search") or []
    skip = ("single by", "album by", "song by", "film", "painting by", "band", "television series")
    hint_words = [word for word in hint.lower().split() if len(word) > 3]
    chosen = None
    for hit in hits:
        display = hit.get("display") or {}
        desc = ((display.get("description") or {}).get("value") or "").lower()
        if any(mark in desc for mark in skip):
            continue
        if hint_words and any(word in desc for word in hint_words):
            return hit.get("id")
        chosen = chosen or hit.get("id")
    return chosen


def _wikidata_by_id(item_id):
    if not item_id:
        return None
    payload = _wikidata_get({
        "action": "wbgetentities",
        "ids": item_id,
        "props": "claims|labels|descriptions|sitelinks",
        "languages": "en",
        "sitefilter": "enwiki",
        "format": "json",
    })
    if not payload:
        return None
    return ((payload.get("entities") or {}).get(item_id))


def _label(entity):
    if not entity:
        return "that subject"
    named = ((entity.get("labels") or {}).get("en") or {}).get("value")
    if named:
        return named
    wiki = ((entity.get("sitelinks") or {}).get("enwiki") or {}).get("title")
    return wiki or "that subject"


def _current_item_id(entity, prop):
    claim = _current_claim(entity, prop)
    if not claim:
        return None
    value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
    return value.get("id")


def _claim_filename(entity, prop):
    claim = _current_claim(entity, prop)
    if not claim:
        return None
    value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
    return value if isinstance(value, str) else None


def _current_claim(entity, prop):
    today = date.today()
    fallback = None
    for claim in ((entity.get("claims") or {}).get(prop) or []):
        if claim.get("rank") == "deprecated":
            continue
        end = _qualifier_date(claim, "P582")
        start = _qualifier_date(claim, "P580")
        if end and end < today:
            continue
        if start and start > today:
            continue
        if claim.get("rank") == "preferred":
            return claim
        fallback = claim
    return fallback


def _qualifier_date(claim, prop):
    qualifiers = (claim.get("qualifiers") or {}).get(prop) or []
    if not qualifiers:
        return None
    raw = ((qualifiers[0].get("datavalue") or {}).get("value") or {}).get("time") or ""
    match = re.match(r"\+(\d{4})-(\d{2})-(\d{2})", raw)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    month = month or 1
    day = day or 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _commons_file(filename):
    if not filename:
        return None
    title = "File:" + filename
    try:
        response = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "titles": title,
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "iiurlwidth": 640,
            },
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=16,
        )
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except (requests.RequestException, ValueError):
        return None
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0] or {}
        thumb = info.get("thumburl") or (
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            + requests.utils.quote(filename)
            + "?width=640"
        )
        slug = title.replace(" ", "_")
        return {
            "thumbnail": thumb,
            "page": "https://commons.wikimedia.org/wiki/" + requests.utils.quote(slug),
            "title": filename,
            "creator": "Wikimedia Commons",
            "license": "See the Commons page",
            "license_url": "",
        }
    return None


def _meta_text(meta, key):
    raw = ((meta.get(key) or {}).get("value") or "").strip()
    text = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


_WEATHER = re.compile(
    r"(?:how(?:'s| is)\s+)?(?:what(?:'s| is)\s+)?(?:the\s+)?"
    r"(?:current\s+|today'?s\s+)?(?:weather|temperature|forecast|meteo)"
    r"(?:\s+now|\s+today|\s+tomorrow|\s+like)?\s+(?:in|at|for|of)\s+(.+?)"
    r"(?:\s+now|\s+today|\s+right\s+now|\s+tomorrow)?\s*[?.!]*$",
    re.IGNORECASE,
)
_WEATHER_LOOSE = re.compile(
    r"^(?:the\s+)?(?:weather|forecast|temperature|meteo)"
    r"(?:\s+now|\s+today|\s+tomorrow)?\s+(?:in|at|for|of\s+)?(.+?)"
    r"(?:\s+now|\s+today|\s+tomorrow)?\s*[?.!]*$",
    re.IGNORECASE,
)
_WEATHER_CODE = {
    0: ("Sunny", "sun"),
    1: ("Mostly sunny", "sun"),
    2: ("Partly cloudy", "cloud"),
    3: ("Overcast", "cloud"),
    45: ("Foggy", "fog"),
    48: ("Foggy", "fog"),
    51: ("Light drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy drizzle", "rain"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    80: ("Rain showers", "rain"),
    81: ("Rain showers", "rain"),
    82: ("Heavy showers", "rain"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm", "storm"),
    99: ("Thunderstorm", "storm"),
}


def weather_reply(message):
    """Today's weather for a city, from Open-Meteo. No account and no fee."""
    match = _WEATHER.match((message or "").strip()) or _WEATHER_LOOSE.match((message or "").strip())
    if not match:
        return None
    place = re.sub(r"\s+", " ", match.group(1)).strip(" .,")
    if not place:
        return None
    found = _weather_place(place)
    if not found:
        return {
            "text": f"I couldn't find a city called {place}.",
            "card": None,
        }
    tomorrow = bool(re.search(r"\btomorrow\b", message or "", re.IGNORECASE))
    card = _weather_card(found, tomorrow=tomorrow)
    if not card:
        return {
            "text": f"I couldn't read the weather for {found['label']} just now.",
            "card": None,
        }
    card["query"] = place
    return {
        "text": (
            f"{card['place']} is {card['temperature']}°C and {card['condition'].lower()}. "
            f"{card['reading']} {card['clock']}."
        ),
        "card": card,
    }


def _weather_get(url, params):
    """Open-Meteo drops the educational client name. A normal browser header is accepted."""
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    last = None
    for _attempt in range(2):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json() or {}
        except (requests.RequestException, ValueError) as error:
            last = error
    if last:
        return None
    return None


def _weather_place(name):
    payload = _weather_get(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": name, "count": 1, "language": "en", "format": "json"},
    )
    hits = (payload or {}).get("results") or []
    if not hits:
        return None
    hit = hits[0]
    label = hit.get("name") or name
    if hit.get("country"):
        label = f"{label}, {hit['country']}"
    return {
        "label": label,
        "latitude": hit.get("latitude"),
        "longitude": hit.get("longitude"),
        "timezone": hit.get("timezone") or "auto",
    }


def _weather_card(place, tomorrow=False):
    payload = _weather_get(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": place["timezone"],
            "current": "temperature_2m,relative_humidity_2m,weather_code",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
            "forecast_hours": 8,
        },
    )
    if not payload:
        return _weather_card_met(place, tomorrow)
    current = payload.get("current") or {}
    hourly = payload.get("hourly") or {}
    daily = payload.get("daily") or {}
    if current.get("temperature_2m") is None:
        return None
    when = current.get("time") or ""
    stamp = _weather_stamp(when, payload.get("utc_offset_seconds") or 0)
    code = int(current.get("weather_code") or 0)
    condition, icon = _sky_at(_WEATHER_CODE.get(code, ("Mixed", "cloud")), when, daily)
    hours = _weather_hours(hourly, when, daily)
    humidity = current.get("relative_humidity_2m")
    rain = hours[0]["rain"] if hours else None
    highs = (daily.get("temperature_2m_max") or [None])[0]
    lows = (daily.get("temperature_2m_min") or [None])[0]
    card = {
        "place": place["label"],
        "query": place["label"].split(",")[0],
        "date": stamp["date"],
        "clock": stamp["clock"],
        "reading": stamp["reading"],
        "temperature": round(current["temperature_2m"]),
        "condition": condition,
        "icon": icon,
        "high": None if highs is None else round(highs),
        "low": None if lows is None else round(lows),
        "rain": rain,
        "humidity": _humidity_word(humidity),
        "hours": hours[:6],
    }
    if not tomorrow:
        return card
    codes = daily.get("weather_code") or []
    highs = daily.get("temperature_2m_max") or []
    dates = daily.get("time") or []
    if len(highs) < 2 or highs[1] is None:
        return card
    next_when = f"{dates[1]}T12:00" if len(dates) > 1 else when
    next_code = int(codes[1] or 0) if len(codes) > 1 else code
    next_condition, next_icon = _sky_at(
        _WEATHER_CODE.get(next_code, ("Mixed", "cloud")),
        next_when,
        daily,
    )
    card["temperature"] = round(highs[1])
    card["condition"] = next_condition
    card["icon"] = next_icon
    card["reading"] = "Tomorrow"
    try:
        card["clock"] = datetime.fromisoformat(dates[1]).strftime("%#d %B %Y" if os.name == "nt" else "%-d %B %Y")
    except (ValueError, IndexError, TypeError):
        card["clock"] = dates[1] if len(dates) > 1 else card["clock"]
    return card


def _met_symbol(code):
    text = (code or "").lower()
    night = "night" in text
    if "thunder" in text:
        return "Thunderstorm", "storm"
    if "snow" in text or "sleet" in text:
        return "Snow", "snow"
    if "rain" in text or "drizzle" in text:
        return "Rain", "rain"
    if "fog" in text:
        return "Foggy", "fog"
    if "partly" in text:
        return ("Mostly clear" if night else "Partly cloudy"), ("moon" if night else "cloud")
    if "cloud" in text:
        return "Overcast", "cloud"
    if "clear" in text or "fair" in text:
        return ("Clear" if night else "Sunny"), ("moon" if night else "sun")
    return "Mixed", "cloud"


def _weather_card_met(place, tomorrow=False):
    """Used when Open-Meteo will not answer the hosted server."""
    try:
        response = requests.get(
            "https://api.met.no/weatherapi/locationforecast/2.0/compact",
            params={"lat": place["latitude"], "lon": place["longitude"]},
            headers={"User-Agent": "e-Chat weather (https://e-chatai.onrender.com/)"},
            timeout=15,
        )
        response.raise_for_status()
        series = ((response.json() or {}).get("properties") or {}).get("timeseries") or []
    except (requests.RequestException, ValueError):
        return None
    if not series:
        return None
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(place.get("timezone") or "UTC")
    except Exception:
        zone = timezone.utc

    def local(stamp):
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return moment.astimezone(zone).replace(tzinfo=None)

    first = series[0]
    details = ((first.get("data") or {}).get("instant") or {}).get("details") or {}
    if details.get("air_temperature") is None:
        return None
    moment = local(first["time"])
    symbol = (((first.get("data") or {}).get("next_1_hours") or {}).get("summary") or {}).get("symbol_code")
    condition, icon = _met_symbol(symbol)
    temps = []
    hours = []
    for item in series[:24]:
        item_details = ((item.get("data") or {}).get("instant") or {}).get("details") or {}
        if item_details.get("air_temperature") is None:
            continue
        temps.append(item_details["air_temperature"])
        if len(hours) < 6:
            when = local(item["time"])
            hour = when.strftime("%I").lstrip("0") or "12"
            item_symbol = (((item.get("data") or {}).get("next_1_hours") or {}).get("summary") or {}).get("symbol_code")
            _condition, item_icon = _met_symbol(item_symbol or symbol)
            hours.append({
                "time": f"{hour} {when.strftime('%p')}",
                "temperature": round(item_details["air_temperature"]),
                "rain": None,
                "icon": item_icon,
            })
    hour = moment.strftime("%I").lstrip("0") or "12"
    card = {
        "place": place["label"],
        "query": place["label"].split(",")[0],
        "date": moment.strftime("%A, %-d %B %Y") if os.name != "nt" else moment.strftime("%A, %#d %B %Y"),
        "clock": f"{hour}:{moment.strftime('%M')} {moment.strftime('%p')}",
        "reading": "Live",
        "temperature": round(details["air_temperature"]),
        "condition": condition,
        "icon": icon,
        "high": round(max(temps)) if temps else None,
        "low": round(min(temps)) if temps else None,
        "rain": None,
        "humidity": _humidity_word(details.get("relative_humidity")),
        "hours": hours,
    }
    if not tomorrow:
        return card
    tomorrow_temps = []
    for item in series:
        when = local(item["time"])
        if when.date() <= moment.date():
            continue
        item_details = ((item.get("data") or {}).get("instant") or {}).get("details") or {}
        if item_details.get("air_temperature") is not None:
            tomorrow_temps.append((when, item_details["air_temperature"], item))
        if len(tomorrow_temps) >= 8:
            break
    if not tomorrow_temps:
        return card
    when, temperature, item = max(tomorrow_temps, key=lambda row: row[1])
    symbol = (((item.get("data") or {}).get("next_1_hours") or {}).get("summary") or {}).get("symbol_code")
    condition, icon = _met_symbol(symbol)
    card["temperature"] = round(temperature)
    card["condition"] = condition
    card["icon"] = icon
    card["reading"] = "Tomorrow"
    card["clock"] = when.strftime("%#d %B %Y" if os.name == "nt" else "%-d %B %Y")
    return card


def _sky_at(named, when, daily):
    condition, icon = named
    try:
        moment = datetime.fromisoformat(when)
    except ValueError:
        return condition, icon
    if not _is_night(moment, daily or {}):
        return condition, icon
    if condition == "Sunny":
        condition = "Clear"
    elif condition == "Mostly sunny":
        condition = "Mostly clear"
    if icon == "sun":
        icon = "moon"
    return condition, icon


def _is_night(moment, daily):
    day = moment.date().isoformat()
    dates = daily.get("time") or []
    rises = daily.get("sunrise") or []
    sets = daily.get("sunset") or []
    for index, stamp in enumerate(dates):
        if str(stamp)[:10] != day:
            continue
        try:
            rise = datetime.fromisoformat(rises[index])
            sunset = datetime.fromisoformat(sets[index])
        except (IndexError, ValueError, TypeError):
            break
        return moment < rise or moment >= sunset
    return moment.hour >= 19 or moment.hour < 6


def _weather_stamp(value, offset_seconds=0):
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return {"date": "", "clock": "", "reading": "Last reading"}
    hour = moment.strftime("%I").lstrip("0") or "12"
    local_now = datetime.now(timezone.utc) + timedelta(seconds=int(offset_seconds or 0))
    age = local_now.replace(tzinfo=None) - moment.replace(tzinfo=None)
    # Open-Meteo publishes the current hour. That hour is the live reading.
    reading = "Live" if timedelta(0) <= age < timedelta(hours=1) else "Last reading"
    return {
        "date": moment.strftime("%A, %-d %B %Y") if os.name != "nt" else moment.strftime("%A, %#d %B %Y"),
        "clock": f"{hour}:{moment.strftime('%M')} {moment.strftime('%p')}",
        "reading": reading,
    }


def _weather_hours(hourly, current_time, daily):
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    rains = hourly.get("precipitation_probability") or []
    codes = hourly.get("weather_code") or []
    start = 0
    if current_time in times:
        start = times.index(current_time)
    rows = []
    for index in range(start, min(start + 6, len(times))):
        try:
            moment = datetime.fromisoformat(times[index])
            hour = moment.strftime("%I").lstrip("0") or "12"
            label = f"{hour} {moment.strftime('%p')}"
        except ValueError:
            label = ""
        code = int(codes[index] or 0) if index < len(codes) else 0
        condition, icon = _sky_at(
            _WEATHER_CODE.get(code, ("Mixed", "cloud")),
            times[index],
            daily,
        )
        rows.append({
            "time": label,
            "temperature": None if index >= len(temps) or temps[index] is None else round(temps[index]),
            "rain": None if index >= len(rains) or rains[index] is None else round(rains[index]),
            "icon": icon,
        })
    return rows


def _humidity_word(value):
    if value is None:
        return ""
    if value < 40:
        return "Dry"
    if value < 60:
        return "Mild"
    if value < 80:
        return "Humid"
    return "Very humid"


def wikipedia_definition(term, question=""):
    """Wikipedia article text, with a plain dictionary line for one word."""
    subject = (term or "").strip()
    if not subject:
        return None
    if subject.lower() in {"ai", "a.i.", "a.i"}:
        subject = "Artificial intelligence"
    direct = _resolved_summary(subject)
    if not direct:
        head = re.sub(
            r"\s+in\s+(?:math|mathematics|statistics|science|programming)\b.*$",
            "",
            subject,
            flags=re.IGNORECASE,
        ).strip()
        if head and head.lower() != subject.lower():
            direct = _resolved_summary(head)
    if not direct:
        return None
    line = _plain_dictionary(subject)
    if line:
        return direct + "\n\n" + line
    return direct


def _plain_dictionary(term):
    """One dictionary sentence, written as ordinary text."""
    if not term or " " in term.strip():
        return ""
    entry = wiktionary_entry(term)
    if not entry or not entry.get("senses"):
        return ""
    sense = entry["senses"][0]
    part = sense.get("part") or ""
    label = f" ({part})" if part else ""
    return f"Dictionary{label}: {sense['text']}"


def _resolved_summary(subject):
    summary = _wikipedia_plain_summary(subject)
    if summary and not _is_disambiguation(summary):
        return summary
    if not summary:
        return None
    for title in (_referred_title(summary), _sense_title(summary), _search_title(subject)):
        if not title or title.lower() == subject.lower():
            continue
        better = _wikipedia_plain_summary(title)
        if better and not _is_disambiguation(better):
            return better
    title = _disambiguation_target(subject)
    if title and title.lower() != subject.lower():
        better = _wikipedia_plain_summary(title)
        if better and not _is_disambiguation(better):
            return better
    return None


def _is_disambiguation(summary):
    head = (summary or "").lower()
    return "may refer to" in head or "may also refer to" in head


def _sense_title(summary):
    """First real topic named by a disambiguation intro."""
    match = re.search(
        r"may (?:also )?refer to (?:a |an |the )?(.+)",
        summary or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    phrase = re.split(r"\bor\b|,", match.group(1))[0]
    phrase = re.sub(r"^(?:a|an|the)\s+", "", phrase.strip(" ."))
    words = phrase.split()
    if words and words[-1].lower() in {"intelligence", "selfishness"}:
        return words[-1]
    return phrase or None


def _search_title(term):
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": term,
                "srlimit": 5,
                "format": "json",
            },
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=16,
        )
        response.raise_for_status()
        hits = (response.json().get("query") or {}).get("search") or []
    except (requests.RequestException, ValueError):
        return None
    for hit in hits:
        title = hit.get("title") or ""
        if title and "disambiguation" not in title.lower() and title.lower() != term.lower():
            return title
    return None


def _referred_title(summary):
    match = re.search(
        r"commonly refers to ([^,\n.]+)",
        summary or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip()


def _wikipedia_plain_summary(title):
    """Article intro through the public Wikipedia API. Needs only requests."""
    try:
        response = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + requests.utils.quote(title.replace(" ", "_")),
            headers={"User-Agent": WIKI_USER_AGENT, "Accept": "application/json"},
            timeout=16,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json() or {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Wikipedia summary failed: %s", type(exc).__name__)
        return None
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json() or {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Wikipedia summary failed: %s", type(exc).__name__)
        return None
    if payload.get("type") == "disambiguation":
        extract = (payload.get("extract") or "").strip()
        return extract or None
    extract = re.sub(r"\s+", " ", payload.get("extract") or "").strip()
    if len(extract) < 40:
        return None
    return f"- {_trim(extract, 700)}"


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


def wiktionary_entry(word):
    """The dictionary line for one word, kept apart from a Wikipedia article."""
    term = (word or "").strip()
    if not term or " " in term:
        return None
    try:
        response = requests.get(
            "https://en.wiktionary.org/api/rest_v1/page/definition/"
            + requests.utils.quote(term),
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=8,
        )
        if not response.ok:
            return None
        senses = []
        for block in (response.json() or {}).get("en") or []:
            part = (block.get("partOfSpeech") or "").strip()
            for item in block.get("definitions") or []:
                text = re.sub(r"<[^>]+>", "", item.get("definition") or "")
                text = re.sub(r"\s+", " ", text).strip()
                if not text:
                    continue
                senses.append({"part": part, "text": text})
                if len(senses) == 3:
                    break
            if len(senses) == 3:
                break
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Wiktionary request failed: %s", type(exc).__name__)
        return None
    if not senses:
        return None
    lines = [term]
    for sense in senses:
        label = f"({sense['part']}) " if sense["part"] else ""
        lines.append(label + sense["text"])
    return {"word": term, "senses": senses, "text": "\n".join(lines)}


def _wiktionary_definition(word):
    entry = wiktionary_entry(word)
    return entry["text"] if entry else None


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
            timeout=16,
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
            timeout=16,
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


_LANG = {
    "english": "en", "french": "fr", "francais": "fr", "français": "fr",
    "spanish": "es", "espanol": "es", "español": "es",
    "swahili": "sw", "kiswahili": "sw",
    "arabic": "ar", "kinyarwanda": "rw", "german": "de", "portuguese": "pt",
    "italian": "it", "chinese": "zh", "japanese": "ja", "korean": "ko",
    "hindi": "hi", "lingala": "ln", "luganda": "lg", "kirundi": "rn",
    "dutch": "nl", "russian": "ru", "turkish": "tr",
}
_LANG_LABEL = {
    "en": "English", "fr": "French", "es": "Spanish", "sw": "Swahili",
    "ar": "Arabic", "rw": "Kinyarwanda", "de": "German", "pt": "Portuguese",
    "it": "Italian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
    "hi": "Hindi", "ln": "Lingala", "lg": "Luganda", "rn": "Kirundi",
    "nl": "Dutch", "ru": "Russian", "tr": "Turkish",
}
_QUOTED_SENTENCE = re.compile(
    r"^(?:please\s+)?(?:translate|what(?:'s| is))\s+[\"“](.+?)[\"”]\s+(?:in|into|to)\s+([A-Za-z][A-Za-z \-]+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_TRANSLATE = re.compile(
    r"^(?:please\s+)?translate\s+(.+?)\s+(?:in|into|to)\s+([A-Za-z][A-Za-z \-]+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_HOW_SAY = re.compile(
    r"^(?:please\s+)?how\s+do\s+you\s+say\s+(.+?)\s+(?:in|into|to)\s+([A-Za-z][A-Za-z \-]+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_WHAT_IN_LANG = re.compile(
    r"^what(?:'s| is)\s+(.+?)\s+in\s+([A-Za-z][A-Za-z \-]+?)\s*[?.!]*$",
    re.IGNORECASE,
)


def translate_reply(message):
    """Translate a word, expression, or passage into only the languages asked for."""
    text = re.sub(r"\s+", " ", (message or "")).strip()
    text = (
        text.replace("“", "\"")
        .replace("”", "\"")
        .replace("‘", "'")
        .replace("’", "'")
    )
    parsed = _parse_translation_request(text)
    if not parsed:
        return None
    phrase, codes, explain = parsed
    if not phrase:
        return None
    if explain and not codes:
        return _meaning_reply(phrase)
    if not codes:
        return None
    kind = _translation_kind(phrase)
    if kind == "paragraph":
        return _paragraph_translation(phrase, codes)
    if kind == "sentence":
        return _sentence_translation(phrase, codes)
    return _word_translation(phrase, codes)


def _parse_translation_request(text):
    meaning = re.match(
        r"^what\s+does\s+(.+?)\s+mean(?:\s+(?:in|into|to)\s+(.+))?\s*[?.!]*$",
        text,
        re.IGNORECASE,
    )
    if meaning:
        phrase = _unwrap_quotes(meaning.group(1).strip(" .\""))
        return phrase, _language_codes(meaning.group(2) or ""), True
    lead = re.match(
        r"^(?:please\s+)?(?:how\s+do\s+you\s+say|translate|what(?:'s| is))\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if not lead:
        return None
    body = lead.group(1).strip()
    names = "|".join(re.escape(name) for name in sorted(_LANG, key=len, reverse=True))
    found = re.search(
        rf"\s+(?:in|into|to)\s+((?:every|all)(?:\s+languages?)?|(?:{names})(?:\s*(?:,|and|&)\s*(?:{names}))*)\s*[?.!]*$",
        body,
        re.IGNORECASE,
    )
    if not found:
        return None
    phrase = _unwrap_quotes(body[:found.start()].strip(" .\""))
    return phrase, _language_codes(found.group(1)), False


def _language_codes(tail):
    tail = re.sub(r"\s+", " ", (tail or "")).strip(" .?").lower()
    if not tail:
        return []
    if re.fullmatch(r"(?:every|all)(?:\s+languages?)?", tail):
        return list(_LANG_LABEL)
    codes = []
    for name in re.split(r"\s*(?:,|&|\band\b)\s*", tail):
        code = _LANG.get(name.strip())
        if code and code not in codes:
            codes.append(code)
    return codes


def _language_label(code):
    return _LANG_LABEL.get(code, code)


def _marked(label, value):
    return f"*{label}:* {value}"


def _translation_kind(phrase):
    """A word stays a word. A clause or idiom is a sentence. A passage is a paragraph."""
    words = _sentence_words(phrase)
    stops = len(re.findall(r"[.!?]", phrase))
    if "\n" in phrase or len(words) >= 25 or stops >= 2:
        return "paragraph"
    clause = re.search(
        r"\b(?:i|i'm|im|don't|dont|do not|he|she|we|they|it|there)\b",
        phrase,
        re.IGNORECASE,
    )
    if len(words) >= 3 or (clause and len(words) >= 2):
        return "sentence"
    return "word"


def _word_translation(phrase, codes):
    lines = []
    card = None
    for code in codes:
        translated = _google_translate(phrase, code)
        label = _language_label(code)
        if not translated:
            lines.append(_marked(label, "I couldn't confirm this."))
            continue
        shown = translated
        lines.append(_marked(label, shown))
        if card is None:
            card = _word_card(phrase, code, translated)
    result = {"text": "\n".join(lines)}
    if card:
        result["card"] = card
    return result


def _word_card(phrase, code, translated):
    entry = wiktionary_entry(phrase) if " " not in phrase.strip() else None
    parts = [(sense.get("part") or "").lower() for sense in (entry.get("senses") or [])] if entry else []
    verb = _is_infinitive(translated, code)
    if verb:
        role = "verb"
    elif "adjective" in parts:
        role = "adjective"
    elif parts and parts[0] != "verb":
        role = parts[0]
    else:
        role = "word"
    rows = _present_rows(code, translated, phrase) if verb else []
    return {
        "language": _language_label(code).lower(),
        "word": translated,
        "kind": "verb" if verb else (role or "word"),
        "rows": rows,
        "examples": _usage_examples(code, translated, phrase, verb, rows, role),
    }


def _meaning_reply(phrase):
    english = _natural_english(phrase)
    return {"text": "\n".join([
        _marked("Expression", phrase),
        _marked("Meaning", english.rstrip(".")),
    ])}


def _paragraph_translation(phrase, codes):
    """The whole passage, in each language asked for, with its breaks kept."""
    lines = []
    for code in codes:
        translated = _translate_passage(phrase, code)
        label = _language_label(code)
        lines.append(_marked(label, translated or "I couldn't confirm this."))
    return {"text": "\n\n".join(lines)}


def _translate_passage(phrase, code):
    pieces = re.split(r"(\n+)", phrase)
    rendered = []
    for piece in pieces:
        if not piece.strip():
            rendered.append(piece)
            continue
        rendered.append(_translate_long(piece, code))
    return "".join(rendered).strip()


def _translate_long(text, code):
    sentences = re.findall(r".+?(?:[.!?]+(?:\s+|$)|$)", text, re.DOTALL) or [text]
    chunks = []
    buf = ""
    for sentence in sentences:
        if buf and len(buf) + len(sentence) > 400:
            chunks.append(buf)
            buf = sentence
        else:
            buf += sentence
    if buf:
        chunks.append(buf)
    parts = []
    for chunk in chunks:
        translated = _google_text(chunk.strip(), code, "auto") or _google_text(chunk.strip(), code, "en")
        parts.append(translated or chunk.strip())
    return " ".join(part.strip() for part in parts if part.strip())


def _is_verb(phrase):
    if " " in phrase.strip():
        return False
    entry = wiktionary_entry(phrase)
    if not entry:
        return False
    return any((sense.get("part") or "").lower() == "verb" for sense in entry.get("senses") or [])


_PRESENT_LABELS = {
    "fr": (
        ("Je", "I"),
        ("Tu", "You (informal)"),
        ("Il / Elle / On", "He / She / One"),
        ("Nous", "We"),
        ("Vous", "You (formal / plural)"),
        ("Ils / Elles", "They"),
    ),
    "es": (
        ("Yo", "I"),
        ("Tú", "You (informal)"),
        ("Él / Ella / Usted", "He / She / You"),
        ("Nosotros", "We"),
        ("Vosotros", "You (plural, Spain)"),
        ("Ellos / Ustedes", "They / You"),
    ),
}


def _present_rows(code, infinitive, english):
    forms = _present_forms(code, infinitive)
    if len(forms) != 6:
        return []
    gloss = _english_forms(english)
    labels = _PRESENT_LABELS[code]
    rows = []
    for index, ((pronoun, who), form) in enumerate(zip(labels, forms)):
        if code == "fr" and pronoun == "Je" and form[:1].lower() in "aàâäeéèêëiîïoôöuùûü":
            pronoun = "J'"
        rows.append({"pronoun": pronoun, "form": form, "english": f"{who} {gloss[index]}"})
    return rows


def _present_forms(code, infinitive):
    """Present-tense forms from the language's conjugation page. No guessed stems."""
    verb = (infinitive or "").strip().split()[0].lower()
    if not verb or code not in _PRESENT_LABELS:
        return []
    key = (code, verb)
    if key in _CONJ_CACHE:
        return _CONJ_CACHE[key]
    try:
        forms = _french_page(verb) if code == "fr" else _spanish_page(verb)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        forms = []
    _CONJ_CACHE[key] = forms
    return forms


_CONJ_CACHE = {}
_COMMAND_CACHE = {}


def _wiki_html(host, title):
    response = requests.get(
        f"https://{host}/w/api.php",
        params={"action": "parse", "page": title, "prop": "text", "format": "json"},
        headers={"User-Agent": WIKI_USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["parse"]["text"]["*"]


def _french_page(verb):
    page = _wiki_html("fr.wiktionary.org", f"Conjugaison:français/{verb}")
    start = page.find('id="Indicatif"')
    if start < 0:
        return []
    section = page[start:]
    present = section.find(">Présent</th>")
    if present < 0:
        return []
    end = section.find(">Imparfait</th>", present)
    chunk = section[present:end if end > 0 else present + 5000]
    pairs = re.findall(
        r'align="right">.*?</td>\s*<td[^>]*align="left">(?:\s*<[^>]+>)*\s*([^<]+)',
        chunk,
        re.DOTALL,
    )
    forms = []
    for form in pairs:
        form = html.unescape(form).replace("\xa0", " ").strip(" \\")
        if form and not form.startswith("\\"):
            forms.append(form)
        if len(forms) == 6:
            break
    mark = page.lower().find('impératif" class="mw-html-heading"')
    command = ""
    if mark >= 0:
        hit = re.search(
            r'align="left">(?:\s*<[^>]+>)*\s*([^<\\]+)',
            page[mark:mark + 2500],
        )
        if hit:
            command = html.unescape(hit.group(1)).replace("\xa0", " ").strip(" \\")
    _COMMAND_CACHE[("fr", verb)] = command
    return forms if len(forms) == 6 else []


def _spanish_page(verb):
    page = _wiki_html("en.wiktionary.org", verb)
    start = page.find('id="Spanish"')
    if start < 0:
        return []
    section = page[start:]
    indicative = section.lower().find("indicative")
    if indicative < 0:
        return []
    block = section[indicative:]
    present = re.search(r">\s*present\s*<", block, re.IGNORECASE)
    imperfect = re.search(r">\s*imperfect\s*<", block, re.IGNORECASE)
    if not present or not imperfect:
        return []
    cell = block[present.end():imperfect.start()]
    forms = []
    for piece in re.split(r"</td>", cell):
        match = re.search(r'lang="es"[^>]*>(?:\s*<a[^>]*>)?([^<]+)', piece)
        if not match:
            continue
        form = html.unescape(match.group(1)).strip()
        if form:
            forms.append(form)
        if len(forms) == 6:
            break
    affirmative = re.search(r">affirmative</span>", section, re.IGNORECASE)
    command = ""
    if affirmative:
        after = section[affirmative.end():affirmative.end() + 1600]
        for piece in re.split(r"</td>", after):
            match = re.search(r'lang="es"[^>]*>(?:\s*<a[^>]*>)?([^<]+)', piece)
            if not match:
                continue
            command = html.unescape(match.group(1)).strip()
            if command:
                break
    _COMMAND_CACHE[("es", verb)] = command
    return forms if len(forms) == 6 else []


def _french_command(verb):
    _present_forms("fr", verb)
    return _COMMAND_CACHE.get(("fr", verb), "")


def _spanish_command(verb):
    _present_forms("es", verb)
    return _COMMAND_CACHE.get(("es", verb), "")


def _is_infinitive(word, code):
    text = (word or "").strip().lower()
    if " " in text or code not in {"fr", "es"}:
        return False
    if code == "fr":
        return text.endswith(("er", "ir", "re", "oir"))
    return text.endswith(("ar", "er", "ir"))


def _english_forms(word):
    base = word.lower().removeprefix("to ").strip()
    third = base + ("es" if base.endswith(("s", "sh", "ch", "x", "o")) else "s")
    return (base, base, third, base, base, base)


def _usage_examples(code, infinitive, phrase, verb, rows, role=""):
    real = _tatoeba_examples(phrase, code)
    if real:
        return real
    word = (infinitive or "").strip()
    if verb and word:
        gift = _google_translate("a gift", code)
        answer = _google_translate("an answer", code)
        head = word[:1].upper() + word[1:]
        examples = []
        if gift:
            examples.append({"phrase": f"{head} {gift}", "meaning": f"To {phrase} a gift"})
        if answer:
            examples.append({"phrase": f"{head} {answer}", "meaning": f"To {phrase} an answer"})
        if code == "fr" and rows:
            command = _french_command(word.lower()) or rows[2]["form"]
            examples.append({
                "phrase": f"{command[:1].upper() + command[1:]}-moi ça !",
                "meaning": f"{phrase[:1].upper() + phrase[1:]} me that!",
            })
        elif code == "es" and rows:
            command = _spanish_command(word.lower()) or rows[2]["form"]
            examples.append({
                "phrase": f"¡{command[:1].upper() + command[1:]}me eso!",
                "meaning": f"{phrase[:1].upper() + phrase[1:]} me that!",
            })
        return examples
    if " " in (phrase or "").strip() or " " in (infinitive or "").strip():
        return []
    if role != "adjective":
        return []
    examples = []
    for prompt in (f"she is {phrase}", f"a {phrase} person"):
        line = _google_translate(prompt, code)
        if line and _plain_letters(line) != _plain_letters(prompt):
            examples.append({"phrase": line, "meaning": prompt[:1].upper() + prompt[1:]})
    return examples


_TATOEBA = {
    "en": "eng", "fr": "fra", "es": "spa", "sw": "swh", "ar": "ara",
    "rw": "kin", "de": "deu", "pt": "por", "it": "ita", "zh": "cmn",
    "ja": "jpn", "ko": "kor", "hi": "hin", "ln": "lin", "lg": "lug",
    "rn": "run", "nl": "nld", "ru": "rus", "tr": "tur",
}


def _example_uses(sentence, query):
    """An example counts only when the sentence actually uses the looked-up words."""
    text = re.sub(r"[^a-z0-9]+", " ", (sentence or "").lower()).strip()
    wanted = re.sub(r"[^a-z0-9]+", " ", (query or "").lower()).strip()
    if not text or not wanted:
        return False
    if " " in wanted:
        return wanted in text
    return bool(re.search(rf"(^| ){re.escape(wanted)}( |$)", text))


def _tatoeba_examples(phrase, code, limit=3):
    """Real sentence pairs from Tatoeba for the common-examples list."""
    target = _TATOEBA.get(code)
    query = (phrase or "").strip()
    if not target or not query:
        return []
    try:
        response = requests.get(
            "https://api.tatoeba.org/unstable/sentences",
            params={
                "lang": "eng",
                "q": query,
                "showtrans": "all",
                "sort": "relevance",
                "limit": 20,
            },
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
        results = response.json().get("data") or []
    except (requests.RequestException, ValueError, TypeError):
        return []
    examples = []
    for item in results:
        english = (item.get("text") or "").strip()
        if not english or not _example_uses(english, query):
            continue
        chosen = ""
        direct = ""
        for sentence in item.get("translations") or []:
            if not isinstance(sentence, dict) or sentence.get("lang") != target:
                continue
            text = (sentence.get("text") or "").strip()
            if not text:
                continue
            if sentence.get("is_direct"):
                direct = text
                break
            if not chosen:
                chosen = text
        line = direct or chosen
        if line:
            examples.append({"phrase": line, "meaning": english})
        if len(examples) >= limit:
            break
    return examples


def _unwrap_quotes(phrase):
    text = (phrase or "").strip().replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text.strip(" \"'`")


def _sentence_words(phrase):
    return [word for word in re.split(r"\s+", phrase.strip()) if word]


def _sentence_translation(phrase, codes):
    """The sentence as a whole, in each language the user named."""
    english = _sentence_meaning(phrase)
    lines = []
    result_card_word = ""
    for code in codes:
        label = _language_label(code)
        if code == "en":
            shown = english
        else:
            shown = _google_text(english.rstrip(".!?"), code, "en") or ""
        if not shown or _plain_letters(shown) == _plain_letters(phrase):
            lines.append(_marked(label, "I couldn't confirm this."))
            continue
        shown = _sentence_case(shown).rstrip(".")
        lines.append(_marked(label, shown))
        if not result_card_word:
            result_card_word = shown
    result = {"text": "\n".join(lines)}
    if result_card_word:
        result["card"] = {
            "language": _language_label(codes[0]).lower() if codes else "",
            "word": result_card_word,
            "kind": "sentence",
            "rows": [],
            "examples": _tatoeba_examples(english.rstrip(".!?"), codes[0] if codes else "")[:3],
        }
    return result


def _sentence_meaning(phrase):
    """English meaning of a sentence, using the language whose wording matches."""
    text, detected = _google_pair(phrase, "en", "auto")
    best_text = text if text and _plain_letters(text) != _plain_letters(phrase) else ""
    best_hits = 0
    if best_text and detected:
        best_hits = _stem_hits(phrase, _google_text(text, detected, "en"))

    def one(code):
        if code == "en" or code == detected:
            return "", 0
        english = _google_text(phrase, "en", code)
        if not english or _plain_letters(english) == _plain_letters(phrase):
            return "", 0
        return english, _stem_hits(phrase, _google_text(english, code, "en"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        for english, hits in pool.map(one, list(_LANG_LABEL)):
            if hits > best_hits:
                best_text, best_hits = english, hits
    if best_hits >= 2 and best_text:
        return _sentence_case(best_text)
    return _sentence_case(best_text or phrase)


def _natural_english(phrase):
    """The meaning in English. A same-language idiom is checked through French and back."""
    direct = _google_text(phrase, "en", "auto")
    if direct and _plain_letters(direct) != _plain_letters(phrase):
        return _sentence_case(direct)
    via = _google_text(phrase, "fr", "en")
    back = _google_text(via, "en", "fr") if via else ""
    if back and _plain_letters(back) != _plain_letters(phrase):
        return _sentence_case(back)
    return _sentence_case(direct or phrase)


def _sentence_case(text):
    text = (text or "").strip()
    if not text:
        return ""
    text = text[:1].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def _every_language(meaning, skip):
    codes = []
    seen = set()
    for lang_code in _LANG_LABEL:
        if lang_code == skip or lang_code in seen:
            continue
        seen.add(lang_code)
        codes.append(lang_code)

    def one(lang_code):
        text = _google_translate(meaning.rstrip(".!?"), lang_code)
        return lang_code, text

    lines = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for lang_code, text in pool.map(one, codes):
            if text:
                lines.append({
                    "phrase": _sentence_case(text),
                    "meaning": _LANG_LABEL.get(lang_code, lang_code),
                })
    lines.sort(key=lambda item: item["meaning"])
    return lines


def _plain_letters(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _sense_reading(phrase, words, target):
    """Read any quoted sentence in the language it is actually written in."""
    payload = _google_payload(phrase, "auto", "en")
    detected, confidence, meaning = _payload_reading(payload)
    if detected and confidence >= 0.55:
        if detected == "en" or _plain_letters(meaning) == _plain_letters(phrase):
            return "en", phrase, words
        reading = _locked_reading(phrase, words, detected, "en")
        if reading and _plain_letters(reading[0]) != _plain_letters(phrase):
            return detected, reading[0], reading[1]
        if meaning:
            return detected, meaning, _word_glosses(words, detected, "en")
    candidates = []
    seen = set()
    for source in [detected, *_LANG.values()]:
        if not source or source == target or source in seen:
            continue
        seen.add(source)
        candidates.append(source)
    readings = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for source, result in zip(candidates, pool.map(lambda source: _locked_reading(phrase, words, source, target), candidates)):
            if result:
                readings.append((source, result))
    ranked = []
    for source, (sentence, glosses) in readings:
        if _plain_letters(sentence) == _plain_letters(phrase):
            continue
        changed = sum(
            1 for gloss, word in zip(glosses, words)
            if _plain_letters(gloss) != _plain_letters(word)
        )
        if changed == 0:
            continue
        score = _sense_score(sentence, glosses, words) + changed
        if source == detected:
            score += 0.5
        ranked.append((score, source, sentence, glosses))
    best = None
    for score, source, sentence, glosses in ranked:
        usual = _google_translate(sentence, source)
        total = score + _stem_hits(phrase, usual) * 3
        if best is None or total > best[0]:
            best = (total, source, sentence, glosses, usual)
    if best:
        _source, sentence, glosses, usual = best[1], best[2], best[3], best[4]
        glosses = _fill_unchanged(glosses, words, sentence, _source)
        return _source, sentence, glosses
    return detected, meaning, _word_glosses(words, detected, target) if detected else words


def _locked_reading(phrase, words, source, target):
    marked = "\n".join(f"### {part}" for part in [phrase, *words])
    payload = _google_payload(marked, source, target)
    if not payload:
        return None
    text = "\n".join(_payload_lines(payload))
    parts = [part.strip() for part in text.split("###") if part.strip()]
    if len(parts) < len(words) + 1:
        return None
    return parts[0], parts[1:1 + len(words)]


def _word_glosses(words, source, target):
    payload = _google_payload("\n".join(words), source, target)
    lines = _payload_lines(payload)
    if len(lines) < len(words):
        return words
    return lines[-len(words):]


_SENSE_SKIP = {
    "a", "an", "the", "to", "and", "or", "of", "in", "on", "for", "me", "i",
    "let", "there", "that", "also", "with", "my", "your",
}


def _stem_hits(left, right):
    left_words = _sentence_words(left or "")
    right_words = _sentence_words(right or "")
    hits = 0
    used = set()
    for word in left_words:
        stem = _plain_letters(word)[:4]
        if len(stem) < 3:
            continue
        for other in right_words:
            if other in used:
                continue
            plain = _plain_letters(other)
            if stem in plain or plain[:4] == stem:
                used.add(other)
                hits += 1
                break
    return hits


def _fill_unchanged(glosses, words, sentence, source):
    glosses = list(glosses)
    unexplained = []
    for word in _content_words(sentence):
        if not any(_stem_hits(word, gloss) for gloss in glosses):
            unexplained.append(word)
    for index, (gloss, word) in enumerate(zip(glosses, words)):
        if _plain_letters(gloss) != _plain_letters(word):
            continue
        for extra in list(unexplained):
            native = _google_translate(extra, source)
            if native and _stem_hits(word, native):
                glosses[index] = extra
                unexplained.remove(extra)
                break
    return glosses


def _sense_score(sentence, glosses, words):
    sentence_words = _content_words(sentence)
    gloss_words = _content_words(" ".join(glosses))
    used = set()
    overlap = 0
    for word in sentence_words:
        for other in gloss_words:
            if other in used:
                continue
            if word == other or word.startswith(other[:4]) or other.startswith(word[:4]):
                if min(len(word), len(other)) >= 3:
                    used.add(other)
                    overlap += 1
                    break
    unchanged = 0
    for gloss, source in zip(glosses, words):
        if _plain_letters(gloss) == _plain_letters(source):
            unchanged += 1
    return overlap * 2 - unchanged


def _content_words(text):
    return [
        word for word in re.findall(r"[a-z']+", (text or "").lower())
        if word not in _SENSE_SKIP and len(word) > 1
    ]


def _usual_spelling(meaning, source):
    if not source:
        return ""
    return _google_translate(meaning.rstrip(".!?"), source)


def _google_payload(phrase, source, target):
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": source or "auto", "tl": target, "dt": "t", "q": phrase[:500]},
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        return None
    return payload


def _payload_lines(payload):
    parts = []
    for block in payload[0]:
        if isinstance(block, list) and block and isinstance(block[0], str):
            parts.append(block[0])
    return [line.strip() for line in "".join(parts).splitlines() if line.strip()]


def _payload_reading(payload):
    if not payload:
        return "", 0, ""
    lines = _payload_lines(payload)
    detected = payload[2] if len(payload) > 2 and isinstance(payload[2], str) else ""
    confidence = payload[6] if len(payload) > 6 and isinstance(payload[6], (int, float)) else 0
    return detected, confidence, lines[0] if lines else ""


def _google_translate(phrase, code, source="auto"):
    """One word or sentence. A single word can fall back to Wiktionary."""
    text = _google_text(phrase, code, source)
    if text and text.lower() != (phrase or "").strip().lower():
        return text
    if source == "auto":
        forced = _google_text(phrase, code, "en")
        if forced and forced.lower() != (phrase or "").strip().lower():
            return forced
    if phrase and " " not in phrase.strip():
        wiki = _wiktionary_word(phrase, code)
        if wiki:
            return wiki
    return text or ""


def _google_text(phrase, code, source):
    """The main Google translation. The dictionary client is tried before the other endpoint."""
    text, _detected = _google_pair(phrase, code, source)
    return text


def _google_pair(phrase, code, source):
    sl = "auto" if not source or source == "auto" else source
    try:
        response = requests.get(
            "https://clients5.google.com/translate_a/t",
            params={"client": "dict-chrome-ex", "sl": sl, "tl": code, "q": (phrase or "")[:500]},
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=12,
        )
        if response.ok:
            text, detected = _clients5_text(response.json())
            if text:
                return text, detected
    except (requests.RequestException, ValueError, TypeError):
        pass
    payload = _google_payload(phrase, source, code)
    lines = _payload_lines(payload) if payload else []
    detected = payload[2] if payload and len(payload) > 2 and isinstance(payload[2], str) else ""
    return (lines[0] if lines else ""), detected


def _clients5_text(data):
    if isinstance(data, str):
        return data.strip(), ""
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, str):
            return first.strip(), ""
        if isinstance(first, list) and first and isinstance(first[0], str):
            detected = first[1] if len(first) > 1 and isinstance(first[1], str) else ""
            return first[0].strip(), detected
    return "", ""


def _wiktionary_word(word, code):
    """The translation listed on the English Wiktionary page for one word."""
    label = _LANG_LABEL.get(code)
    if not label:
        return ""
    try:
        response = requests.get(
            "https://en.wiktionary.org/w/api.php",
            params={"action": "parse", "page": word.strip(), "prop": "wikitext", "format": "json"},
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=12,
        )
        response.raise_for_status()
        wikitext = response.json()["parse"]["wikitext"]["*"]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return ""
    forms = re.findall(
        r"\{\{t\+?\|" + re.escape(code) + r"\|([^|}]+)",
        wikitext,
    )
    for form in forms:
        cleaned = form.strip().replace("_", " ")
        if cleaned and not cleaned.startswith("{{"):
            return cleaned
    return ""


_HOW = re.compile(
    r"^how\s+(?:do\s+i|can\s+i|could\s+i|to|does\s+one)\s+(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_GUIDES = (
    (
        ("software engineer", "software engineering"),
        "To become a software engineer, prepare knowledge, tools, and a computer you can practice on.\n\n"
        "Knowledge: one programming language, how an app or a website is put together, and how to split a problem into small steps. "
        "Build small projects after each lesson so the skill is yours, not only something you watched.\n\n"
        "Tools: a code editor, Git to keep your work, and a web browser. "
        "Equipment: a laptop that can run those is enough. You do not need a powerful machine.\n\n"
        "Train for free at [freeCodeCamp](https://www.freecodecamp.org) "
        "and [The Odin Project](https://www.theodinproject.com).",
    ),
    (
        ("artificial intelligence", "an ai", " ai", "create ai", "make ai", "build ai"),
        "To create an AI, start with a small program that learns from examples, not with a giant system.\n\n"
        "Knowledge: basic Python, what data is, and the difference between a rule you wrote and a model trained on examples. "
        "Tools: Python, a notebook or a code editor, and a free dataset. "
        "Equipment: the same laptop you already use is enough for a first model.\n\n"
        "Train for free at [freeCodeCamp](https://www.freecodecamp.org/news/tag/machine-learning/) "
        "and [fast.ai](https://www.fast.ai).",
    ),
)


def _needs_search_intro(goal):
    """Technical tasks and long requests open with a search intro."""
    words = re.findall(r"[a-z0-9]+", goal.lower())
    technical = (
        "arduino", "python", "code", "program", "programming", "circuit", "robot",
        "install", "software", "website", "html", "css", "javascript", "repair",
        "sensor", "library", "firmware", "bootloader", "api",
    )
    return any(word in words for word in technical) or len(words) >= 6


_WHY = re.compile(r"^why\b", re.IGNORECASE)
_SCIENCE = re.compile(
    r"\b(sky|gravity|rain|boil|freeze|rust|photosynthesis|magnet|earth|moon|sun|light|"
    r"heat|sound|atom|cell|plant|water|oxygen|carbon|force|energy|orbit|tide|electric|"
    r"chemical|biology|physics|volcano|cloud|rainbow|friction|pressure|density|gas|"
    r"liquid|solid|bacteria|dna|evolution|climate|temperature|wave|particle|electron|"
    r"gravity|ice|steam|fire|star|planet|ocean|leaf|blood|heart|bone|muscle)\b",
    re.IGNORECASE,
)


def why_reply(message):
    """A why question. Ordinary reasons use a search intro; science links several facts."""
    text = re.sub(r"\s+", " ", (message or "")).strip()
    if not _WHY.match(text):
        return None
    facts = []
    for note in _duckduckgo_snippets(text) or []:
        spoken = _spoken_note(note) or note.strip()
        if spoken and spoken not in facts and not _is_word_gloss(spoken, text):
            facts.append(spoken)
    if _SCIENCE.search(text):
        for note in _wikipedia_snippet(text) or []:
            spoken = _spoken_note(note) or note.strip()
            if spoken and spoken not in facts and not _is_word_gloss(spoken, text):
                facts.append(spoken)
    if not facts:
        return None
    if not _SCIENCE.search(text):
        return " ".join(facts[:2])
    chain = _connect_facts(facts, text)
    if len(chain) < 2:
        return chain[0] if chain else facts[0]
    opening = chain[0]
    if not opening.lower().startswith("because"):
        opening = "Because " + opening[0].lower() + opening[1:]
    lines = [opening, "The facts connect like this:"]
    lines.extend(f"{index}. {fact}" for index, fact in enumerate(chain, start=1))
    shared = _shared_terms(chain)
    if shared:
        lines.append("They meet on " + ", ".join(shared[:3]) + ".")
    return "\n\n".join(lines)


def _is_word_gloss(fact, question):
    start = (fact or "").lower()
    return any(start.startswith(f"{word} is ") or start.startswith(f"{word}. ") for word in _content_words(question))


def _connect_facts(facts, question):
    """Order facts so each one shares a word with the previous fact."""
    remaining = list(facts)
    question_words = set(_content_words(question))

    def closeness(fact):
        return len(set(_content_words(fact)) & question_words)

    remaining.sort(key=closeness, reverse=True)
    chain = [remaining.pop(0)]
    while remaining and len(chain) < 4:
        previous = set(_content_words(chain[-1]))
        best_index = None
        best_shared = 0
        for index, fact in enumerate(remaining):
            shared = previous & set(_content_words(fact))
            if len(shared) > best_shared:
                best_shared = len(shared)
                best_index = index
        if best_index is None:
            break
        chain.append(remaining.pop(best_index))
    return chain


def _shared_terms(chain):
    terms = []
    for left, right in zip(chain, chain[1:]):
        for word in set(_content_words(left)) & set(_content_words(right)):
            if len(word) > 3 and word not in terms:
                terms.append(word)
    return terms


def how_to_reply(message):
    """A how-to question, answered from the source that fits that kind of task."""
    match = _HOW.match(re.sub(r"\s+", " ", (message or "")).strip())
    if not match:
        return None
    goal = re.sub(r"\bbecomes\b", "become", match.group(1).strip(" ."), flags=re.IGNORECASE)
    lowered = f" {goal.lower()} "
    for keys, guide in _GUIDES:
        if any(key in lowered for key in keys):
            return guide
    chosen = _how_sources(goal)
    found = [hit for source in chosen if (hit := _source_page(goal, source))]
    page = next((item for item in found if item.get("steps")), None)
    if page is None:
        page = next((item for item in found if item.get("text")), None)
    if page is None and found:
        page = found[0]
    if page is None:
        notes = _duckduckgo_snippets(message) or _wikipedia_snippet(goal)
        spoken = [note for note in (_spoken_note(note) for note in (notes or [])) if note]
        if not spoken:
            return "I couldn't confirm that from the public sources."
        return f"To {goal}, {spoken[0]}"
    lines = [f"To {goal}:"]
    if _needs_search_intro(goal):
        intro = next(
            (note for note in (_spoken_note(item) for item in _duckduckgo_snippets(f"how to {goal}")) if note),
            "",
        )
        if intro:
            lines.append(intro)
    if page.get("steps"):
        lines.extend(f"{index}. {step}" for index, step in enumerate(page["steps"][:6], start=1))
    elif page.get("text"):
        lines.append(page["text"])
    lines.append(f"[{page['name']}: {page['title']}]({page['url']})")
    related = list(page.get("related") or [])
    for item in found:
        if item is page:
            continue
        related.append({"title": item["title"], "url": item["url"]})
    seen = {page["url"]}
    extras = []
    for item in related:
        if item.get("url") in seen:
            continue
        seen.add(item["url"])
        extras.append(item)
        if len(extras) == 5:
            break
    if extras:
        lines.append("Other guides:")
        lines.extend(f"- [{item['title']}]({item['url']})" for item in extras)
    return "\n\n".join(lines)


def _how_sources(goal):
    """Pick the sites for this task. Practical questions start with a project guide and a video."""
    text = f" {goal.lower()} "
    if any(word in text for word in ("repair", "fix ", "ifix", "phone", "iphone", "screen", "battery")):
        return [("ifixit.com", "iFixit", "page")]
    if "arduino" in text:
        return [("docs.arduino.cc", "Arduino", "page"), ("youtube.com/watch", "YouTube", "video")]
    if "python" in text:
        return [("docs.python.org", "Python documentation", "page")]
    if any(word in text for word in ("website", "web page", "html", "css", "javascript")):
        return [("developer.mozilla.org", "MDN", "page"), ("wikihow.com", "wikiHow", "page")]
    if any(word in text for word in ("cook", "recipe", "rice", "bake", "boil", "fry")):
        return [("wikihow.com", "wikiHow", "page"), ("youtube.com/watch", "YouTube", "video")]
    if any(word in text for word in ("formula", "equation", "calculus", "theorem", "physics")):
        return [("ocw.mit.edu", "MIT OpenCourseWare", "page")]
    if any(word in text for word in ("robot", "build", "make ", "diy", "craft")):
        return [
            ("instructables.com", "Instructables", "page"),
            ("wikihow.com", "wikiHow", "page"),
            ("youtube.com/watch", "YouTube", "video"),
        ]
    return [("instructables.com", "Instructables", "page"), ("youtube.com/watch", "YouTube", "video")]


def _source_page(goal, source):
    site, name, kind = source
    if kind == "video":
        return _youtube_result(goal)
    finders = {
        "ifixit.com": _ifixit_result,
        "wikihow.com": _wikihow_result,
        "instructables.com": _instructables_result,
        "docs.python.org": _python_docs_result,
        "developer.mozilla.org": _mdn_result,
        "docs.arduino.cc": _arduino_result,
        "ocw.mit.edu": _ocw_result,
    }
    finder = finders.get(site)
    hit = finder(goal) if finder else None
    if not hit:
        return None
    if isinstance(hit, dict):
        return hit
    title, url = hit
    steps = _wikihow_steps(url) if "wikihow.com" in url else []
    return {
        "kind": "page",
        "name": name,
        "title": title or name,
        "url": url,
        "steps": steps,
        "text": "" if steps else _page_note(url),
        "related": [],
    }


def _guide_headers():
    return {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}


def _goal_words(goal):
    skip = {"with", "from", "your", "that", "this", "into", "using", "make", "build", "create", "program"}
    return [word for word in re.findall(r"[a-z0-9]+", goal.lower()) if len(word) > 2 and word not in skip]


def _youtube_result(goal):
    try:
        response = requests.get(
            "https://www.youtube.com/results",
            params={"search_query": f"how to {goal}"},
            headers=_guide_headers(),
            timeout=12,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    words = _goal_words(goal)
    ranked = []
    seen = set()
    for video_id, title in re.findall(
        r'"videoId":"([A-Za-z0-9_-]{11})".{0,700}?"text":"([^"\\]{6,140})"',
        response.text,
    ):
        if video_id in seen:
            continue
        seen.add(video_id)
        score = _title_score(title, words)
        lowered = title.lower()
        if any(skip in lowered for skip in ("cardboard", "#shorts", "one minute", "60 second")):
            score -= 4
        if "how to" in lowered:
            score += 2
        ranked.append((score, html.unescape(title), video_id))
    ranked = [item for item in ranked if item[0] > 0]
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return None
    _score, title, video_id = ranked[0]
    steps = _youtube_steps(video_id)
    return {
        "kind": "video",
        "name": "YouTube",
        "title": title,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "steps": steps,
        "text": "",
        "related": [
            {"title": name, "url": f"https://www.youtube.com/watch?v={vid}"}
            for _score, name, vid in ranked[1:6]
        ],
    }


def _title_score(title, words):
    lowered = title.lower()
    return sum(1 for word in words if re.search(rf"\b{re.escape(word)}", lowered))


def _youtube_steps(video_id):
    excerpt = _youtube_excerpt(video_id) or _youtube_description(video_id)
    if not excerpt:
        return []
    parts = [part.strip(" -") for part in re.split(r"(?<=[.!?])\s+|\n+", excerpt) if len(part.strip()) > 30]
    return parts[:4]


def _youtube_description(video_id):
    try:
        response = requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers=_guide_headers(),
            timeout=12,
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""
    found = re.search(r'"shortDescription":"(.*?)"', response.text)
    if not found:
        return ""
    try:
        return json.loads(f'"{found.group(1)}"')
    except ValueError:
        return ""


def _youtube_title(video_id):
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            headers=_guide_headers(),
            timeout=8,
        )
        response.raise_for_status()
        return (response.json().get("title") or "").strip()
    except (requests.RequestException, ValueError):
        return ""


def _ifixit_result(goal):
    words = _goal_words(goal)
    query = "iPhone repair" if "phone" in goal.lower() else goal
    try:
        response = requests.get(
            "https://www.ifixit.com/api/2.0/search/" + requests.utils.quote(query),
            headers=_guide_headers(),
            timeout=12,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
    except (requests.RequestException, ValueError):
        return None
    best = None
    for item in results:
        if item.get("dataType") != "guide" or not item.get("url"):
            continue
        title = item.get("title") or ""
        lowered = title.lower()
        if any(skip in lowered for skip in ("cable", "usb", "charger") if skip not in goal.lower()):
            continue
        hits = sum(1 for word in words if re.search(rf"\b{re.escape(word)}", lowered))
        if "iphone" in lowered or re.search(r"\bphone\b", lowered):
            hits += 2
        if any(part in lowered for part in ("screen", "battery", "display")) and "screen" not in goal.lower():
            hits += 3
        if best is None or hits > best[0]:
            best = (hits, title, item["url"])
    if not best or best[0] == 0:
        return None
    return best[1], best[2]


def _wikihow_result(goal):
    words = [word.capitalize() for word in re.findall(r"[A-Za-z0-9]+", goal)]
    slugs = ["-".join(words)]
    if words and words[0].lower() in {"build", "make", "create"}:
        slugs.append("-".join(["Make" if words[0].lower() == "build" else "Build", *words[1:]]))
        slugs.append("-".join(["Build", "a", "Simple", *words[1:]]))
    seen = set()
    for slug in slugs:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        url = f"https://www.wikihow.com/{slug}"
        try:
            response = requests.get(url, headers=_guide_headers(), timeout=12)
        except requests.RequestException:
            continue
        if response.status_code != 200 or "Client Challenge" in response.text[:500]:
            continue
        title = re.search(r"<title>(.*?)</title>", response.text, re.S)
        name = re.sub(r"\s+", " ", html.unescape(title.group(1))).split(" - ")[0].strip() if title else slug.replace("-", " ")
        if any(word in name.lower() for word in _goal_words(goal)):
            return name, response.url
    return None


def _instructables_result(goal):
    slug = "-".join(re.findall(r"[A-Za-z0-9]+", goal)).lower()
    for url in (
        f"https://www.instructables.com/{slug}/",
        f"https://www.instructables.com/howto/{slug}/",
    ):
        try:
            response = requests.get(url, headers=_guide_headers(), timeout=10)
        except requests.RequestException:
            continue
        if response.status_code != 200 or "couldn't find" in response.text[:400].lower():
            continue
        title = re.search(r"<title>(.*?)</title>", response.text, re.S)
        name = re.sub(r"\s+", " ", html.unescape(title.group(1) if title else "")).strip()
        if name and name.lower() not in {"loading", "instructables"}:
            return name, response.url
    return None


def _python_docs_result(goal):
    url = "https://docs.python.org/3/tutorial/index.html"
    if any(word in goal.lower() for word in ("file", "read", "write")):
        url = "https://docs.python.org/3/tutorial/inputoutput.html"
    elif any(word in goal.lower() for word in ("function", "def ")):
        url = "https://docs.python.org/3/tutorial/controlflow.html"
    elif any(word in goal.lower() for word in ("class", "object")):
        url = "https://docs.python.org/3/tutorial/classes.html"
    return "The Python Tutorial", url


def _mdn_result(goal):
    query = "getting started with the web" if "website" in goal.lower() else goal
    try:
        response = requests.get(
            "https://developer.mozilla.org/api/v1/search",
            params={"q": query, "locale": "en-US"},
            headers=_guide_headers(),
            timeout=12,
        )
        response.raise_for_status()
        documents = response.json().get("documents") or []
    except (requests.RequestException, ValueError):
        return None
    for item in documents:
        path = item.get("mdn_url") or ""
        title = item.get("title") or ""
        if not path.startswith("/en-US/docs/") or "/MDN/Community" in path:
            continue
        if title:
            return title, "https://developer.mozilla.org" + path
    return None


def _arduino_result(goal):
    matches = _arduino_matches(goal)
    if not matches:
        return None
    best = next((item for item in matches if item.get("steps")), matches[0])
    related = [item for item in matches if item["url"] != best["url"]]
    return {
        "kind": "page",
        "name": "Arduino",
        "title": best["title"],
        "url": best["url"],
        "steps": best.get("steps") or [],
        "text": "",
        "related": [{"title": item["title"], "url": item["url"]} for item in related[:5]],
    }


_ARDUINO_CATALOG = None


def _arduino_matches(goal):
    global _ARDUINO_CATALOG
    if _ARDUINO_CATALOG is None:
        _ARDUINO_CATALOG = _load_arduino_catalog()
    words = _goal_words(goal)
    generic = set(words) <= {"use", "arduino", "using", "start", "started", "begin"}
    ranked = []
    for item in _ARDUINO_CATALOG:
        score = _title_score(item["title"], words)
        lowered = item["title"].lower()
        if generic and "getting started" in lowered and "ide" in lowered and "cloud" not in lowered:
            score += 8
        if generic and lowered.startswith("use ") and "arduino" in lowered:
            score += 4
        if generic and any(word in lowered for word in ("memory", "partition", "aws", "business", "education", "linux", "cloud")):
            score -= 6
        if generic and any(mark in lowered for mark in ("mkr", "sara", "ctc", "bootloader", "nb 1500", "cloud agent")):
            score -= 3
        if score > 0:
            ranked.append((score, dict(item)))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    chosen = [item for _score, item in ranked[:8]]
    for item in chosen[:4]:
        item["steps"] = _markdown_steps(item.get("source") or "")
    return chosen


def _load_arduino_catalog():
    try:
        response = requests.get("https://docs.arduino.cc/llms.txt", headers=_guide_headers(), timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        return []
    entries = []
    pattern = re.compile(
        r"- \[([^\]]+)\]\((https://docs\.arduino\.cc/[^)]+)\): [^\n]*\n\s+Source: (\S+)"
    )
    for title, url, source in pattern.findall(response.text):
        entries.append({"title": html.unescape(title).strip(), "url": url, "source": source})
    return entries


def _markdown_steps(url):
    if not url:
        return []
    try:
        response = requests.get(url, headers=_guide_headers(), timeout=12)
        response.raise_for_status()
    except requests.RequestException:
        return []
    steps = []
    for line in response.text.splitlines():
        match = re.match(r"^(?:\d+\.|[-*])\s+(.{24,220})$", line.strip())
        if not match or match.group(1).startswith("["):
            continue
        step = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", match.group(1))
        step = step.replace("**", "").replace("`", "").strip()
        if step and step not in steps:
            steps.append(step)
        if len(steps) == 6:
            break
    return steps


def _wikihow_steps(url):
    try:
        response = requests.get(url, headers=_guide_headers(), timeout=12)
        response.raise_for_status()
    except requests.RequestException:
        return []
    steps = []
    for raw in re.findall(r'class="whb"[^>]*>(.*?)</(?:b|div|span)>', response.text, re.S):
        step = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(raw))).strip()
        if len(step) > 18 and step not in steps:
            steps.append(step)
        if len(steps) == 6:
            break
    return steps


def _ocw_result(goal):
    query = requests.utils.quote(goal)
    return "MIT OpenCourseWare", f"https://ocw.mit.edu/search/?q={query}"


def _page_note(url):
    try:
        response = requests.get(url, headers={"User-Agent": WIKI_USER_AGENT}, timeout=12)
        response.raise_for_status()
    except requests.RequestException:
        return ""
    text = re.sub(r"(?is)<(script|style|nav|footer|header).*?</\1>", " ", response.text)
    paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", text)
    for raw in paragraphs:
        clean = re.sub(r"<[^>]+>", "", html.unescape(raw))
        clean = re.sub(r"\s+", " ", clean).strip()
        if "contributor" in clean.lower() or "this guide" in clean.lower() or len(clean) < 80:
            continue
        note = _spoken_note(clean)
        if note:
            return note
    return ""


def _youtube_id(url):
    found = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url or "")
    return found.group(1) if found else ""


def _youtube_excerpt(video_id):
    """A short English caption line, when YouTube publishes one for that video."""
    try:
        response = requests.get(
            "https://www.youtube.com/api/timedtext",
            params={"v": video_id, "lang": "en"},
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=8,
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""
    pieces = re.findall(r">([^<]{12,})", response.text or "")
    words = []
    for piece in pieces:
        words.extend(html.unescape(piece).split())
        if len(words) >= 40:
            break
    if len(words) < 8:
        return ""
    return _spoken_note(" ".join(words[:40]))


def _spoken_note(note):
    text = re.sub(r"\s+", " ", note or "").strip()
    text = re.sub(r"^[A-Z][^.]{0,40}\.\s+", "", text)
    text = text.strip(" .")
    if len(text) < 40:
        return ""
    words = text.split()
    titled = sum(1 for word in words[:12] if word[:1].isupper())
    if titled >= 5:
        return ""
    if len(text) > 280:
        text = text[:280].rsplit(" ", 1)[0]
    return text[0].lower() + text[1:].rstrip(".") + "."


def looks_like_open_question(text):
    """An opinion or imagined situation, after the books have nothing to cite."""
    lowered = (text or "").lower()
    marks = (
        "what do you think",
        "imagine ",
        "suppose ",
        "what would you",
        "in your opinion",
        "think that",
        "think you",
        "what if ",
    )
    return any(mark in lowered for mark in marks)


def search_result_text(question):
    """Retrieve public snippets and retain only those matching the question."""
    query = re.sub(r"\s+", " ", (question or "")).strip()
    if not query:
        return None
    wanted = _question_words(query)
    content = [
        word for word in wanted
        if word not in _NUMBER_WORDS and not word.isdigit()
    ]
    wiki_lines = _wikipedia_snippet(query)
    lines = _matching(wiki_lines, content, minimum=2) or wiki_lines[:1]
    if not lines:
        found = _duckduckgo_snippets(query)
        lines = _matching(found, wanted) or found[:2]
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
            timeout=16,
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
