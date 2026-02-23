from flask import Flask, render_template, request, jsonify
import re
import ast
import operator
import os
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env

API_KEY = os.getenv("GEMINI_API_KEY")
API_URL = os.getenv("API_BASE_URL")

app = Flask(__name__)

# ===============================
# FRONTEND ROUTES
# ===============================

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/e-Chat")
def chat():
    return render_template("e-Chat.html", api_key=API_KEY, api_url=API_URL)

@app.route("/login")
def login():
    return render_template("login.html")


# ===============================
# SAFE MATH ENGINE
# ===============================

OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}

def contains_math_operation(text):
    return bool(re.search(r'[\d+\-*/().%^]', text))

def evaluate_expression(expr):
    expr = expr.replace("^", "**")

    def eval_node(node):
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            return OPERATORS[type(node.op)](
                eval_node(node.left),
                eval_node(node.right)
            )
        elif isinstance(node, ast.UnaryOp):
            return OPERATORS[type(node.op)](
                eval_node(node.operand)
            )
        else:
            raise ValueError("Unsupported expression")

    parsed = ast.parse(expr, mode='eval')
    return eval_node(parsed.body)


# ===============================
# API ROUTE (BRAIN)
# ===============================

@app.route("/brain", methods=["POST"])
def brain():
    data = request.get_json()
    message = data.get("message", "")

    if contains_math_operation(message):
        try:
            result = evaluate_expression(message)

            return jsonify({
                "response": f""" ✅ The answer to your math problem is:
{result}"""
            })

        except Exception:
            return jsonify({
                "response": "⚠️ I detected math but couldn't evaluate safely.Try to type a math expression lonely without any extra text. For example: `2 + 2` or `sqrt(16)`."
            })

    # If not math, return None so frontend uses Gemini
    return jsonify({ "response": None })


# ===============================
# RUN SERVER
# ===============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)