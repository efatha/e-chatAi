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


def _parse_natural_language_math(text):
    text_lower = text.lower()
    operator_symbol = None
    for keyword in sorted(MATH_OPERATORS, key=len, reverse=True):
        if keyword in text_lower:
            operator_symbol = MATH_OPERATORS[keyword]
            break
    if not operator_symbol:
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

        if _contains_math_operation(text):
            try:
                result = _evaluate_expression(text)
                return _personalize(f"the result is {result}", username)
            except Exception:
                pass

        if _contains_math_keywords(text):
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
