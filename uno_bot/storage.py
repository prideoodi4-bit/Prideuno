from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    private_chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    username TEXT
                );

                CREATE TABLE IF NOT EXISTS games (
                    code TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    thread_key INTEGER NOT NULL,
                    thread_id INTEGER,
                    creator_id INTEGER NOT NULL,
                    board_message_id INTEGER,
                    state_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_games_location
                ON games(chat_id, thread_key, active);
                """
            )

    def upsert_user(self, user_id: int, private_chat_id: int, name: str, username: str | None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, private_chat_id, name, username)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                  private_chat_id=excluded.private_chat_id,
                  name=excluded.name,
                  username=excluded.username
                """,
                (user_id, private_chat_id, name, username),
            )

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def create_game(
        self,
        code: str,
        chat_id: int,
        thread_id: int | None,
        creator_id: int,
        state: dict[str, Any],
    ) -> None:
        thread_key = thread_id if thread_id is not None else -1
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO games(code,chat_id,thread_key,thread_id,creator_id,state_json,active) VALUES(?,?,?,?,?,?,1)",
                (code, chat_id, thread_key, thread_id, creator_id, json.dumps(state, ensure_ascii=False)),
            )

    def get_active_at(self, chat_id: int, thread_id: int | None) -> dict[str, Any] | None:
        thread_key = thread_id if thread_id is not None else -1
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM games WHERE chat_id=? AND thread_key=? AND active=1 ORDER BY created_at DESC LIMIT 1",
                (chat_id, thread_key),
            ).fetchone()
            return self._decode(row)

    def get_game(self, code: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM games WHERE code=?", (code,)).fetchone()
            return self._decode(row)

    def save_state(self, code: str, state: dict[str, Any], active: bool | None = None) -> None:
        with self._lock, self._connect() as conn:
            if active is None:
                conn.execute(
                    "UPDATE games SET state_json=? WHERE code=?",
                    (json.dumps(state, ensure_ascii=False), code),
                )
            else:
                conn.execute(
                    "UPDATE games SET state_json=?, active=? WHERE code=?",
                    (json.dumps(state, ensure_ascii=False), 1 if active else 0, code),
                )

    def set_board_message(self, code: str, message_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE games SET board_message_id=? WHERE code=?", (message_id, code))

    def deactivate(self, code: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE games SET active=0 WHERE code=?", (code,))

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        data = dict(row)
        data["state"] = json.loads(data.pop("state_json"))
        return data
