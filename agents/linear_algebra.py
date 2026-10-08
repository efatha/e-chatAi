"""NumPy is the calculator for matrices. The reply explains what the numbers mean."""

import re

import numpy as np

SAMPLE = np.array([[2.0, 1.0], [1.0, 2.0]])


def answer(message):
    text = message or ""
    lowered = text.lower()
    if not _is_linear_question(lowered) and "[[" not in text:
        return None

    matrix = _extract_matrix(text)
    used_sample = matrix is None
    if used_sample:
        matrix = SAMPLE.copy()

    rows, cols = matrix.shape
    lines = [
        "How the matrix is stored. NumPy keeps it as a "
        f"{rows} by {cols} array of floating-point numbers, one row per inner list:",
        _format_matrix(matrix),
        "",
    ]

    if rows != cols:
        singular = np.linalg.svd(matrix, compute_uv=False)
        lines.append(
            "Eigenvalues need a square matrix, because they solve A v = λ v. "
            f"This array is {rows} by {cols}, so that equation is the wrong shape."
        )
        lines.append(
            "The singular values still describe how the matrix stretches vectors: "
            + ", ".join(_show(value) for value in singular)
            + "."
        )
        lines.append(_numerical_note(matrix))
        return _pack(lines)

    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    eigenvalues = np.real_if_close(eigenvalues, tol=1e8)
    lines.append("How the eigenvalues are computed. They are the roots of det(A − λ I) = 0.")
    lines.append("λ = " + ", ".join(_show(value) for value in eigenvalues) + ".")
    lines.append("")
    lines.append(
        "How the vectors are manipulated. Each column below is a direction v with A v = λ v. "
        "NumPy scales every column so its length is 1."
    )
    lines.append(_format_matrix(np.real_if_close(eigenvectors, tol=1e8)))
    if used_sample:
        lines.append("")
        lines.append(
            "That is the sample A = [[2, 1], [1, 2]]. "
            "Paste another square matrix in the same bracket form and I will run it the same way."
        )
    lines.append("")
    lines.append(_numerical_note(matrix, eigenvalues))
    return _pack(lines)


def _is_linear_question(lowered):
    hints = (
        "matrix", "matrices", "eigen", "eigenvector", "eigenvalue",
        "numpy", "vector", "singular value", "linalg",
    )
    return any(hint in lowered for hint in hints)


def _extract_matrix(text):
    match = re.search(r"\[\s*\[.*?\]\s*\]", text, re.DOTALL)
    if not match:
        return None
    rows = re.findall(r"\[([^\[\]]+)\]", match.group(0))
    data = []
    for row in rows:
        numbers = re.findall(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", row, flags=re.I)
        if not numbers:
            return None
        data.append([float(number) for number in numbers])
    widths = {len(row) for row in data}
    if not data or len(widths) != 1:
        return None
    return np.array(data, dtype=float)


def _numerical_note(matrix, eigenvalues=None):
    notes = [
        "Real numerical behavior. The entries are floats, not exact fractions, "
        "so a value that prints as 3 may be 2.9999999999999996 in memory."
    ]
    if eigenvalues is not None:
        imaginary = np.imag(np.asarray(eigenvalues, dtype=complex))
        if np.any(np.abs(imaginary) > 1e-8):
            notes.append(
                "Some eigenvalues are genuinely complex. A tiny imaginary part, near 1e-16, is rounding error and is dropped."
            )
        else:
            notes.append("A tiny imaginary part, near 1e-16, is rounding error and is dropped.")
    if matrix.shape[0] == matrix.shape[1]:
        condition = np.linalg.cond(matrix)
        if not np.isfinite(condition) or condition > 1e12:
            notes.append(
                "Edge case: this matrix is singular or nearly singular, so an inverse would amplify tiny input errors into large output errors."
            )
        elif condition > 1e4:
            notes.append(
                f"Edge case: the condition number is about {_show(condition)}, so small changes in the entries can move the answer."
            )
    return " ".join(notes)


def _format_matrix(matrix):
    rows = []
    for row in np.asarray(matrix):
        rows.append("[" + ", ".join(_show(value) for value in row) + "]")
    return "[" + ", ".join(rows) + "]" if len(rows) == 1 else "[\n  " + ",\n  ".join(rows) + "\n]"


def _show(value):
    number = complex(value)
    if abs(number.imag) < 1e-8:
        number = number.real
        if abs(number - round(number)) < 1e-8:
            return str(int(round(number)))
        return f"{number:.6g}"
    return f"{number.real:.4g}{number.imag:+.4g}i"


def _pack(lines):
    return {"response": "\n".join(lines).strip(), "source": "numpy", "provider": "numpy"}
