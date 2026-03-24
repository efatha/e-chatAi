from flask import Flask, render_template, request, jsonify
import re
import ast
import operator
import os
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env
import json
from flask import session

# Load the data.json file
with open("data.json", "r", encoding="utf-8") as f:
    DATA = json.load(f)

TRAINED_KNOWLEDGE = DATA.get("trained_knowledge", [])
WORD_MEANINGS = DATA.get("word_meanings", {})
API_KEY = os.getenv("GEMINI_API_KEY")
API_URL = os.getenv("API_BASE_URL")

app = Flask(__name__)

# FRONTEND ROUTES
app.secret_key = "supersecret"

@app.route('/get-username', methods=['POST'])
def get_username():
    data = request.get_json()
    session['username'] = data.get('username')
    session['email'] = data.get('email')
    session.modified = True
    return jsonify({"status": "saved"})

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

# TRAINED KNOWLEDGE & WORD MEANINGS
def get_trained_response(message):
    msg_lower = message.lower()
    for item in TRAINED_KNOWLEDGE:
        if any(keyword in msg_lower for keyword in item.get("keywords", [])):
            return item.get("response")
    return None

def get_word_meaning(message):
    message_lower = message.lower()
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

# API ROUTE (BRAIN)
@app.route("/brain", methods=["POST"])
def brain():
    data = request.get_json()
    message = data.get("message", "")
    username = session.get("username")

    def personalize(text):
        if username:
            return f"{username}, {text}"
        return text

    # STORE USER MESSAGE
    if "history" not in session:
        session["history"] = []

    session["history"].append(str(message))
    session.modified = True

    # 1️⃣ Math
    if contains_math_operation(message):
        try:
            result = evaluate_expression(message)
            return jsonify({"response": personalize(f"the result is {result}")})
        except:
            return jsonify({"response": personalize("I couldn't evaluate that math. Try with digits and operators only.")})

    # 2️⃣ Greetings
    if any(word in message.lower() for word in ["hi", "hello", "hey"]):
        if username:
            return jsonify({"response": f"👋 Hello {username}! How can I help you today?"})
        else:
            return jsonify({"response": "👋 Hello! How can I help you today?"})

    # 3️⃣ “my name” question
    if "my name" in message.lower():
        if username:
            return jsonify({"response": f"😊 Your name is {username}, right?"})
        else:
            return jsonify({"response": "I don't know your name yet."})

    # 4️⃣ Trained knowledge
    trained_response = get_trained_response(message)
    if trained_response:
        return jsonify({"response": personalize(trained_response)})

    # 5️⃣ Word meanings
    meaning_response = get_word_meaning(message)
    if meaning_response:
        return jsonify({"response": personalize(meaning_response)})

    # Memory questions (explicit)
    if any(q in message.lower() for q in [
        "do you remember",
        "what did i say",
        "repeat what i said",
        "can you repeat"
    ]):
        history = session.get("history", [])
        if len(history) > 1:
            previous = history[:-1]  # exclude current question
            safe_previous = [str(item) for item in previous[-3:]]  # last 3 messages
            return jsonify({"response": personalize("I remember you said: " + ", ".join(safe_previous))})
        else:
            return jsonify({"response": personalize("I don't have anything to remember yet.")})

    # 6️⃣ Default fallback + memory
    history = session.get("history", [])
    previous = history[:-1] if len(history) > 1 else []

    if previous:
        safe_previous = [str(item) for item in previous[-3:]]  # last 3 messages
        return jsonify({"response": personalize("I remember you said: " + ", ".join(safe_previous))})
    else:
        return jsonify({"response": personalize("I don't know yet. I'm still learning!")})

# RUN SERVER
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)