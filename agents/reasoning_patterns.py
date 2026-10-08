"""Structured reasoning for questions that are not a single calculation.

Each pattern names the claim, the evidence, and a check. The local books
stay available for proof questions; they are not replaced by these patterns.
"""

import re


def pattern_answer(message, notes=None, excerpts=None):
    text = (message or "").strip()
    if not text:
        return None
    lowered = re.sub(r"\s+", " ", text.lower()).strip(" ?.")
    notes = notes or {}
    excerpts = excerpts or []
    builders = (
        _comparison,
        _counterexample,
        _error_analysis,
        _debugging,
        _business,
        _engineering,
        _case_study,
        _proof,
    )
    for builder in builders:
        reply = builder(lowered, text, notes)
        if reply:
            reply = _with_sources(reply, notes, excerpts)
            return {"response": reply, "source": "pattern", "provider": "reasoning-pattern"}
    return None


def concept_terms(message):
    """The concepts to look up, or None when the message is not one of these patterns."""
    text = (message or "").strip()
    if not text:
        return None
    lowered = re.sub(r"\s+", " ", text.lower()).strip(" ?.")
    if _pair(lowered) or re.search(r"\b(better than|worse than|advantages? of|compare)\b", lowered):
        pair = _pair(lowered)
        return list(pair) if pair else []
    if any((
        re.search(r"counterexample|is it always|does this always|is this always true|find a case where", lowered),
        re.search(r"where is the mistake|what is wrong|error analysis|flaw in|bug in the proof|incorrect step", lowered),
        re.search(r"\b(debug|debugging|crash|stack trace|exception|does not work|doesn't work|fails when|bug)\b", lowered),
        re.search(r"\b(sales|revenue|customers?|market|profit|pricing|competitor|store)\b", lowered),
        re.search(r"\b(design|latency|throughput|load|capacity|bridge|circuit|sensor|manufactur)\b", lowered),
        re.search(r"case study|what went wrong|what happened when|postmortem|retrospective", lowered),
        re.search(r"\b(prove|proof|show that)\b", lowered),
    )):
        return []
    return None


def _comparison(lowered, text, notes):
    pair = _pair(lowered)
    if not pair and not re.search(r"\b(better than|worse than|advantages? of|compare)\b", lowered):
        return None
    if not pair:
        return None
    left, right = pair
    left_note = notes.get(left) or ""
    right_note = notes.get(right) or ""
    left_used = set()
    right_used = set()
    left_line = _take_sentence(left_note, left_used) or f"I do not have a source page for {left} yet, so I will not invent its definition."
    right_line = _take_sentence(right_note, right_used) or f"I do not have a source page for {right} yet, so I will not invent its definition."
    direction = "better" if "better" in lowered else "the difference"
    return (
        f"Comparison. I chose the sense that can actually be compared, then read each page once.\n"
        f"{left}: {left_line}\n"
        f"{right}: {right_line}\n\n"
        f"Advantages. {_side_point(left, left_note, _ADVANTAGE_CUES, 'what it can do', left_used)}\n"
        f"{_side_point(right, right_note, _ADVANTAGE_CUES, 'what it can do', right_used)}\n\n"
        f"Limitations. {_side_point(left, left_note, _LIMIT_CUES, 'where it stops', left_used)}\n"
        f"{_side_point(right, right_note, _LIMIT_CUES, 'where it stops', right_used)}\n\n"
        f"Direction. Words only in {left}: {_only_words(left_note, right_note)}. "
        f"Words only in {right}: {_only_words(right_note, left_note)}. "
        f"I pick {left} when the task needs its words, and {right} when it needs the other list."
    )


def _counterexample(lowered, text, notes):
    if not re.search(r"counterexample|is it always|does this always|is this always true|find a case where", lowered):
        return None
    return (
        "Claim. One example never proves a 'for all', but one counterexample refutes it.\n\n"
        "Counterexample. I look for a single case that meets the hypothesis and misses the conclusion. "
        "For 'every even number is divisible by 4', n = 2 is even and 4 does not divide 2.\n\n"
        "Check. State the hypothesis, state the failed conclusion, and stop. No further cases are required once one witness exists."
    )


def _error_analysis(lowered, text, notes):
    if not re.search(r"where is the mistake|what is wrong|error analysis|flaw in|bug in the proof|incorrect step", lowered):
        return None
    return (
        "Error analysis. I read the argument as a chain of steps and mark the first step that does not follow.\n\n"
        "What failed. A common break is using the converse instead of the implication, dividing by a quantity that might be zero, "
        "or treating a local minimum as a global one.\n\n"
        "Repair. Replace that step with a justification that names the definition it uses. "
        "The steps before the break can stay; the steps after it have to be checked again."
    )


def _debugging(lowered, text, notes):
    if not re.search(r"\b(debug|debugging|crash|stack trace|exception|does not work|doesn't work|fails when|bug)\b", lowered):
        return None
    return (
        "What is failing. Name the input, the action, and the wrong result before changing any code.\n\n"
        "Hypotheses.\n"
        "- The input is not the shape the next step assumes.\n"
        "- A recent change altered one branch and left another branch stale.\n"
        "- An error is caught and replaced with a vague message, so the real failure is hidden.\n\n"
        "Tests.\n"
        "- Reproduce it with the smallest input that still fails.\n"
        "- Check the value just before and just after the suspected line.\n"
        "- Try the same input on the previous working version.\n\n"
        "Next step. Fix only the first broken assumption, then rerun that smallest input."
    )


def _business(lowered, text, notes):
    if not re.search(r"\b(sales|revenue|customers?|market|profit|pricing|competitor|store)\b", lowered):
        return None
    if re.search(r"\b(drop|dropped|decline|fell|down|loss|losing)\b", lowered):
        hypotheses = ["Price increase", "New competitor", "Seasonality"]
        tests = ["Compare prices with last period", "Analyze traffic and where it went", "Review customer feedback for a repeated complaint"]
        situation = "Sales fell, and more than one cause can produce the same drop."
    else:
        hypotheses = ["A change in price or offer", "A change in who the customer is", "A change outside the store, such as season or a competitor"]
        tests = ["Compare the numbers before and after the change", "Split the result by customer type", "Check whether the same pattern appears in a period with no internal change"]
        situation = "A business result has several plausible causes, so I separate them before picking one."
    return _hypotheses(situation, hypotheses, tests)


def _engineering(lowered, text, notes):
    if not re.search(r"\b(design|latency|throughput|load|capacity|bridge|circuit|sensor|manufactur)\b", lowered):
        return None
    return _hypotheses(
        "An engineering outcome can fail for a design reason, a load reason, or a measurement reason.",
        ["The design assumption does not match the real load", "A component is operating past its rated range", "The measurement itself is noisy or delayed"],
        ["Compare the assumed load with the measured load", "Inspect the component that sits nearest its limit", "Repeat the measurement with a second instrument"],
    )


def _case_study(lowered, text, notes):
    if not re.search(r"case study|what went wrong|what happened when|postmortem|retrospective", lowered):
        return None
    return (
        "Case. State the setting, the decision that was taken, and the outcome that followed.\n\n"
        "What the case shows. Separate the facts from the explanation. "
        "A single project can illustrate a mechanism, but it does not prove the mechanism always holds.\n\n"
        "What to carry out. Name one decision you would repeat and one you would change, and say which fact supports each."
    )


def _proof(lowered, text, notes):
    if not re.search(r"\b(prove|proof|show that)\b", lowered):
        return None
    if re.search(r"\b(even|contrapositive|induction|contradiction|subset|if and only if)\b", lowered):
        return None
    return (
        "Given. Write the hypotheses in symbols before the prose.\n\n"
        "Goal. Write the claim as an implication, a subset, or a quantified statement.\n\n"
        "Proof. Each line is given, a definition, or a consequence of earlier lines. "
        "The last line is the goal, and it names the definition it used."
    )


_ADVANTAGE_CUES = (
    "efficient", "optimal", "guarantee", "exact", "simple", "fast", "robust",
    "allows", "useful", "scal", "probability", "likely", "evidence", "update",
)
_LIMIT_CUES = (
    "cannot", "can't", "only", "local", "fail", "difficult", "expensive",
    "assume", "not always", "slow", "intractable", "approximate", "may not",
    "limited", "however", "although", "drawback", "does not", "uncertain",
    "prior", "noise",
)
_SKIP_CONTENT = {
    "that", "this", "with", "from", "into", "which", "their", "there", "about",
    "when", "where", "what", "than", "then", "also", "such", "using", "used",
    "wikipedia", "between", "other", "these", "those", "have", "been", "being",
}


def _sentences(note):
    if not note:
        return []
    body = " ".join(
        line.strip() for line in note.splitlines()
        if line.strip() and not line.lower().startswith("wikipedia")
    )
    parts = re.split(r"(?<=[.!?])\s+", body)
    return [part.strip() for part in parts if len(part.split()) >= 6]


def _take_sentence(note, used):
    for sentence in _sentences(note):
        if sentence not in used:
            used.add(sentence)
            return sentence
    return None


def _side_point(name, note, cues, missing, used):
    ranked = []
    for sentence in _sentences(note):
        if sentence in used:
            continue
        score = sum(1 for cue in cues if cue in sentence.lower())
        if score:
            ranked.append((score, sentence))
    if ranked:
        ranked.sort(key=lambda item: item[0], reverse=True)
        used.add(ranked[0][1])
        return f"{name}: {ranked[0][1]}"
    for sentence in _sentences(note):
        if sentence not in used:
            used.add(sentence)
            return f"{name}: {sentence}"
    return f"{name}: the sources do not say {missing}."


def _only_words(note, other):
    words = set(_content_words(note)) - set(_content_words(other))
    picked = sorted(words)[:6]
    if not picked:
        return "none that the other side does not also use"
    return ", ".join(picked)


def _content_words(note):
    return [
        word for word in re.findall(r"[a-z]{5,}", (note or "").lower())
        if word not in _SKIP_CONTENT
    ]


def _meaning(note):
    if not note:
        return None
    lines = [line.strip() for line in note.splitlines() if line.strip() and not line.startswith("Wikipedia")]
    body = " ".join(lines)
    sentence = re.split(r"(?<=[.])\s", body)[0]
    return sentence[:420]


def _with_sources(reply, notes, excerpts):
    blocks = [reply]
    sourced = [f"{name}: {note}" for name, note in notes.items() if note]
    if sourced or excerpts:
        blocks.append("")
        blocks.append("Sources used for this comparison:")
        blocks.extend(sourced)
        blocks.extend(excerpts)
    return "\n".join(blocks)


def _hypotheses(situation, hypotheses, tests):
    hypo = "\n".join(f"- {item}" for item in hypotheses)
    check = "\n".join(f"- {item}" for item in tests)
    return (
        f"{situation}\n\n"
        f"Hypotheses.\n{hypo}\n\n"
        f"Tests.\n{check}\n\n"
        "I do not pick a cause until one of those tests favors it and the others do not."
    )


def _pair(lowered):
    patterns = (
        r"why (?:is|are) (.+?) better than (.+)",
        r"why (?:is|are) (.+?) worse than (.+)",
        r"(.+?) better than (.+)",
        r"(?:compare|comparison of|difference between) (.+?) (?:and|vs\.?|versus|with) (.+)",
        r"(.+?) (?:vs\.?|versus) (.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        left = match.group(1).strip(" ?.!")
        right = match.group(2).strip(" ?.!")
        if left and right and left != right:
            return left, right
    return None
