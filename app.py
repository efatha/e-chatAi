from flask import Flask, render_template, request, jsonify
import os
import re
import threading
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


def _drive_file_id(link):
    text = (link or "").strip()
    if "/folders/" in text:
        return ""
    marker = "/file/d/"
    if marker in text:
        return text.split(marker, 1)[1].split("/", 1)[0].split("?", 1)[0]
    if "id=" in text:
        return text.split("id=", 1)[1].split("&", 1)[0]
    return ""


def _pdf_bytes(body):
    if not body:
        return None
    start = body.find(b"%PDF-")
    if start < 0 or start > 1024:
        return None
    return body[start:]


def _save_drive_pdf(session, file_id):
    """Download one Drive file. Large files need the usercontent confirm link."""
    url = "https://drive.usercontent.google.com/download"
    response = session.get(
        url,
        params={"id": file_id, "export": "download", "confirm": "t"},
        timeout=120,
    )
    response.raise_for_status()
    pdf = _pdf_bytes(response.content)
    if pdf:
        return pdf
    text = response.content.decode("utf-8", errors="ignore")
    confirm = re.search(r"confirm=([0-9A-Za-z_\-]+)", text)
    if not confirm:
        return None
    confirmed = session.get(
        url,
        params={"id": file_id, "export": "download", "confirm": confirm.group(1)},
        timeout=180,
    )
    confirmed.raise_for_status()
    return _pdf_bytes(confirmed.content)


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
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    for index, link in enumerate(raw, start=1):
        file_id = _drive_file_id(link)
        if not file_id:
            log.warning("Book link %s is a folder or not a Drive file link.", index)
            continue
        name = secure_filename(file_id) + ".pdf"
        try:
            body = _save_drive_pdf(session, file_id)
            if not body:
                log.warning(
                    "Book %s did not download. Set General access to Anyone with the link.",
                    index,
                )
                continue
            (BOOKS_DIR / name).write_bytes(body)
            saved += 1
            log.warning("Saved private book %s (%s bytes).", index, len(body))
        except Exception as exc:
            log.warning("Private book %s failed: %s", index, type(exc).__name__)
    if saved:
        book_agent().refresh()
        log.warning("Indexed %s private books.", saved)


threading.Thread(target=_fetch_private_books, daemon=True).start()

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