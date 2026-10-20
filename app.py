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


def _pdf_bytes(response):
    body = response.content or b""
    if "pdf" in response.headers.get("Content-Type", "").lower() and body[:5] == b"%PDF-":
        return body
    start = body.find(b"%PDF-")
    if 0 <= start <= 2048:
        return body[start:]
    return None


def _confirm_download(session, response):
    text = response.content.decode("utf-8", errors="ignore")
    action = re.search(r'action="([^"]+)"', text)
    names = re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', text)
    if not names:
        names = [(name, value) for value, name in re.findall(r'value="([^"]*)"[^>]*name="([^"]+)"', text)]
    if not action or not names:
        return None
    confirmed = session.get(
        action.group(1).replace("&amp;", "&"),
        params=dict(names),
        timeout=180,
    )
    confirmed.raise_for_status()
    return _pdf_bytes(confirmed)


def _save_drive_pdf(session, file_id):
    """Anyone-with-the-link file. Large files need the confirm form, not the warning page."""
    urls = [
        f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t",
        f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t",
    ]
    for url in urls:
        response = session.get(url, timeout=180)
        response.raise_for_status()
        pdf = _pdf_bytes(response)
        if pdf:
            return pdf
        pdf = _confirm_download(session, response)
        if pdf:
            return pdf
    return None


def _fetch_private_books():
    """Download every BOOK_URLS file in the background. The site opens first."""
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
        path = BOOKS_DIR / (secure_filename(f"book-{index}") + ".pdf")
        if path.is_file() and path.stat().st_size > 1000:
            saved += 1
            continue
        try:
            body = _save_drive_pdf(session, file_id)
            if not body:
                log.warning("Book %s was not a PDF. Share the file as Anyone with the link.", index)
                continue
            path.write_bytes(body)
            saved += 1
            log.warning("Saved Drive book %s (%s bytes).", index, len(body))
        except Exception as exc:
            log.warning("Drive book %s failed: %s", index, type(exc).__name__)
    if saved:
        book_agent().refresh()
        log.warning("Indexed %s Drive books.", saved)


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