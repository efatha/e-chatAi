"""Reasoning agent backed by local books.

Drop a PDF in the books folder. It is indexed on this machine and is not
committed. More PDFs can be added later; each file becomes another book.
"""

import logging
import math
import pickle
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
    "compare", "versus", "difference", "tradeoff", "prefer", "better",
    "linear", "matrix", "vector", "convex", "gradient", "eigen",
    "bayes", "posterior", "prior", "likelihood",
    "variance", "statistic", "statistics", "hypothesis", "distribution", "confidence",
)


class BookAgent:
    def __init__(self, books_dir=BOOKS_DIR):
        self.books_dir = Path(books_dir)
        self.books = []
        self._idf = {}
        self.refresh()

    def refresh(self):
        self.books = []
        self._idf = {}
        if not self.books_dir.exists():
            return
        pdfs = sorted(self.books_dir.glob("*.pdf"))
        signature = [
            (path.name, path.stat().st_size)
            for path in pdfs
        ]
        cached = _load_cache(self.books_dir, signature)
        if cached:
            self.books, self._idf = cached
            return
        for path in pdfs:
            book = _read_pdf(path)
            if book and book["chunks"]:
                self.books.append(book)
        self._idf = _idf_table(self.books)
        _save_cache(self.books_dir, signature, self.books, self._idf)
        if not self.books:
            logger.warning("No local books were loaded from %s", self.books_dir)

    def answer(self, message):
        text = (message or "").strip()
        if not text:
            return None

        habit = _proof_habit(text)
        passages = self._from_each_book(text)
        if not passages and not habit:
            return None
        return {
            "response": _speak(text, habit, passages),
            "source": "book",
            "provider": "both-books",
        }

    def _from_each_book(self, message):
        """Top passages by how rare the question's words are in that page."""
        query = _tokens(message)
        if "statistic" in (message or "").lower():
            query = set(query) | {"probability", "statistics"}
        if not query or not self.books:
            return []
        ranked = []
        rarest = max(query, key=lambda token: self._idf.get(token, 0))
        for book in self.books:
            best = None
            for chunk in book["chunks"]:
                if not _on_topic(message, book["title"], chunk["text"]):
                    continue
                score = _tfidf(query, chunk["tokens"], self._idf)
                if rarest in chunk["tokens"]:
                    score += self._idf.get(rarest, 0)
                if "statistic" in (message or "").lower() and "statistic" in book["title"].lower():
                    score += 3
                if chunk["text"].count(" . ") > 6 or chunk["text"].lower().count("chapter") >= 3:
                    score *= 0.1
                if best is None or score > best[0]:
                    best = (score, chunk["text"], chunk["page"])
            if best and best[0] >= 4:
                ranked.append((best[0], book["title"], best[2], _clip(best[1])))
        ranked.sort(key=lambda item: item[0], reverse=True)
        kept = ranked[:1]
        if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] * 0.72:
            kept.append(ranked[1])
        return [(title, page, snippet) for _score, title, page, snippet in kept]

    def excerpts(self, message):
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


def _rephrase(text):
    """Say the question back once, in a form that can be answered."""
    body = re.sub(r"\s+", " ", text or "").strip(" ?.!")
    body = re.sub(
        r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?(?:explain\s+|tell me\s+)?",
        "",
        body,
        flags=re.IGNORECASE,
    ).strip()
    if not body:
        return "Restated once: say the claim you want checked."
    sentence = body[0].upper() + body[1:]
    if not sentence.endswith("."):
        sentence += "."
    return f"Restated once: {sentence}"


def _logic_line(text):
    """A definition or a symbol form, only when the question names that idea."""
    lowered = (text or "").lower()
    forms = (
        ("contrapositive", "Definition. The contrapositive of P → Q is ¬Q → ¬P. They are the same claim: (P → Q) ↔ (¬Q → ¬P)."),
        ("converse", "Definition. The converse of P → Q is Q → P. It is a different claim."),
        ("if and only if", "Definition. P ↔ Q means (P → Q) ∧ (Q → P)."),
        ("biconditional", "Definition. P ↔ Q means (P → Q) ∧ (Q → P)."),
        ("contradiction", "Definition. A proof by contradiction assumes the denial of the goal and derives ⊥."),
        ("induction", "Definition. Induction: prove P(0), then ∀k (P(k) → P(k+1)), hence ∀n P(n)."),
        ("posterior", "Definition. The posterior is P(A|B) = P(B|A) P(A) / P(B). P(A) is the prior."),
        ("prior", "Definition. The prior is P(A), the belief before the evidence B. The posterior is P(A|B)."),
        ("likelihood", "Definition. The likelihood of a hypothesis A given evidence B is P(B|A)."),
        ("subspace", "Definition. A subspace is closed under addition and scalar multiplication, so it contains 0."),
        ("basis", "Definition. A basis of V is a linearly independent list that spans V."),
        ("span", "Definition. span(v₁,…,vₙ) = {a₁v₁ + … + aₙvₙ}."),
        ("eigen", "Definition. A v = λ v, with v ≠ 0. λ is an eigenvalue and v is an eigenvector."),
        ("convex", "Definition. C is convex when ∀x,y ∈ C and ∀t ∈ [0,1], t x + (1−t) y ∈ C."),
        ("variance", "Definition. Variance is the expected squared distance from the mean: Var(X) = E[(X − E[X])²]."),
        ("confidence interval", "Definition. A confidence interval is a range computed from the sample that is claimed to cover the population parameter in a stated fraction of repeated samples."),
        ("priority", "Definition. In a statistics question, priority is read as probability: a number from 0 to 1 for how often an outcome happens over many repetitions."),
        ("probability", "Definition. A probability is a number from 0 to 1 for how often an outcome happens over many repetitions."),
    )
    for needle, line in forms:
        if re.search(rf"\b{re.escape(needle)}\b", lowered):
            return line
    return ""


def _speak(text, habit, passages):
    lines = [_rephrase(text), ""]
    logic = _logic_line(text)
    if logic:
        lines.append(logic)
        lines.append("")
    if habit:
        lines.append(habit)
    elif passages:
        lines.append("I am answering from the page that uses these words, then saying what that page commits me to.")
    else:
        lines.append("I will treat this as a claim to be proved, not a guess.")
    if passages:
        lines.append("")
        lines.append("Reference.")
        for title, page, snippet in passages:
            lines.append(f"• _{title}, p. {page}_: {snippet}")
    lines.append("")
    lines.append(
        "In ordinary speech: the restatement is the claim, the definition is the rule, "
        "and the page is the place I took the words from."
    )
    return "\n".join(lines).strip()


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
    return (
        f"What they are. {left} is one defined object or method. {right} is the other. "
        f"I will not collapse them into one idea just because the question names both.\n\n"
        f"Where they agree. Both earn a conclusion only after their definitions are met. "
        f"A symbol such as → or ⊆ is just the sharp form of that requirement.\n\n"
        f"Where they differ. {left} and {right} ask different questions, so a step that is valid for one can be invalid for the other.\n\n"
        f"The tradeoff. {left} is the shorter path when its hypotheses are already given. "
        f"{right} takes an extra step and is worth it when the short path is blocked.\n\n"
        f"When one is preferable. I use {left} when the given information matches its hypotheses. "
        f"I use {right} when those hypotheses are missing, or when the goal is a denial, a minimum, or a different structure.\n\n"
        f"Why that conclusion. A preference without a matching definition is only a taste. "
        f"The justified choice is the one whose hypotheses are actually in hand."
    )


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
