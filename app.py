from flask import Flask, render_template, request, jsonify
import os
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env
import json
from flask import session
from werkzeug.utils import secure_filename

from agents.router import answer_question, api_agent, book_agent, configure
from agents.book_agent import BOOKS_DIR

# Load the data.json file
with open("data.json", "r", encoding="utf-8") as f:
    DATA = json.load(f)

configure(DATA.get("trained_knowledge", []), DATA.get("word_meanings", {}))

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
    return render_template("e-Chat.html")

@app.route("/login")
def login():
    return render_template("login.html")


def _portal_key():
    return os.getenv("BOOK_PORTAL_KEY", "").strip()


def _portal_unlocked():
    key = _portal_key()
    sent = (request.form.get("key") or "").strip()
    if key and sent == key:
        session["book_portal"] = key
        session.modified = True
    return bool(key) and session.get("book_portal") == key


@app.route("/library", methods=["GET", "POST"])
def library():
    """Hidden upload. Not linked from the chat. Rebuilds the book index on this server."""
    message = ""
    if request.method == "POST" and _portal_unlocked() and request.files.get("pdf"):
        upload = request.files["pdf"]
        name = secure_filename(upload.filename or "")
        if not name.lower().endswith(".pdf"):
            message = "Only a PDF can be added."
        else:
            BOOKS_DIR.mkdir(parents=True, exist_ok=True)
            upload.save(BOOKS_DIR / name)
            book_agent().refresh()
            message = f"Indexed {name}."
    agent = book_agent()
    titles = [book.get("title") or "Untitled" for book in agent.books]
    return render_template(
        "library.html",
        configured=bool(_portal_key()),
        unlocked=_portal_unlocked(),
        titles=titles,
        count=len(titles),
        key=_portal_key() if _portal_unlocked() else "",
        message=message,
    )


def _chat_turn():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    file = data.get("file") if isinstance(data.get("file"), dict) else None
    has_file = bool(file and file.get("data"))
    if not message and not has_file:
        return jsonify({"error": "message is required"}), 400

    if "history" not in session:
        session["history"] = []
    if message:
        session["history"].append(message)
        session.modified = True

    result = answer_question(
        message=message,
        username=session.get("username"),
        history=session.get("history", []),
        file=file,
    )
    return jsonify(result)


# Both routes share the two agents: local first, API when it is active.
@app.route("/ask", methods=["POST"])
@app.route("/brain", methods=["POST"])
def ask():
    return _chat_turn()


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