"""Reasoning agent backed by local books.

Drop a PDF in the books folder. It is indexed on this machine and is not
committed. More PDFs can be added later; each file becomes another book.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "and", "or",
    "in", "on", "for", "with", "that", "this", "it", "as", "by", "from", "at",
    "what", "why", "how", "does", "do", "can", "you", "me", "my", "i", "we",
    "please", "explain", "tell", "about",
}
REASONING_HINTS = (
    "prove", "proof", "show that", "therefore", "implies", "if and only if",
    "contrapositive", "contradiction", "induction", "quantif", "for all",
    "there exists", "set", "subset", "function", "theorem", "lemma", "axiom",
    "definition", "logic", "predicate", "proposition", "formal",
)


class BookAgent:
    def __init__(self, books_dir=BOOKS_DIR):
        self.books_dir = Path(books_dir)
        self.books = []
        self.refresh()

    def refresh(self):
        self.books = []
        if not self.books_dir.exists():
            return
        for path in sorted(self.books_dir.glob("*.pdf")):
            book = _read_pdf(path)
            if book and book["chunks"]:
                self.books.append(book)

    def answer(self, message):
        text = (message or "").strip()
        if not text:
            return None

        habit = _proof_habit(text)
        if habit:
            return {
                "response": habit,
                "source": "book",
                "provider": "book-of-proof",
            }

        passages = self._search(text)
        if passages:
            return {
                "response": _from_books(text, passages),
                "source": "book",
                "provider": "books",
            }

        if _is_reasoning_question(text):
            return {
                "response": _reason_without_book(text),
                "source": "book",
                "provider": "reasoning",
            }
        return None

    def _search(self, message, limit=3):
        query = _tokens(message)
        if not query or not self.books:
            return []
        scored = []
        for book in self.books:
            for chunk in book["chunks"]:
                score = len(query & chunk["tokens"])
                if score >= 2 or (score == 1 and len(query) <= 3):
                    scored.append((score, book["title"], chunk["text"], chunk["page"]))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:limit]


def _read_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf is not installed, so %s was not read", path.name)
        return None
    try:
        reader = PdfReader(str(path))
        title = ""
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title).strip()
        title = title or path.stem.replace("_", " ").replace("-", " ")
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


def _proof_habit(text):
    """Short original replies in the style of a proof book: define, then conclude."""
    lowered = re.sub(r"\s+", " ", text.lower()).strip()

    if "contrapositive" in lowered:
        return (
            "The contrapositive of 'if P, then Q' is 'if not Q, then not P'. "
            "It is equivalent to the original implication. "
            "Example: 'if n is divisible by 4, then n is even' has contrapositive "
            "'if n is not even, then n is not divisible by 4'. "
            "The converse, 'if n is even, then n is divisible by 4', is a different statement and is false (n = 2)."
        )
    if "converse" in lowered and "even" in lowered:
        return (
            "The converse swaps the hypothesis and the conclusion. "
            "'If n is divisible by 4, then n is even' is true. "
            "Its converse, 'if n is even, then n is divisible by 4', is false, because 2 is even and 2 is not divisible by 4."
        )
    if "if and only if" in lowered or re.search(r"\biff\b", lowered):
        return (
            "An if-and-only-if statement is two proofs. "
            "For 'n is even if and only if n squared is even': "
            "first assume n = 2k and show n squared = 4k squared, which is even; "
            "then assume n squared is even and show n cannot be odd, because an odd number squares to an odd number. "
            "Both directions together are the equivalence."
        )
    if "contradiction" in lowered or "irrational" in lowered or "square root of 2" in lowered or "sqrt(2)" in lowered or "√2" in text:
        return (
            "Proof by contradiction starts by assuming the opposite of what you want. "
            "To show that the square root of 2 is irrational, assume it equals a/b in lowest terms. "
            "Then a squared = 2 b squared, so a is even, write a = 2k, and get b squared = 2 k squared, so b is even too. "
            "Both a and b are even, which contradicts lowest terms. So no such fraction exists."
        )
    if "induction" in lowered:
        return (
            "A proof by induction has two steps. "
            "Base case: check the statement at the starting number, usually n = 1. "
            "Inductive step: assume it is true for some n = k (the inductive hypothesis), and prove it for n = k+1 using that assumption. "
            "For the sum 1+2+...+n = n(n+1)/2, the base case is 1 = 1·2/2. "
            "If the sum to k equals k(k+1)/2, then the sum to k+1 equals that plus (k+1), which simplifies to (k+1)(k+2)/2."
        )
    if "subset" in lowered or "element of" in lowered:
        return (
            "A set is a collection of objects, and 'x is an element of A' means x is one of those objects. "
            "A is a subset of B when every element of A is also an element of B. "
            "To prove A ⊆ B, take an arbitrary x in A and show x is in B. "
            "To prove A = B, prove both A ⊆ B and B ⊆ A."
        )
    if "for all" in lowered or "there exists" in lowered or "quantif" in lowered:
        return (
            "A universal statement 'for all x in S, P(x)' is proved by letting x be an arbitrary member of S and proving P(x) with nothing special assumed about x. "
            "An existence statement 'there exists x in S with P(x)' is proved by naming one witness that works. "
            "One counterexample kills a 'for all', but one example does not prove a 'for all'."
        )
    if re.search(r"\b(prove|show that)\b", lowered) and "even" in lowered:
        return (
            "Definition first: an integer is even when it equals 2k for some integer k. "
            "Let the two even integers be 2a and 2b. "
            "Their sum is 2a + 2b = 2(a+b), and a+b is an integer, so the sum is even. "
            "That is a direct proof: the definition was used, and the goal was the last line."
        )
    if re.search(r"\b(prove|show that|direct proof)\b", lowered):
        return (
            "A direct proof names the hypothesis, recalls the definition of each word in the goal, "
            "and writes a chain of equalities or implications that ends at the conclusion. "
            "Nothing is used that was not given or previously defined."
        )
    return None


def _is_reasoning_question(text):
    lowered = text.lower()
    if any(hint in lowered for hint in REASONING_HINTS):
        return True
    return bool(re.search(r"\b(why|how)\b", lowered)) and len(_tokens(text)) >= 3


def _from_books(message, passages):
    lines = ["Here is how I would work through that from the books on this machine.", ""]
    for _score, title, excerpt, page in passages:
        snippet = excerpt.strip()
        if len(snippet) > 500:
            snippet = snippet[:500].rsplit(" ", 1)[0] + "..."
        lines.append(f"From {title}, page {page}:")
        lines.append(snippet)
        lines.append("")
    lines.append(
        "Using that, start from the definitions in the passage, "
        "name what is given, and then take one step at a time toward what was asked."
    )
    return "\n".join(lines).strip()


def _reason_without_book(text):
    lowered = text.lower()
    steps = [
        "Let me treat this as a formal-math question and set it up before jumping to a claim.",
        "",
        f"Question: {text.strip()}",
        "",
        "1. Write the statement in symbols if it is not already: sets, quantifiers, or an implication P → Q.",
        "2. List what is given and what must be shown. Do not use a word until it has a definition.",
    ]
    if any(word in lowered for word in ("if and only if", "iff")):
        steps.append("3. An if-and-only-if needs both directions: assume P and derive Q, then assume Q and derive P.")
    elif "contrapositive" in lowered:
        steps.append("3. The contrapositive of P → Q is ¬Q → ¬P. Prove that, and the original implication follows.")
    elif "contradiction" in lowered:
        steps.append("3. Assume the claim is false, derive a statement and its negation, and that contradiction proves the claim.")
    elif "induction" in lowered:
        steps.append("3. For induction: check the base case, assume it holds for n, and derive it for n+1 from that assumption only.")
    elif any(word in lowered for word in ("for all", "there exists", "quantif")):
        steps.append("3. For ∀x, let x be an arbitrary element of the domain. For ∃x, produce one explicit witness.")
    elif any(word in lowered for word in ("set", "subset", "element")):
        steps.append("3. For A ⊆ B, take an arbitrary x ∈ A and show x ∈ B. For equality, show both inclusions.")
    else:
        steps.append("3. Prefer a direct proof. If that stalls, try the contrapositive, then proof by contradiction.")
    steps.append("4. End by stating that the goal has been reached, and name the definition or axiom each step used.")
    steps.append("")
    steps.append(
        "Place a formal-mathematics PDF in the books folder and I will quote the matching pages "
        "instead of only this outline."
    )
    return "\n".join(steps)
