"""API agent. Retrieves an answer when Gemini or Grok is configured and reachable."""

import logging
import os
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
XAI_CHAT_URL = "https://api.x.ai/v1/chat/completions"
REQUEST_TIMEOUT = 20
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
SELF_PATHS = {"/brain", "/ask", "/grok"}


class ApiAgent:
    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.gemini_url = os.getenv("API_BASE_URL")
        self.gemini_model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.xai_key = os.getenv("XAI_API_KEY")
        self.xai_model = os.getenv("XAI_MODEL", "grok-4.6")

    def is_configured(self):
        return bool(self._gemini_url() or self._xai_keys())

    def has_grok(self):
        return bool(self._xai_keys())

    def retrieve(self, message, history=None, file=None):
        """Return an API answer, or None when every configured provider is down."""
        if not self.is_configured():
            return None

        prompt = _with_history(message, history)
        has_file = bool(file and file.get("data"))

        if self._gemini_url():
            text = self._gemini(prompt, file)
            if text:
                return {"response": text, "source": "api", "provider": "gemini"}

        if not has_file:
            text = self._grok(prompt)
            if text:
                return {"response": text, "source": "api", "provider": "grok"}

        return None

    def grok_only(self, message):
        text = self._grok(message)
        if text:
            return {"response": text, "source": "api", "provider": "grok"}
        return None

    def _xai_keys(self):
        keys = []
        if self.xai_key:
            keys.append(self.xai_key)
        # An xAI key is sometimes stored in the Gemini variable by mistake.
        if self.gemini_key and self.gemini_key.startswith("xai-") and self.gemini_key not in keys:
            keys.append(self.gemini_key)
        return keys

    def _gemini_url(self):
        """External Gemini endpoint only. This app's own routes are not an API provider."""
        if self.gemini_url and not _is_self_url(self.gemini_url):
            if "key=" in self.gemini_url or not _is_google_key(self.gemini_key):
                return self.gemini_url
            joiner = "&" if "?" in self.gemini_url else "?"
            return f"{self.gemini_url}{joiner}key={self.gemini_key}"
        if _is_google_key(self.gemini_key):
            endpoint = GEMINI_ENDPOINT.format(model=self.gemini_model)
            return f"{endpoint}?key={self.gemini_key}"
        return None

    def _gemini(self, message, file=None):
        url = self._gemini_url()
        if not url:
            return None

        parts = [{"text": message}]
        if file and file.get("data") and file.get("mime_type"):
            parts.append({
                "inline_data": {
                    "mime_type": file["mime_type"],
                    "data": file["data"],
                }
            })

        payload = {
            "systemInstruction": {
                "parts": [{
                    "text": (
                        "You are e-Chat, an assistant created by Efatha Rutakaza. "
                        "Answer the user directly."
                    )
                }]
            },
            "contents": [{"role": "user", "parts": parts}],
        }

        try:
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            if not response.ok:
                logger.warning("Gemini request failed with status %s", response.status_code)
                return None
            return _gemini_text(response.json())
        except requests.RequestException as exc:
            logger.warning("Gemini request failed: %s", type(exc).__name__)
            return None

    def _grok(self, message):
        payload = {
            "model": self.xai_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are e-Chat, an assistant created by Efatha Rutakaza. "
                        "Answer the user directly."
                    ),
                },
                {"role": "user", "content": message},
            ],
        }
        for key in self._xai_keys():
            try:
                response = requests.post(
                    XAI_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                if not response.ok:
                    logger.warning("Grok request failed with status %s", response.status_code)
                    continue
                data = response.json()
                text = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                cleaned = _clean_text(text)
                if cleaned:
                    return cleaned
            except (requests.RequestException, IndexError, AttributeError) as exc:
                logger.warning("Grok request failed: %s", type(exc).__name__)
        return None


def _is_google_key(key):
    return bool(key) and key.startswith("AIza")


def _is_self_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").rstrip("/") or "/"
    return host in LOCAL_HOSTS or path in SELF_PATHS


def _gemini_text(data):
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
    return _clean_text(text)


def _with_history(message, history):
    prior = [str(item).strip() for item in (history or []) if str(item).strip()]
    if prior and prior[-1] == message:
        prior = prior[:-1]
    if not prior:
        return message
    earlier = "\n".join(prior[-4:])
    return f"Previous user messages:\n{earlier}\n\nQuestion: {message}"


def _clean_text(text):
    if not text:
        return None
    cleaned = text.replace("**", "").strip()
    return cleaned or None
