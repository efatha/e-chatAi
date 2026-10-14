from flask import Flask, render_template, request, jsonify
import os
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env
import json
from flask import session

from agents.router import answer_question, api_agent, book_agent, configure
from agents.book_agent import BOOKS_DIR

# Load the data.json file
with open("data.json", "r", encoding="utf-8") as f:
    DATA = json.load(f)

configure(DATA.get("trained_knowledge", []), DATA.get("word_meanings", {}))


def _drive_download_url(link):
    """Turn a Drive file link into a direct download. A folder link cannot be read."""
    text = (link or "").strip()
    marker = "/file/d/"
    if marker in text:
        file_id = text.split(marker, 1)[1].split("/", 1)[0]
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    if "id=" in text:
        return text
    return text


def _fetch_private_books():
    """Download PDFs from BOOK_URLS. The links stay in Render, not in git."""
    raw = os.getenv("BOOK_URLS", "").replace(",", " ").split()
    if not raw:
        return
    import logging
    import requests
    from werkzeug.utils import secure_filename

    log = logging.getLogger(__name__)
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for index, link in enumerate(raw, start=1):
        if "/folders/" in link:
            log.warning("Skipped a Google Drive folder link. Paste one link per PDF.")
            continue
        url = _drive_download_url(link)
        name = secure_filename(link.split("?")[0].rstrip("/").split("/")[-1])
        if not name.lower().endswith(".pdf"):
            name = f"book-{index}.pdf"
        try:
            response = requests.get(url, timeout=45)
            response.raise_for_status()
            body = response.content
            if body[:5] != b"%PDF-":
                log.warning("Drive did not return a PDF for book %s. Share the file as anyone with the link.", index)
                continue
            (BOOKS_DIR / name).write_bytes(body)
            saved += 1
        except Exception as exc:
            log.warning("Private book download failed: %s", type(exc).__name__)
    if saved:
        book_agent().refresh()


_fetch_private_books()

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