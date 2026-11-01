"""Reasoning agent backed by local books.

Drop a PDF in the books folder. It is indexed on this machine and is not
committed. More PDFs can be added later; each file becomes another book.
"""

import logging
import math
import pickle
import re
import threading
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)
_index_lock = threading.Lock()

BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "and", "or",
    "in", "on", "for", "with", "that", "this", "it", "as", "by", "from", "at",
    "what", "why", "how", "does", "do", "can", "you", "me", "my", "i", "we",
    "please", "explain", "tell", "about",
}
FOCUS = {
    "contrapositive", "converse", "induction", "contradiction", "quantifier",
    "quantifiers", "subset", "biconditional", "negation", "irrational",
    "implies", "existential", "universal",
}
REASONING_HINTS = (
    "prove", "proof", "show that", "therefore", "implies", "if and only if",
    "contrapositive", "contradiction", "induction", "quantif", "for all",
    "there exists", "set", "subset", "function", "theorem", "lemma", "axiom",
    "definition", "logic", "predicate", "proposition", "formal", "symbol",
    "truth table", "biconditional", "negation", "converse", "given", "goal",
    "compare", "versus", "difference", "tradeoff", "prefer", "better",
    "linear", "matrix", "vector", "convex", "gradient", "eigen",
    "bayes", "posterior", "prior", "likelihood",
    "variance", "statistic", "statistics", "hypothesis", "distribution", "confidence",
)
SEMANTIC_CONCEPTS = (
    (
        "basis",
        re.compile(r"\bbases?\b|\bunique coordinates?\b|\bcoordinate representation\b"),
        (
            ("basis", "bases"),
            ("span", "spanning"),
            ("independent", "independence"),
            ("coordinate", "coordinates", "representation", "unique"),
        ),
    ),
    (
        "rank-nullity",
        re.compile(
            r"\brank\s*[- ]\s*nullity\b|\bnullity\b|"
            r"\bdimension\b.*\b(image|kernel|null space)\b|"
            r"\b(image|kernel|null space)\b.*\bdimension\b"
        ),
        (
            ("rank",),
            ("nullity", "kernel", "null space"),
            ("dimension", "dimensional"),
            ("linear map", "transformation"),
        ),
    ),
    (
        "convexity",
        re.compile(r"\bconvex\b|\bline segment\b"),
        (
            ("convex",),
            ("line segment", "segment"),
            ("combination", "interpolation"),
            ("set", "points"),
        ),
    ),
    (
        "confidence-interval",
        re.compile(
            r"\bconfidence interval\b|\bconfidence level\b|"
            r"\b(interval|range)\b.*\bpopulation\b|"
            r"\bpopulation\b.*\b(interval|range)\b"
        ),
        (
            ("confidence",),
            ("interval",),
            ("population", "parameter"),
            ("sample", "estimate"),
        ),
    ),
    (
        "quantifier-negation",
        re.compile(r"\bquantifiers?\b|\bfor all\b|\bevery\b.*\bnegat"),
        (
            ("quantifier", "quantifiers"),
            ("negate", "negation"),
            ("universal", "every", "for all"),
            ("existential", "exists", "there exists"),
        ),
    ),
    (
        "python-loop",
        re.compile(
            r"\bfor loop\b|\biterate\b|\biteration\b|"
            r"\bpython\b.*\b(each|item|repeat)\b"
        ),
        (
            ("loop", "iteration", "iterate"),
            ("python",),
            ("sequence", "list", "range"),
            ("each", "element", "item"),
        ),
    ),
    (
        "bayesian-update",
        re.compile(
            r"\bprior\b.*\bposterior\b|\bposterior\b.*\bprior\b|\bbayes|"
            r"\bupdate\b.*\b(evidence|belief)|\b(evidence|belief)\b.*\bupdate"
        ),
        (
                ("prior", "before", "beforehand", "initial belief"),
                ("posterior", "after", "updated", "revised belief"),
                ("probability", "likelihood", "belief"),
                ("evidence", "bayes", "conditional", "update"),
        ),
    ),
)


class BookAgent:
    def __init__(self, books_dir=BOOKS_DIR):
        self.books_dir = Path(books_dir)
        self.books = []
        self._idf = {}
        self._ready = False

    def refresh(self):
        with _index_lock:
            self.books = []
            self._idf = {}
            if not self.books_dir.exists():
                self._ready = True
                return
            pdfs = sorted(self.books_dir.glob("*.pdf"))
            signature = [
                (path.name, path.stat().st_size)
                for path in pdfs
            ]
            cached = _load_cache(self.books_dir, signature)
            if cached:
                self.books, self._idf = cached
                self._ready = True
                return
            for path in pdfs:
                book = _read_pdf(path)
                if book and book["chunks"]:
                    self.books.append(book)
            self._idf = _idf_table(self.books)
            _save_cache(self.books_dir, signature, self.books, self._idf)
            self._ready = True
            if not self.books:
                logger.warning("No local books were loaded from %s", self.books_dir)

    def ensure(self):
        """Pick up PDFs another worker downloaded after this process started."""
        if self.books or not self.books_dir.exists():
            return
        if any(self.books_dir.glob("*.pdf")):
            self.refresh()

    def answer(self, message):
        self.ensure()
        text = (message or "").strip()
        if not text:
            return None

        passages = self._from_each_book(text)
        habit = _proof_habit(text)
        if habit:
            response = _speak(text, habit, passages)
        elif passages:
            response = _evidence_answer(passages)
        else:
            return None
        if not response:
            return None
        cited = any(
            f"_{title}, p. {page}_" in response
            for title, page, _ in passages
        )
        return {
            "response": response,
            "source": "book" if cited else "reasoning",
            "provider": "local-rules+books" if cited else "local-rules",
        }

    def _from_each_book(self, message):
        """Rank local passages with question terms and built-in concept synonyms."""
        if (
            _parity_habit((message or "").lower())
            or _induction_habit((message or "").lower())
        ):
            return []
        query = _tokens(message)
        concept = _semantic_concept(message)
        concept_key, concept_groups = concept if concept else (None, ())
        expanded_query = set(query)
        for group in concept_groups:
            for phrase in group:
                expanded_query.update(_tokens(phrase))
        if "statistic" in (message or "").lower():
            expanded_query.update({"probability", "statistics"})
        if not expanded_query or not self.books:
            return []
        ranked = []
        for book in self.books:
            best = None
            for chunk in book["chunks"]:
                if _navigation_chunk(chunk["text"]):
                    continue
                if not _on_topic(message, book["title"], chunk["text"]):
                    continue
                chunk_tokens = chunk["tokens"]
                if concept_key and not _supports_semantic_concept(
                    concept_key, message, chunk["text"]
                ):
                    continue
                if concept_groups:
                    concept_hits = sum(
                        any(set(_tokens(phrase)) & chunk_tokens for phrase in group)
                        for group in concept_groups
                    )
                    if concept_hits < 2:
                        continue
                elif query and len(query & chunk_tokens) < min(2, len(query)):
                    continue
                direct_hits = len(query & chunk_tokens)
                score = _tfidf(expanded_query, chunk_tokens, self._idf)
                score += 2.5 * direct_hits
                if concept_groups:
                    score += 3 * concept_hits
                if any(token in chunk_tokens for token in ("definition", "theorem", "means")):
                    score += 0.5
                if concept_key and _has_explicit_concept_phrase(
                    concept_key, chunk["text"]
                ):
                    score += 12
                if "statistic" in (message or "").lower() and "statistic" in book["title"].lower():
                    score += 3
                if chunk["text"].count(" . ") > 6 or chunk["text"].lower().count("chapter") >= 3:
                    score *= 0.1
                if best is None or score > best[0]:
                    best = (score, chunk["text"], chunk["page"])
            minimum_score = 4 if concept_groups else 10
            if best and best[0] >= minimum_score:
                ranked.append((
                    best[0],
                    book["title"],
                    best[2],
                    _clip_relevant(
                        best[1],
                        query,
                        expanded_query,
                        concept_groups,
                        self._idf,
                    ),
                ))
        ranked.sort(key=lambda item: item[0], reverse=True)
        kept = ranked[:1]
        if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] * 0.88:
            kept.append(ranked[1])
        return [(title, page, snippet) for _, title, page, snippet in kept]

    def excerpts(self, message):
        self.ensure()
        lines = []
        for title, page, snippet in self._from_each_book(message):
            lines.append(f"• _{title}, p. {page}_: {snippet}")
        return lines


def _read_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf is not installed, so %s was not read", path.name)
        return None
    try:
        reader = PdfReader(str(path))
        title = _known_title(path)
        if not title and reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title).strip()
        if not title or "/" in title or "\\" in title or title.lower().endswith(".dvi"):
            title = _display_title(path)
        chunks = []
        for index, page in enumerate(reader.pages, start=1):
            raw = page.extract_text() or ""
            for piece in _split_page(raw):
                tokens = _tokens(piece)
                if len(tokens) >= 8:
                    chunks.append({"text": piece, "page": index, "tokens": tokens})
        return {"title": title, "chunks": chunks}
    except Exception as exc:
        logger.warning("Could not read %s: %s", path.name, type(exc).__name__)
        return None


def _split_page(raw):
    text = re.sub(r"\s+", " ", raw).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.?!])\s+", text)
    chunks = []
    current = ""
    for part in parts:
        if len(current) + len(part) < 700:
            current = (current + " " + part).strip()
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


def _tokens(text):
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9']{2,}", (text or "").lower())
    return {word for word in words if word not in STOPWORDS}


def _semantic_concept(message):
    lowered = unicodedata.normalize("NFKC", message or "").lower()
    for key, pattern, groups in SEMANTIC_CONCEPTS:
        if pattern.search(lowered):
            return key, groups
    return None


def _supports_semantic_concept(key, question, passage):
    lowered = unicodedata.normalize("NFKC", passage or "").lower()
    if key == "basis":
        if re.search(r"\b(unique|uniquely)\b", question, re.I) and re.search(
            r"\bcoordinate", question, re.I
        ):
            return (
                bool(re.search(r"\bbases?\b", lowered))
                and bool(re.search(r"\b(unique|uniquely)\b", lowered))
                and bool(re.search(r"\b(coordinate|linear combination)\b", lowered))
            )
    elif key == "rank-nullity":
        return (
            bool(re.search(r"\brank\b", lowered))
            and bool(re.search(r"\b(nullity|kernel|null space)\b", lowered))
            and bool(re.search(r"\bdimension\b", lowered))
        )
    elif key == "confidence-interval":
        return (
            bool(re.search(r"\b(interval|range)\b", lowered))
            and bool(re.search(r"\b(population|parameter)\b", lowered))
            and bool(re.search(r"\b(confidence|estimate|estimated)\b", lowered))
        )
    elif key == "python-loop":
        return (
            bool(re.search(r"\b(loop|iteration|iterate)\b", lowered))
            and bool(re.search(r"\b(each|element|item|sequence|list|range)\b", lowered))
        )
    elif key == "bayesian-update":
        return (
            bool(re.search(r"\bbayes\b", lowered))
            and bool(re.search(r"\bprior\b", lowered))
            and bool(re.search(r"\bposterior\b", lowered))
            and bool(re.search(r"\b(update|evidence|data)\b", lowered))
        )
    return True


def _has_explicit_concept_phrase(key, passage):
    lowered = unicodedata.normalize("NFKC", passage or "").lower()
    if key == "basis":
        return bool(re.search(
            r"\blinear combination of basis vectors\b.{0,80}\bunique\b|"
            r"\b(unique|uniquely)\b.{0,80}\bcoordinates?\b|"
            r"\bbasis\b.{0,100}\bunique\b.{0,100}\bcoordinates?\b",
            lowered,
        ))
    if key == "rank-nullity":
        return bool(re.search(
            r"\brank\b.{0,100}\bnullity\b|\bnullity\b.{0,100}\brank\b",
            lowered,
        ))
    if key == "confidence-interval":
        return bool(re.search(r"\bconfidence interval\b", lowered))
    if key == "python-loop":
        return bool(re.search(r"\bfor\b.{0,100}\bin\b.{0,100}\bloop\b", lowered))
    if key == "bayesian-update":
        return bool(re.search(r"\bbayes(?:'|’)?s?\s+rule\b", lowered))
    return False


def _known_title(path):
    key = path.stem.lower().replace("-", "").replace("_", "").replace(" ", "")
    names = (
        ("bookofproof", "Book of Proof"),
        ("howtoproveit", "How to Prove It"),
        ("hefferon", "Linear Algebra (Hefferon)"),
        ("linearalgebra", "Linear Algebra"),
        ("convex", "Convex Optimization"),
        ("thinkbayes", "Think Bayes"),
        ("thinkpython", "Think Python"),
        ("openlogic", "Open Logic"),
        ("introductorystatistics", "Introductory Statistics"),
        ("bayesreasoning", "Bayesian Reasoning and Machine Learning"),
    )
    for needle, title in names:
        if needle in key:
            return title
    return ""


def _display_title(path):
    return _known_title(path) or path.stem.replace("_", " ").replace("-", " ")


def _clip(text, limit=240):
    snippet = re.sub(r"\s+", " ", text).strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit].rsplit(" ", 1)[0] + "..."


def _clip_relevant(text, query, expanded_query, concept_groups, idf, limit=240):
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if len(normalized) <= limit:
        return normalized

    def score(candidate):
        tokens = _tokens(candidate)
        concept_hits = sum(
            any(set(_tokens(phrase)) & tokens for phrase in group)
            for group in concept_groups
        )
        return (
            3 * len(query & tokens)
            + _tfidf(expanded_query, tokens, idf)
            + 4 * concept_hits
            - 0.025 * len(candidate)
        )

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    candidates = [sentence for sentence in sentences if sentence.strip()]
    best = max(candidates, key=score, default=normalized)
    if len(best) <= limit:
        return best

    words = list(re.finditer(r"\S+", best))
    windows = []
    for start in range(len(words)):
        for end in range(start + 1, len(words) + 1):
            if words[end - 1].end() - words[start].start() > limit:
                break
            candidate = best[words[start].start():words[end - 1].end()]
            if len(candidate) >= 60:
                windows.append(candidate)
    if not windows:
        return _clip(best, limit)
    selected = max(windows, key=score)
    start = best.find(selected)
    prefix = "..." if start > 0 else ""
    suffix = "..." if start + len(selected) < len(best) else ""
    return prefix + selected + suffix


def _clauses(text):
    """Pull P and Q out of 'if P then Q' or 'if P, Q'."""
    body = re.sub(r"\s+", " ", text or "").strip()
    match = re.search(r"\bif\s+(.+?)\s+then\s+(.+)$", body, re.I)
    if not match:
        match = re.search(r"\bif\s+([^,]+),\s*(?:then\s+)?(.+)$", body, re.I)
    if not match:
        return None
    premise = match.group(1).strip(" .?:")
    conclusion = re.sub(r"\s+(true|false)$", "", match.group(2).strip(" .?:"), flags=re.I)
    premise = re.sub(r"^.*\bof\s+", "", premise, flags=re.I).strip()
    if not premise or not conclusion:
        return None
    return premise, conclusion


def _deny(clause):
    words = clause.strip()
    if words.lower().startswith("not "):
        return words[4:]
    return "not " + words


def _page_supports(snippet, conclusion, anchors):
    """A page stays only when it carries the conclusion, not one nearby word."""
    words = [word for word in _tokens(conclusion) if len(word) >= 4]
    lowered = (snippet or "").lower()
    hits = sum(1 for word in words if word in lowered)
    if hits < 2 or hits / max(1, len(words)) < 0.35:
        return False
    if anchors:
        anchor_hits = sum(
            anchor in lowered
            for anchor in anchors
            if anchor not in {"__sqrt2__", "__coprime__"}
        )
        if "__sqrt2__" in anchors:
            anchor_hits += int(any(
                marker in lowered
                for marker in ("√2", "sqrt(2)", "square root of 2")
            ))
        if "__coprime__" in anchors:
            anchor_hits += int(any(
                marker in lowered
                for marker in ("lowest terms", "coprime")
            ))
        if anchor_hits < min(3, len(anchors)):
            return False
    return True


def _navigation_chunk(text):
    """Reject table-of-contents fragments that match terms but do not explain them."""
    content = text or ""
    section_entries = re.findall(r"\b\d+(?:\.\d+){1,2}\.?\s+[A-Z]", content)
    page_references = re.findall(r"\b(?:[A-Z]-\d+|\d{1,4})\b", content)
    return (
        len(section_entries) >= 3
        or (len(page_references) >= 8 and content.count(",") >= 5)
    )


def _speak(text, habit, passages):
    """Keep local derivations distinct from evidence quoted from indexed books."""
    lines = []
    if habit:
        lines.append(f"Built-in reasoning (not a quotation):\n{habit}")
    anchors = _page_anchors(text)
    supported = [
        item for item in passages
        if _page_supports(item[2], text, anchors)
        or (habit and _page_supports(item[2], habit, anchors))
    ]
    if supported:
        lines.append("From the books:")
        for title, page, snippet in supported:
            lines.append(f"• _{title}, p. {page}_: {snippet}")
    return "\n\n".join(lines).strip()


def _evidence_answer(passages):
    lines = ["The closest matching evidence in the local books is:"]
    lines.extend(
        f"• _{title}, p. {page}_: {snippet}"
        for title, page, snippet in passages
    )
    lines.append(
        "These are source excerpts, not a paraphrase; they support only what the "
        "passages themselves state."
    )
    return "\n\n".join(lines)


def _page_anchors(text):
    lowered = (text or "").lower()
    if "√2" in text or "sqrt(2)" in lowered or "square root of 2" in lowered:
        return ("__sqrt2__", "__coprime__")
    if "contrapositive" in lowered:
        return ("contrapositive", "direct proof")
    if "converse" in lowered:
        return ("converse",)
    if "subspace" in lowered or "zero vector" in lowered:
        return ("closed", "scalar")
    if "subset" in lowered:
        return ("subset",)
    if "square" in lowered or "squared" in lowered or "²" in text:
        return ("square",)
    if "sum" in lowered or re.search(r"\b(plus|adding)\b", lowered):
        return ("sum",)
    if "even" in lowered and re.search(r"\b(prove|show that)\b", lowered):
        return ("even",)
    if "priority" in lowered or "statistic" in lowered:
        return ("probability", "statistic")
    return ()


def _on_topic(message, title, text):
    """A statistics question must come from a statistics page, not a chance use of one word."""
    lowered = (message or "").lower()
    if "statistic" not in lowered:
        return True
    blob = f"{title} {text}".lower()
    return any(word in blob for word in ("statistic", "probability", "variance", "distribution", "sample"))


def looks_like_reasoning(text):
    return _is_reasoning_question(text) or _proof_habit(text) is not None


def _comparison(lowered):
    """Six-step comparison: two ideas, likeness, difference, tradeoff, choice, justification."""
    pair = _split_pair(lowered)
    if not pair:
        return None
    left, right = pair
    known = _known_comparison(left, right)
    if known:
        return known
    return None


def _split_pair(lowered):
    patterns = (
        r"(?:compare|comparison of|comparison between|difference between|tradeoff between)\s+(.+?)\s+(?:and|vs\.?|versus|with)\s+(.+)",
        r"(.+?)\s+(?:vs\.?|versus)\s+(.+)",
        r"which is (?:better|preferable)[,:]?\s+(.+?)\s+or\s+(.+)",
        r"(?:should i use|when should i use|prefer)\s+(.+?)\s+(?:or|over|instead of|rather than)\s+(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        left = _clean_side(match.group(1))
        right = _clean_side(match.group(2))
        if left and right and left != right:
            return left, right
    return None


def _clean_side(side):
    side = re.sub(r"^(a|an|the)\s+", "", side.strip(" ?.!"))
    side = re.sub(r"\s+(proof|method|approach)$", "", side).strip()
    return side


def _known_comparison(left, right):
    blob = f"{left} {right}"
    if "direct" in blob and "contrapositive" in blob:
        return (
            "What they are. A direct proof of P → Q assumes P and derives Q. "
            "A contrapositive proof assumes ¬Q and derives ¬P. In symbols, (P → Q) ↔ (¬Q → ¬P).\n\n"
            "Where they agree. They prove the same implication. If one is finished, the other statement is already true.\n\n"
            "Where they differ. Direct proof pushes from the hypothesis. Contrapositive proof pushes from the denial of the goal, which is often easier when Q is 'even', 'divisible', or some other positive form.\n\n"
            "The tradeoff. Direct proof is shorter when P is easy to use. Contrapositive proof adds a negation and pays for it when ¬Q is the cleaner assumption.\n\n"
            "When one is preferable. I use a direct proof when the hypothesis hands me the algebra. "
            "I use the contrapositive when the hypothesis is awkward and the denial of the conclusion is simple, as in 'if n² is even, then n is even'.\n\n"
            "Why that conclusion. The two proofs are equivalent, so the choice is about the path, not about a different theorem. "
            "I pick the path whose first assumption I can actually write down."
        )
    if ("local" in blob and "global" in blob) or ("convex" in blob and ("nonconvex" in blob or "linear" in blob)):
        return (
            "What they are. A local minimum is a point where no nearby feasible point is better. "
            "A global minimum is a point where no feasible point anywhere is better. "
            "A set C is convex when ∀x,y ∈ C and ∀t ∈ [0,1], tx + (1-t)y ∈ C. "
            "A function on a convex set is convex when its graph lies under the chords: f(tx+(1-t)y) ≤ t f(x) + (1-t) f(y).\n\n"
            "Where they agree. Every global minimum is a local minimum. On a convex problem, a local minimum is global.\n\n"
            "Where they differ. Outside convex problems, a local minimum can be a trap. Linear algebra gives exact structure (spans, bases, Ax = b). Convex optimization gives a guaranteed best point when the set and the objective are convex, even if the algebra is not a single linear system.\n\n"
            "The tradeoff. Linear algebra is exact and cheap when the model is linear. Convex optimization covers inequalities and curved objectives, and the price is an algorithm instead of one factorization.\n\n"
            "When one is preferable. I use linear algebra when the claim is Ax = b, a basis, or an eigenvalue. "
            "I use convex optimization when the goal is to minimize a convex f over a convex set, especially with inequalities.\n\n"
            "Why that conclusion. If the problem is convex, every local solution is a global one, so I do not have to second-guess the answer. "
            "If it is not convex, a point that looks best nearby may not be best at all."
        )
    if "gradient" in blob or ("least squares" in blob and "convex" in blob):
        return (
            "What they are. Least squares solves min ||Ax - b||², a convex quadratic. "
            "A general convex problem is min f(x) subject to x ∈ C, with f and C convex.\n\n"
            "Where they agree. Both seek a global minimum, and for least squares that minimum is also the solution of the normal equations AᵀA x = Aᵀb.\n\n"
            "Where they differ. Least squares has a closed linear-algebra form. A general convex problem may only offer inequalities, so the step is a descent or a projection, not one matrix solve.\n\n"
            "The tradeoff. The normal equations are fast when A is modest and well behaved. A convex solver still works when the constraint is an inequality the normal equations cannot say.\n\n"
            "When one is preferable. I use least squares when the model is Ax ≈ b with no inequalities. "
            "I use the convex formulation when a constraint such as x ≥ 0 or ||x|| ≤ 1 is part of the claim.\n\n"
            "Why that conclusion. The squared residual is convex, so the least-squares point is not just a local fit. "
            "The moment a constraint leaves the linear world, I keep the convex method so the minimum stays global."
        )
    if ("span" in blob and "basis" in blob) or ("independence" in blob and ("span" in blob or "basis" in blob)):
        return (
            "What they are. A span is every linear combination of a list of vectors. "
            "A basis of a subspace V is a linearly independent list that spans V. "
            "Linear independence means a₁v₁ + … + aₙvₙ = 0 ⇒ every aᵢ = 0.\n\n"
            "Where they agree. Both describe how vectors build a subspace. A basis is a span that has no redundant vector.\n\n"
            "Where they differ. A spanning list can be too long. An independent list can be too short to cover V. Only a basis is both.\n\n"
            "The tradeoff. Extra spanning vectors make coordinates ambiguous. A basis gives unique coordinates, at the cost of checking independence.\n\n"
            "When one is preferable. I speak of the span when I only need to know which vectors I can reach. "
            "I ask for a basis when I need dimension or unique coordinates.\n\n"
            "Why that conclusion. Dimension is the length of a basis, not the length of some spanning list. "
            "If the list is dependent, that length is not the dimension, so the basis is the one I trust."
        )
    if "eigen" in blob and ("singular" in blob or "vector" in blob):
        return (
            "What they are. An eigenvector of A satisfies A v = λ v, with v ≠ 0. "
            "The singular value description writes A = U Σ Vᵀ, and it exists for every matrix, square or not.\n\n"
            "Where they agree. Both expose directions that A treats in a simple way, stretching or shrinking along special axes.\n\n"
            "Where they differ. Eigenvalues can be complex or missing over the reals, and they need a square matrix. Singular values are nonnegative and exist for every A.\n\n"
            "The tradeoff. Eigenvectors diagonalize A when a full basis of them exists, which is the cleanest algebra. Singular vectors still describe stretch when A is rectangular or not diagonalizable.\n\n"
            "When one is preferable. I use eigenvalues when A is square and I care about A v = λ v, powers of A, or a diagonalization. "
            "I use singular values when A is rectangular or I need a stable notion of stretch, such as ||A||.\n\n"
            "Why that conclusion. A v = λ v is a stronger algebraic demand than a singular-value factorization. "
            "I only claim eigenvalues when that equation has a nonzero solution."
        )
    return None


def _proof_habit(text):
    """Symbolic proof talk. The wording is original; the books only supply support."""
    lowered = re.sub(r"\s+", " ", text.lower()).strip(" ?.")
    compared = _comparison(lowered)
    if compared:
        return compared

    induction = _induction_habit(lowered)
    if induction:
        return induction

    truth_condition = _conditional_truth_condition(lowered)
    if truth_condition:
        return truth_condition

    concept = _logic_concept(lowered)
    if concept:
        return concept

    parity = _parity_habit(lowered)
    if parity:
        return parity

    if "truth table" in lowered:
        return (
            "Given a formula built from P and Q. Goal: the rows where it is true.\n"
            "∧ is true only when both sides are true. ∨ is false only when both are false. "
            "¬ flips the value. P → Q is false only in the row P true, Q false. "
            "P ↔ Q is true exactly when P and Q match. ∴ a truth table decides the connective before any English paraphrase."
        )
    if "negat" in lowered and ("quantif" in lowered or "for all" in lowered or "there exists" in lowered):
        return (
            "Negation pushes in and flips the quantifier.\n"
            "¬∀x P(x)  ↔  ∃x ¬P(x).\n"
            "¬∃x P(x)  ↔  ∀x ¬P(x).\n"
            "So the denial of 'every integer is even' is 'some integer is not even', and one odd witness settles it."
        )
    if "contrapositive" in lowered:
        parts = _clauses(text)
        if parts:
            premise, conclusion = parts
            return (
                f"Rule: contrapositive. P is \"{premise}\". Q is \"{conclusion}\".\n"
                f"The contrapositive is ¬Q → ¬P: if {_deny(conclusion)}, then {_deny(premise)}.\n"
                f"(P → Q) ↔ (¬Q → ¬P). The converse, if {conclusion}, then {premise}, is a different claim."
            )
        return (
            "Rule: contrapositive. Given P → Q, the contrapositive is ¬Q → ¬P, "
            "and (P → Q) ↔ (¬Q → ¬P). The converse Q → P is a different claim."
        )
    if "converse" in lowered:
        parts = _clauses(text)
        if parts:
            premise, conclusion = parts
            even_square = "even" in premise.lower() and "even" in conclusion.lower() and "square" in conclusion.lower()
            verdict = (
                "This converse is true: if n is odd then n squared is odd, so n squared even forces n even."
                if even_square else
                "The original implication does not decide this converse."
            )
            return (
                f"Rule: converse. P is \"{premise}\". Q is \"{conclusion}\".\n"
                f"The converse is Q → P: if {conclusion}, then {premise}.\n"
                f"{verdict}"
            )
        return (
            "Rule: converse. The converse of P → Q is Q → P. "
            "They are different claims, so the original implication does not prove the converse."
        )
    if "if and only if" in lowered or re.search(r"\biff\b", lowered) or "↔" in text or "<->" in lowered:
        return (
            "P ↔ Q means (P → Q) ∧ (Q → P). Both directions are required.\n"
            "Even(n) ↔ Even(n²): if n = 2k then n² = 4k², so n² is even. "
            "If n is odd then n² is odd, so the other direction is the contrapositive of 'odd squares stay odd'."
        )
    sqrt_two = bool(re.search(
        r"(?:square root of 2|sqrt\s*\(\s*2\s*\)|√\s*2|\broot 2\b)",
        lowered,
    )) or "√2" in text
    if sqrt_two:
        return (
            "To prove R, assume ¬R and reach S ∧ ¬S.\n"
            "Assume √2 = a/b for coprime positive integers a and b. Then a² = 2b² is even, "
            "so a is even: an odd integer has an odd square. Write a = 2k. Substitution gives "
            "b² = 2k², so b is even for the same reason. Now a and b share the factor 2, "
            "contradicting that they are coprime. ∴ √2 is irrational."
        )
    if re.search(r"proof by cases|case analysis|exhaustive cases", lowered):
        return (
            "A proof by cases splits the hypothesis into an exhaustive list.\n"
            "Given P ∨ Q, and both P → R and Q → R, conclude R.\n"
            "For an integer n, the cases n even and n odd cover every integer, so a claim proved in both cases holds for all n."
        )
    if "subspace" in lowered and ("zero" in lowered or "0" in lowered):
        return (
            "Take any vector v in the subspace. "
            "If the subspace is closed under scalar multiplication, then 0·v is in it. "
            "0·v is the zero vector, so the subspace contains 0."
        )
    if "subset" in lowered or "∈" in text or "⊆" in text:
        example = ""
        if "example" in lowered:
            example = (
                "\n\nExample. {1, 2} ⊆ {1, 2, 3}, because each element of the first "
                "set is in the second.\n"
                "Non-example. {1, 4} ⊄ {1, 2, 3}, because 4 is missing from the second set."
            )
        return (
            "Rule: subset. x ∈ A means x is a member of A. A ⊆ B means ∀x (x ∈ A → x ∈ B).\n"
            "To prove A ⊆ B, let x be arbitrary, assume x ∈ A, and show x ∈ B. "
            "A = B means (A ⊆ B) ∧ (B ⊆ A)."
            + example
        )
    if "for all" in lowered or "there exists" in lowered or "quantif" in lowered or "∀" in text or "∃" in text:
        return (
            "∀x ∈ S, P(x) is proved by letting x be an arbitrary element of S and proving P(x).\n"
            "∃x ∈ S, P(x) is proved by naming one witness.\n"
            "One counterexample refutes ∀. One example never proves ∀."
        )
    if re.search(r"\b(prove|show that)\b", lowered) and "even" in lowered:
        return (
            "Definition: Even(n) ↔ ∃k ∈ Z (n = 2k).\n"
            "Rule: direct proof. P is Even(a) and Even(b). Q is Even(a+b).\n"
            "Given Even(a) ∧ Even(b). Then a = 2m and b = 2n, so a + b = 2(m+n). "
            "m+n ∈ Z, hence Even(a+b). ∴ the sum of two even integers is even."
        )
    return None


def _induction_habit(lowered):
    if "induction" not in lowered:
        return None

    normalized = re.sub(r"\s+", "", lowered).replace("…", "...")
    sum_formula = re.search(
        r"1\+2\+\.{3,}\+n=n\(n\+1\)/2",
        normalized,
    )
    if sum_formula:
        return (
            "Let P(n) be 1 + 2 + … + n = n(n + 1)/2.\n\n"
            "- Base case (n = 1): 1 = 1(2)/2 = 1, so P(1) holds.\n"
            "- Inductive hypothesis: assume P(k), so 1 + 2 + … + k = k(k + 1)/2.\n"
            "- Inductive step:\n"
            "  1 + 2 + … + k + (k + 1)\n"
            "  = k(k + 1)/2 + (k + 1)\n"
            "  = (k + 1)(k + 2)/2.\n"
            "- This is P(k + 1). Therefore, by induction, the formula holds for every integer n ≥ 1."
        )

    if "..." in normalized:
        return (
            "I can’t verify this induction claim as written because the ellipsis does not "
            "specify the terms or the stopping index. Please give the exact sequence, "
            "the first value of n, and the proposed right-hand side."
        )
    return (
        "Please state the exact proposition P(n) you want to prove. An induction proof "
        "needs a starting value and a rule that takes P(k) to P(k + 1)."
    )


def _conditional_truth_condition(lowered):
    implication = re.search(r"\bp\s*(?:→|->|implies)\s*q\b", lowered)
    asks_when = re.search(r"\b(when|under what conditions|which row)\b", lowered)
    asks_false = re.search(r"\b(false|falsity)\b", lowered)
    if implication and asks_when and asks_false:
        return (
            "P → Q is false in exactly one case: P is true and Q is false. "
            "If P is false, or if Q is true, the implication is true."
        )
    return None


def _logic_concept(lowered):
    if "rank-nullity" in lowered or "rank nullity" in lowered:
        return (
            "Rank–nullity theorem. For a linear map T: V → W with finite-dimensional "
            "domain V, dim(V) = rank(T) + nullity(T).\n\n"
            "- rank(T) is dim(im(T)), the dimension of the output space reached by T.\n"
            "- nullity(T) is dim(ker(T)), the dimension of the inputs sent to zero.\n"
            "- For an m × n matrix A, rank(A) + nullity(A) = n, the number of columns."
        )

    if "basis" in lowered and re.search(r"\b(vectors?|space|span|independent)\b", lowered):
        return (
            "A basis of a vector space is a set of vectors that both spans the space "
            "and is linearly independent.\n\n"
            "- Spanning means every vector in the space can be written as a linear "
            "combination of the basis vectors.\n"
            "- Linear independence means no basis vector is redundant: only the "
            "trivial combination equals zero.\n"
            "- Together, these properties give every vector a unique coordinate "
            "representation in that basis."
        )

    if "convex set" in lowered or ("convex" in lowered and "line segment" in lowered):
        return (
            "A set C is convex if, for every x, y ∈ C and every t ∈ [0, 1], "
            "(1 − t)x + ty ∈ C. In plain language, the entire line segment between "
            "any two points in C stays inside C.\n\n"
            "Example: the interval [0, 1] is convex; every point between any two "
            "members is still in the interval. Non-example: {0, 1} is not convex, "
            "because the segment between 0 and 1 contains points such as 1/2 that "
            "are not in the set."
        )
    return None


def _parity_habit(lowered):
    """Prove or refute common parity claims from their actual operands."""
    square = re.search(r"\b(square|squared)\b|²|\*\*2", lowered)
    if square:
        parities = re.findall(r"\b(even|odd)\b", lowered)
        if len(parities) >= 2:
            operand, claimed = parities[0], parities[-1]
            actual = operand
            if claimed != actual:
                witness = "n = 2, so n² = 4 is even" if operand == "even" else "n = 1, so n² = 1 is odd"
                return (
                    f"The claim is false. Counterexample: {witness}; "
                    f"that contradicts the claim that an {operand} integer has an {claimed} square."
                )
            if operand == "even":
                return (
                    "Let n be an even integer, so n = 2k for some integer k. "
                    "Then n² = (2k)² = 4k² = 2(2k²). Since 2k² is an integer, "
                    "n² is even."
                )
            return (
                "Let n be an odd integer, so n = 2k + 1 for some integer k. "
                "Then n² = (2k + 1)² = 4k² + 4k + 1 = 2(2k² + 2k) + 1. "
                "Since 2k² + 2k is an integer, n² is odd."
            )

    operation = None
    pair = None
    for candidate, pattern in (
        ("sum", r"\b(?:sum|adding|addition)\b|\+"),
        ("product", r"\b(?:product|multiplying|multiplication|times)\b|[×*]"),
    ):
        if not re.search(pattern, lowered):
            continue
        operation = candidate
        pair_patterns = (
            r"\b(even|odd)\s*(?:\+|×|\*)\s*(even|odd)\b",
            rf"\b(?:sum|product)\s+of\s+(?:two\s+)?(?:an?\s+)?(even|odd)\b"
            r"(?:\s+integers?|\s+numbers?)?\s+and\s+(?:two\s+)?(?:an?\s+)?(even|odd)\b",
            rf"\b(?:sum|product)\s+of\s+two\s+(even|odd)\b"
            r"(?:\s+integers?|\s+numbers?)?",
            rf"\b(?:adding|multiplying)\s+(?:two\s+)?(?:an?\s+)?(even|odd)\b"
            r"(?:\s+integers?|\s+numbers?)?\s+and\s+(?:two\s+)?(?:an?\s+)?(even|odd)\b",
            rf"\b(?:adding|multiplying)\s+two\s+(even|odd)\b"
            r"(?:\s+integers?|\s+numbers?)?",
        )
        for pair_pattern in pair_patterns:
            match = re.search(pair_pattern, lowered)
            if match:
                right = match.group(2) if match.lastindex and match.lastindex > 1 else None
                pair = (match.group(1), right or match.group(1))
                remainder = lowered[match.end():]
                result_match = re.search(r"\b(even|odd)\b", remainder)
                if not result_match:
                    return None
                claimed = result_match.group(1)
                break
        if pair:
            break
        operation = None

    if not pair or not operation:
        return None

    left, right = pair
    if operation == "sum":
        actual = "even" if left == right else "odd"
    else:
        actual = "even" if "even" in pair else "odd"

    if claimed != actual:
        examples = {
            ("sum", "even", "even"): "2 + 4 = 6",
            ("sum", "odd", "odd"): "1 + 1 = 2",
            ("sum", "even", "odd"): "2 + 1 = 3",
            ("sum", "odd", "even"): "1 + 2 = 3",
            ("product", "odd", "odd"): "3 × 5 = 15",
            ("product", "even", "odd"): "2 × 3 = 6",
            ("product", "odd", "even"): "3 × 2 = 6",
            ("product", "even", "even"): "2 × 4 = 8",
        }
        example = examples[(operation, left, right)]
        return (
            f"The claim is false. Counterexample: {example}, which is {actual}, "
            f"not {claimed}."
        )

    if operation == "sum" and left == right == "even":
        return (
            "Let a = 2m and b = 2n for integers m and n. Then "
            "a + b = 2m + 2n = 2(m + n). Since m + n is an integer, "
            "the sum of two even integers is even."
        )
    if operation == "sum" and left == right == "odd":
        return (
            "Let a = 2m + 1 and b = 2n + 1 for integers m and n. Then "
            "a + b = 2m + 2n + 2 = 2(m + n + 1). Since m + n + 1 is an integer, "
            "the sum of two odd integers is even."
        )
    if operation == "sum":
        return (
            "Let the even integer be 2m and the odd integer be 2n + 1, "
            "where m and n are integers. Their sum is 2m + 2n + 1 = "
            "2(m + n) + 1, so the sum is odd."
        )
    if left == right == "odd":
        return (
            "Let a = 2m + 1 and b = 2n + 1 for integers m and n. Then "
            "ab = (2m + 1)(2n + 1) = 2(2mn + m + n) + 1. "
            "The quantity in parentheses is an integer, so the product is odd."
        )
    return (
        "One factor is even, so write it as 2m for an integer m and call the "
        "other integer n. Their product is (2m)n = 2(mn). Since mn is an "
        "integer, the product is even."
    )


def _is_reasoning_question(text):
    lowered = text.lower()
    for hint in REASONING_HINTS:
        if " " in hint:
            if hint in lowered:
                return True
        elif re.search(rf"\b{re.escape(hint)}\b", lowered):
            return True
    if re.search(r"[∀∃∈⊆∧∨¬→↔√]", text):
        return True
    return bool(re.search(r"\b(why|how)\b", lowered)) and len(_tokens(text)) >= 3


def _idf_table(books):
    counts = {}
    total = 0
    for book in books:
        for chunk in book["chunks"]:
            total += 1
            for token in chunk["tokens"]:
                counts[token] = counts.get(token, 0) + 1
    if not total:
        return {}
    return {
        token: math.log((total + 1) / (count + 1)) + 1
        for token, count in counts.items()
    }


def _tfidf(query, tokens, idf):
    return sum(idf.get(token, 0) for token in query if token in tokens)


def _cache_path(books_dir):
    return Path(books_dir) / ".index.pkl"


def _load_cache(books_dir, signature):
    path = _cache_path(books_dir)
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)
        if payload.get("signature") != signature and not _same_books(payload.get("signature"), signature):
            return None
        return payload["books"], payload["idf"]
    except Exception:
        return None


def _same_books(saved, current):
    """Name and size are enough. A changed timestamp must not force a full reread."""
    def key(item):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None
        return (item[0], item[1])
    if not isinstance(saved, list) or not isinstance(current, list):
        return False
    return [key(item) for item in saved] == [key(item) for item in current]


def _save_cache(books_dir, signature, books, idf):
    path = _cache_path(books_dir)
    try:
        with path.open("wb") as handle:
            pickle.dump({"signature": signature, "books": books, "idf": idf}, handle)
    except Exception as exc:
        logger.warning("Could not save the book index: %s", type(exc).__name__)
