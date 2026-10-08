"""Local agent. Answers from math, memory, and trained knowledge with no network."""

import ast
import operator
import re

OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}

MATH_OPERATORS = {
    "sum": "+",
    "add": "+",
    "plus": "+",
    "subtract": "-",
    "minus": "-",
    "difference": "-",
    "multiply": "*",
    "times": "*",
    "product": "*",
    "divide": "/",
    "division": "/",
    "divided by": "/",
    "power": "**",
    "to the power": "**",
    "modulo": "%",
    "mod": "%",
    "remainder": "%",
}

MEANING_PATTERNS = [
    r"(what is|what's|define|meaning of|tell me about|do you know)\s+(\w+)",
    r"(can you tell me about|explain)\s+(\w+)",
]
# These are not dictionary headwords. Leave the full question for the API agent.
SKIP_MEANING_WORDS = {"the", "a", "an", "my", "your", "this", "that", "it"}


def _personalize(text, username):
    if username:
        return f"{username}, {text}"
    return text


def _contains_math_operation(text):
    return bool(re.search(r"[\d+\-*/().%^]", text))


def _contains_math_keywords(text):
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in MATH_OPERATORS)


def _phrase_to_expr(phrase):
    """Turn a short arithmetic phrase into a safe expression, or return None."""
    text = phrase.lower().strip(" ?.!")
    text = text.replace("divided by", "/")
    text = text.replace("to the power", "**")
    replacements = (
        ("plus", "+"),
        ("added to", "+"),
        ("minus", "-"),
        ("times", "*"),
        ("multiplied by", "*"),
        ("over", "/"),
    )
    for word, symbol in replacements:
        text = re.sub(rf"\b{word}\b", symbol, text)
    text = re.sub(r"[^0-9+\-*/().\s*]", "", text)
    text = re.sub(r"\s+", "", text)
    if not text or not re.search(r"\d", text):
        return None
    if not re.fullmatch(r"[0-9+\-*/().]+", text):
        return None
    return text


def _spoken_arithmetic(text):
    """
    Resolve English arithmetic instead of treating it as an unknown sentence.
    'the half of 4 + 6' means half of the whole sum, (4+6)/2.
    'half of 4, plus 6' means (4/2)+6.
    """
    lowered = text.lower().strip()
    if re.search(r"\b(prove|proof|induction|contrapositive|contradiction|subset|quantif)\b", lowered):
        return None, None
    lowered = re.sub(
        r"^(what is|what's|whats|calculate|compute|find|how much is)\s+",
        "",
        lowered,
    ).strip(" ?.")

    percent = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(\d+(?:\.\d+)?)",
        lowered,
    )
    if percent:
        rate, whole = percent.group(1), percent.group(2)
        return f"({rate}/100)*({whole})", f"{rate}% of {whole}"

    unknown = _unknown_number(lowered)
    if unknown:
        return unknown

    split_half = re.fullmatch(
        r"(?:the\s+)?half of\s+(\d+(?:\.\d+)?)\s*,\s*(?:plus|\+|and)\s+(\d+(?:\.\d+)?)",
        lowered,
    )
    if split_half:
        left, right = split_half.group(1), split_half.group(2)
        expr = f"({left})/2+({right})"
        return expr, f"half of {left} only, then add {right}"

    whole_half = re.fullmatch(r"(?:the\s+)?half of\s+(.+)", lowered)
    if whole_half:
        inner = _phrase_to_expr(whole_half.group(1))
        if inner:
            return f"({inner})/2", f"half of the whole quantity {inner}"

    twice = re.fullmatch(r"(?:twice|double)\s+(.+)", lowered)
    if twice:
        inner = _phrase_to_expr(twice.group(1))
        if inner:
            return f"2*({inner})", f"twice the quantity {inner}"

    expr = _phrase_to_expr(lowered)
    if expr and re.search(r"[+\-*/]", expr):
        return expr, expr
    return None, None


def _unknown_number(text):
    """
    Recover n from the operation and the result, ignoring commas and wording.
    'multiplied by 3, and becomes 20' is the same fact as 'multiplied by 3 and becomes 20': n × 3 = 20.
    """
    flat = re.sub(r"[,:;]+", " ", text)
    flat = re.sub(r"\s+", " ", flat).strip()
    operations = (
        (r"multiplied by|times|multiplied with", "mul"),
        (r"divided by", "div"),
        (r"increased by|added by|added to|plus", "add"),
        (r"decreased by|subtracted by|reduced by|taken away|minus", "sub"),
    )
    found = None
    for pattern, kind in operations:
        match = re.search(rf"(?:{pattern})\s+(\d+(?:\.\d+)?)", flat)
        if match and (found is None or match.start() < found[0].start()):
            found = (match, kind)
        front = re.search(
            rf"(\d+(?:\.\d+)?)\s+(?:{pattern})\s+(?:a |the |that |some )?number",
            flat,
        )
        if front and (found is None or front.start() < found[0].start()):
            found = (front, kind)
    if not found:
        return None

    match, kind = found
    factor = match.group(1)
    result = re.search(
        r"(?:becomes|become|equals|equal|yields|gives|results in|comes to|is)\s+(\d+(?:\.\d+)?)",
        flat[match.end():],
    )
    if not result:
        return None
    total = result.group(1)
    if kind == "mul":
        return f"({total})/({factor})", f"n × {factor} = {total}, so n = {total}/{factor}"
    if kind == "div":
        return f"({total})*({factor})", f"n / {factor} = {total}, so n = {total} × {factor}"
    if kind == "add":
        return f"({total})-({factor})", f"n + {factor} = {total}, so n = {total} - {factor}"
    return f"({total})+({factor})", f"n - {factor} = {total}, so n = {total} + {factor}"


def _show_number(result):
    if isinstance(result, float):
        if abs(result - round(result)) < 1e-9:
            return str(int(round(result)))
        text = f"{result:.10f}".rstrip("0").rstrip(".")
        return text
    return str(result)


def _parse_natural_language_math(text):
    text_lower = text.lower()
    operator_symbol = None
    for keyword in sorted(MATH_OPERATORS, key=len, reverse=True):
        if keyword in text_lower:
            operator_symbol = MATH_OPERATORS[keyword]
            break
    if not operator_symbol:
        return None
    if re.search(r"\b(becomes|number|percent)\b|%", text_lower):
        return None

    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if len(numbers) < 2:
        return None

    num1 = float(numbers[0]) if "." in numbers[0] else int(numbers[0])
    num2 = float(numbers[1]) if "." in numbers[1] else int(numbers[1])
    return f"{num1}{operator_symbol}{num2}"


def _evaluate_expression(expr):
    expr = expr.replace("^", "**")

    def eval_node(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            return OPERATORS[type(node.op)](eval_node(node.left), eval_node(node.right))
        if isinstance(node, ast.UnaryOp):
            return OPERATORS[type(node.op)](eval_node(node.operand))
        raise ValueError("Unsupported expression")

    parsed = ast.parse(expr, mode="eval")
    return eval_node(parsed.body)


def _lookup_word(message, word_meanings):
    message_lower = message.lower()
    for pattern in MEANING_PATTERNS:
        match = re.search(pattern, message_lower)
        if not match:
            continue
        word = match.group(2)
        if word in SKIP_MEANING_WORDS:
            return None, False
        meaning = word_meanings.get(word)
        if meaning:
            return f"📖 {word.capitalize()}: {meaning}", True
        return f"🤔 Sorry, I don't know about '{word}' yet. You may teach me about it", False
    return None, False


class IndependentAgent:
    """Answers without calling an external API."""

    def __init__(self, trained_knowledge, word_meanings):
        self.trained_knowledge = trained_knowledge or []
        self.word_meanings = word_meanings or {}

    def confident_answer(self, message, username=None, history=None):
        """Return a local answer only when this agent actually knows it."""
        history = history or []
        text = message or ""
        lowered = text.lower()

        proof_question = bool(re.search(
            r"\b(prove|proof|induction|contrapositive|contradiction|subset|quantif)\b",
            lowered,
        ))

        spoken_expr, reading = (None, None) if proof_question else _spoken_arithmetic(text)
        if spoken_expr:
            try:
                result = _evaluate_expression(spoken_expr)
                reply = (
                    f"I read that as {reading}. "
                    f"{spoken_expr} = {_show_number(result)}."
                )
                return _personalize(reply, username)
            except Exception:
                pass

        if _contains_math_operation(text) and not proof_question:
            try:
                result = _evaluate_expression(text)
                return _personalize(f"the result is {result}", username)
            except Exception:
                pass

        if _contains_math_keywords(text) and not proof_question:
            try:
                math_expr = _parse_natural_language_math(text)
                if math_expr:
                    result = _evaluate_expression(math_expr)
                    return _personalize(f"the result is {result}", username)
            except Exception:
                return _personalize(
                    "I couldn't evaluate that math. Try with digits and operators only.",
                    username,
                )

        if re.search(r"\b(hi|hello|hey)\b", lowered):
            if username:
                return f"👋 Hello {username}! How can I help you today?"
            return "👋 Hello! How can I help you today?"

        if "my name" in lowered:
            if username:
                return f"😊 Your name is {username}, right?"
            return "I don't know your name yet."

        for item in self.trained_knowledge:
            if any(keyword in lowered for keyword in item.get("keywords", [])):
                return _personalize(item.get("response"), username)

        if any(q in lowered for q in (
            "do you remember",
            "what did i say",
            "repeat what i said",
            "can you repeat",
        )):
            previous = history[:-1] if history else []
            if previous:
                safe_previous = [str(item) for item in previous[-3:]]
                return _personalize(
                    "I remember you said: " + ", ".join(safe_previous),
                    username,
                )
            return _personalize("I don't have anything to remember yet.", username)

        return None

    def fallback(self, message, username=None, history=None):
        """Used when the API agent is offline and no confident local answer exists."""
        meaning, found = _lookup_word(message or "", self.word_meanings)
        if meaning and not found:
            return _personalize(meaning, username)
        return _personalize("I don't know yet. I'm still learning!", username)
