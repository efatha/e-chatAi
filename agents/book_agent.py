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
        passages = self._from_each_book(text)
        if habit or passages or _is_reasoning_question(text):
            return {
                "response": _speak(habit, passages),
                "source": "book",
                "provider": "both-books",
            }
        return None

    def _from_each_book(self, message):
        """Best matching passage from each PDF, so both books can speak."""
        query = _tokens(message)
        if not query or not self.books:
            return []
        chosen = []
        for book in self.books:
            best = None
            for chunk in book["chunks"]:
                overlap = query & chunk["tokens"]
                score = len(overlap)
                focused = FOCUS & query
                if focused & chunk["tokens"]:
                    score += 6
                elif focused:
                    score -= 2
                if best is None or score > best[0]:
                    best = (score, chunk["text"], chunk["page"])
            if best and best[0] >= 2:
                chosen.append((book["title"], best[2], _clip(best[1])))
        return chosen


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
        title = title or _display_title(path)
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


def _display_title(path):
    key = path.stem.lower()
    if "bookofproof" in key.replace("-", "").replace("_", ""):
        return "Book of Proof"
    if "how-to-prove-it" in key or "howtoproveit" in key.replace("-", ""):
        return "How to Prove It"
    return path.stem.replace("_", " ").replace("-", " ")


def _clip(text, limit=240):
    snippet = re.sub(r"\s+", " ", text).strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit].rsplit(" ", 1)[0] + "..."


def _speak(habit, passages):
    lines = []
    if habit:
        lines.append(habit)
    else:
        lines.append(
            "Given the wording of your question, I will treat it as a claim to be proved, not a guess."
        )
    if passages:
        lines.append("")
        lines.append("Both local books are in use:")
        for title, page, snippet in passages:
            lines.append(f"• {title}, p. {page}: {snippet}")
    lines.append("")
    lines.append("I will stand on that reading: symbols first, then the proof, then the conclusion.")
    return "\n".join(lines).strip()


def looks_like_reasoning(text):
    return _is_reasoning_question(text) or _proof_habit(text) is not None


def _proof_habit(text):
    """Symbolic proof talk. The wording is original; the books only supply support."""
    lowered = re.sub(r"\s+", " ", text.lower()).strip()

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
        return (
            "Given P → Q. The contrapositive is ¬Q → ¬P, and (P → Q) ↔ (¬Q → ¬P).\n"
            "Example: (4 | n) → Even(n). Contrapositive: ¬Even(n) → ¬(4 | n).\n"
            "The converse Q → P is a different claim. Even(n) → (4 | n) is false, since n = 2 is a counterexample."
        )
    if "converse" in lowered:
        return (
            "The converse of P → Q is Q → P. They are not equivalent.\n"
            "(4 | n) → Even(n) is true. Even(n) → (4 | n) is false: n = 2 is even and 4 does not divide 2."
        )
    if "if and only if" in lowered or re.search(r"\biff\b", lowered) or "↔" in text or "<->" in lowered:
        return (
            "P ↔ Q means (P → Q) ∧ (Q → P). Both directions are required.\n"
            "Even(n) ↔ Even(n²): if n = 2k then n² = 4k², so n² is even. "
            "If n is odd then n² is odd, so the other direction is the contrapositive of 'odd squares stay odd'."
        )
    if "contradiction" in lowered or "irrational" in lowered or "square root of 2" in lowered or "sqrt(2)" in lowered or "√2" in text:
        return (
            "To prove R, assume ¬R and reach S ∧ ¬S.\n"
            "Assume √2 = a/b in lowest terms. Then a² = 2b², so a is even, a = 2k, hence b² = 2k², so b is even. "
            "Thus 2 | a and 2 | b, contradicting lowest terms. ∴ √2 is irrational."
        )
    if "cases" in lowered:
        return (
            "A proof by cases splits the hypothesis into an exhaustive list.\n"
            "Given P ∨ Q, and both P → R and Q → R, conclude R.\n"
            "For an integer n, the cases n even and n odd cover every integer, so a claim proved in both cases holds for all n."
        )
    if "induction" in lowered:
        return (
            "Given a statement P(n) for integers n ≥ 1. Goal: ∀n P(n).\n"
            "Base: P(1). Inductive step: P(k) → P(k+1).\n"
            "For Σ_{i=1}^{n} i = n(n+1)/2, P(1) is 1 = 1. "
            "If the sum to k equals k(k+1)/2, the sum to k+1 equals that plus (k+1) = (k+1)(k+2)/2. ∴ P(k+1)."
        )
    if "subset" in lowered or "∈" in text or "⊆" in text:
        return (
            "x ∈ A means x is a member of A. A ⊆ B means ∀x (x ∈ A → x ∈ B).\n"
            "To prove A ⊆ B, let x be arbitrary, assume x ∈ A, and show x ∈ B. "
            "A = B means (A ⊆ B) ∧ (B ⊆ A)."
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
            "Given Even(a) ∧ Even(b). Then a = 2m and b = 2n, so a + b = 2(m+n). "
            "m+n ∈ Z, hence Even(a+b). ∴ the sum of two even integers is even."
        )
    if re.search(r"\b(prove|show that|direct proof|symbol)\b", lowered):
        return (
            "Structured proof, the way both books train it.\n"
            "Given: the hypotheses. Goal: the claim.\n"
            "Write the goal as symbols (→, ↔, ∀, ∃, ∈, ⊆) before the prose. "
            "Each line is either given, a definition, or a consequence of earlier lines. The last line is the goal."
        )
    return None


def _is_reasoning_question(text):
    lowered = text.lower()
    if any(hint in lowered for hint in REASONING_HINTS):
        return True
    if re.search(r"[∀∃∈⊆∧∨¬→↔√]", text):
        return True
    return bool(re.search(r"\b(why|how)\b", lowered)) and len(_tokens(text)) >= 3
