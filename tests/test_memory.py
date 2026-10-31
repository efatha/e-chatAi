import unittest
from unittest.mock import MagicMock, patch

from agents.memory import ConversationMemory


class ConversationMemoryConnectionTests(unittest.TestCase):
    def setUp(self):
        self.memory = ConversationMemory.__new__(ConversationMemory)
        self.connection = MagicMock()

    def test_connection_closes_after_successful_transaction(self):
        with patch.object(self.memory, "_connect", return_value=self.connection):
            with self.memory._connection() as connection:
                self.assertIs(connection, self.connection)

        self.connection.__enter__.assert_called_once_with()
        self.connection.__exit__.assert_called_once_with(None, None, None)
        self.connection.close.assert_called_once_with()

    def test_connection_closes_after_failed_transaction(self):
        with patch.object(self.memory, "_connect", return_value=self.connection):
            with self.assertRaisesRegex(RuntimeError, "database operation failed"):
                with self.memory._connection():
                    raise RuntimeError("database operation failed")

        self.connection.__exit__.assert_called_once()
        self.connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
