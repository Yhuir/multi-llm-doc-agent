"""Chat history persistence for TOC review."""

from __future__ import annotations

from typing import Any

from backend.models.enums import ChatRole
from backend.models.schemas import ChatMessage
from backend.repositories.db import SQLiteDB


class ChatMessageRepository:
    def __init__(self, db: SQLiteDB) -> None:
        self.db = db

    def create(self, message: ChatMessage) -> ChatMessage:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO chat_message (
                    message_id, task_id, role, content, related_toc_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.task_id,
                    message.role.value,
                    message.content,
                    message.related_toc_version,
                    message.created_at,
                ),
            )
        return message

    def list_by_task(self, task_id: str, limit: int = 200) -> list[ChatMessage]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chat_message
                WHERE task_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    @staticmethod
    def _row_to_message(row: Any) -> ChatMessage:
        return ChatMessage(
            message_id=row["message_id"],
            task_id=row["task_id"],
            role=ChatRole(row["role"]),
            content=row["content"],
            related_toc_version=row["related_toc_version"],
            created_at=row["created_at"],
        )
