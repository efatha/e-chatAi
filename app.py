from flask import Flask, render_template, request, jsonify
import re
import ast
import operator
import os
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env
import json
import os

# Load the data.json file
with open("data.json", "r", encoding="utf-8") as f:
    DATA = json.load(f)

TRAINED_KNOWLEDGE = DATA.get("trained_knowledge", [])
WORD_MEANINGS = DATA.get("word_meanings", {})
API_KEY = os.getenv("GEMINI_API_KEY")
API_URL = os.getenv("API_BASE_URL")

app = Flask(__name__)

# FRONTEND ROUTES

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/e-Chat")
def chat():
    return render_template("e-Chat.html", api_key=API_KEY, api_url=API_URL)

@app.route("/login")
def login():
    return render_template("login.html")

# SAFE MATH ENGINE

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


# API ROUTE (BRAIN)
# TRAINED KNOWLEDGE & WORD MEANINGS
import re

def get_trained_response(message):
    """Check if message matches any trained knowledge keywords."""
    msg_lower = message.lower()
    for item in TRAINED_KNOWLEDGE:
        if any(keyword in msg_lower for keyword in item.get("keywords", [])):
            return item.get("response")
    return None

def get_word_meaning(message):
    """Detect word queries and return meanings from WORD_MEANINGS."""
    message_lower = message.lower()
    
    # Regex patterns for various question forms
    patterns = [
        r"(what is|what's|define|meaning of|tell me about|do you know)\s+(\w+)",
        r"(can you tell me about|explain)\s+(\w+)"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if match:
            word = match.group(2)
            meaning = WORD_MEANINGS.get(word)
            if meaning:
                return f"📖 {word.capitalize()}: {meaning}"
            else:
                return f"🤔 Sorry, I don't know about '{word}' yet. You may teach me about it"
    
    return None

@app.route("/brain", methods=["POST"])
def brain():
    data = request.get_json()
    message = data.get("message", "")

    # 1️⃣ Check math first
    if contains_math_operation(message):
        try:
            result = evaluate_expression(message)
            return jsonify({"response": f"✅ Math result: {result}"})
        except:
            return jsonify({"response": "⚠️ I detected math but couldn't evaluate safely.Try to type a math expression lonely without any extra text. For example: `2 + 2` or `sqrt(16)`"})

    # 2️⃣ Check trained knowledge
    trained_response = get_trained_response(message)
    if trained_response:
        return jsonify({"response": trained_response})

    # 3️⃣ Check word meanings
    meaning_response = get_word_meaning(message)
    if meaning_response:
        return jsonify({"response": meaning_response})

    # 4️⃣ Default fallback
    return jsonify({"response": "🤖 I don't know yet. I'm still learning!"})

# RUN SERVER

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)