"""Small, local conversation memory backed by Python's built-in SQLite."""

from contextlib import contextmanager
import re
import sqlite3
from pathlib import Path


_FACT = re.compile(
    r"(?:remember\s+that\s+)?my\s+(.{1,60}?)\s+is\s+(.{1,200}?)[.!]?$",
    re.IGNORECASE,
)
_FACT_QUESTION = re.compile(
    r"(?:(?:what|who)(?:'s|\s+is)|do\s+you\s+remember(?:\s+(?:what|who))?)"
    r"\s+my\s+(.{1,60}?)[?!.]*$",
    re.IGNORECASE,
)


class ConversationMemory:
    def __init__(self, path="e_chat_memory.sqlite3"):
        self.path = Path(path)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS messages_conversation
                ON messages(conversation_id, id)
                """
            )

    def add(self, conversation_id, role, content):
        text = str(content or "").strip()
        if not conversation_id or role not in {"user", "assistant"} or not text:
            return
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO messages(conversation_id, role, content)
                VALUES (?, ?, ?)
                """,
                (conversation_id, role, text[:20000]),
            )

    def recent(self, conversation_id, limit=20, role=None):
        if not conversation_id:
            return []
        parameters = [conversation_id]
        role_filter = ""
        if role in {"user", "assistant"}:
            role_filter = " AND role = ?"
            parameters.append(role)
        parameters.append(max(1, min(int(limit), 100)))
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT role, content, created_at
                FROM messages
                WHERE conversation_id = ?{role_filter}
                ORDER BY id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear(self, conversation_id):
        if not conversation_id:
            return
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )

    def recall(self, conversation_id, question):
        """Answer a direct question about a fact the user previously stated."""
        asked = _FACT_QUESTION.fullmatch(str(question or "").strip())
        if not asked:
            return None
        wanted = self._normalize_key(asked.group(1))
        messages = self.recent(conversation_id, limit=100, role="user")
        for item in reversed(messages):
            statement = _FACT.search(item["content"].strip())
            if not statement:
                continue
            key = self._normalize_key(statement.group(1))
            if key == wanted:
                value = statement.group(2).strip(" .!?")
                return f"You told me your {key} is {value}."
        return None

    @staticmethod
    def _normalize_key(value):
        return re.sub(r"\s+", " ", value.strip().lower())
