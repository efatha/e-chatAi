from flask import Flask, render_template, request, jsonify
import os
import secrets
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env
import json
from flask import session

from agents.router import answer_question, api_agent, book_agent, configure
from agents.memory import ConversationMemory

# Load the data.json file
with open("data.json", "r", encoding="utf-8") as f:
    DATA = json.load(f)

configure(DATA.get("trained_knowledge", []), DATA.get("word_meanings", {}))
memory = ConversationMemory(os.environ.get("MEMORY_DATABASE", "e_chat_memory.sqlite3"))

def _index_books():
    book_agent().refresh()

threading.Thread(target=_index_books, daemon=True).start()

app = Flask(__name__)

# FRONTEND ROUTES
def _local_secret_key():
    secret_file = Path(".flask-secret")
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()
    value = secrets.token_hex(32)
    secret_file.write_text(value, encoding="utf-8")
    return value


app.secret_key = os.environ.get("FLASK_SECRET_KEY") or _local_secret_key()
app.permanent_session_lifetime = timedelta(days=30)


def _conversation_id():
    session.permanent = True
    if "conversation_id" not in session:
        session["conversation_id"] = uuid4().hex
    return session["conversation_id"]

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
    return render_template("e-Chat.html")

@app.route("/login")
def login():
    return render_template("login.html")

def _chat_turn():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    file = data.get("file") if isinstance(data.get("file"), dict) else None
    browser_memory = data.get("memory") if isinstance(data.get("memory"), list) else []
    has_file = bool(file and file.get("data"))
    if not message and not has_file:
        return jsonify({"error": "message is required"}), 400

    conversation_id = _conversation_id()
    if not memory.recent(conversation_id, limit=1):
        for item in browser_memory[-40:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                memory.add(conversation_id, role, content)
    if message:
        memory.add(conversation_id, "user", message)

    history = [
        item["content"]
        for item in memory.recent(conversation_id, limit=20, role="user")
    ]

    recalled = memory.recall(conversation_id, message) if message and not has_file else None
    if recalled:
        result = {
            "response": recalled,
            "source": "memory",
            "provider": "local-sqlite",
        }
    else:
        result = answer_question(
            message=message,
            username=session.get("username"),
            history=history,
            file=file,
        )
    if result.get("response"):
        memory.add(conversation_id, "assistant", result["response"])
    return jsonify(result)


# Both routes share the two agents: local first, API when it is active.
@app.route("/ask", methods=["POST"])
@app.route("/brain", methods=["POST"])
def ask():
    return _chat_turn()


@app.route("/memory", methods=["GET", "DELETE"])
def conversation_memory():
    conversation_id = _conversation_id()
    if request.method == "DELETE":
        memory.clear(conversation_id)
        return jsonify({"status": "cleared"})
    return jsonify({"messages": memory.recent(conversation_id)})


@app.route("/grok", methods=["POST"])
def grok():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    agent = api_agent()
    if not agent.has_grok():
        return jsonify({"error": "Grok API is not configured"}), 503
    result = agent.grok_only(message)
    if not result:
        return jsonify({"error": "Grok API failed"}), 502
    return jsonify(result)

# RUN SERVER
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)