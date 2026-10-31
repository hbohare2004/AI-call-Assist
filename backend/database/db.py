from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from services.config import DB_PATH
from services.summary_service import CallSummary


@contextmanager
def db_connect() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                summary TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                caller_name TEXT,
                caller_phone TEXT,
                reason_for_call TEXT,
                callback_requested TEXT,
                preferred_callback_time TEXT,
                urgency TEXT
            )
            """
        )
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(calls)").fetchall()
        }
        for column, column_type in (
            ("caller_name", "TEXT"),
            ("caller_phone", "TEXT"),
            ("reason_for_call", "TEXT"),
            ("callback_requested", "TEXT"),
            ("preferred_callback_time", "TEXT"),
            ("urgency", "TEXT"),
        ):
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE calls ADD COLUMN {column} {column_type}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS call_summaries (
                call_id TEXT PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
                caller_name TEXT NOT NULL,
                caller_phone TEXT NOT NULL,
                reason_for_call TEXT NOT NULL,
                callback_requested TEXT NOT NULL,
                preferred_callback_time TEXT NOT NULL,
                urgency TEXT NOT NULL,
                summary TEXT NOT NULL,
                transcript TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def insert_message(
    conn: sqlite3.Connection,
    call_id: str,
    role: str,
    content: str,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO messages (call_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (call_id, role, content, created_at),
    )


def _summary_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "caller_name": row["caller_name"],
        "caller_phone": row["caller_phone"],
        "reason_for_call": row["reason_for_call"],
        "callback_requested": row["callback_requested"],
        "preferred_callback_time": row["preferred_callback_time"],
        "urgency": row["urgency"],
        "summary": row["summary"],
        "transcript": row["transcript"],
        "created_at": row["created_at"],
    }


def update_call_summary(call_id: str, ended_at: str, summary: CallSummary) -> None:
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO call_summaries (
                call_id, caller_name, caller_phone, reason_for_call,
                callback_requested, preferred_callback_time, urgency,
                summary, transcript, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(call_id) DO UPDATE SET
                caller_name=excluded.caller_name,
                caller_phone=excluded.caller_phone,
                reason_for_call=excluded.reason_for_call,
                callback_requested=excluded.callback_requested,
                preferred_callback_time=excluded.preferred_callback_time,
                urgency=excluded.urgency,
                summary=excluded.summary,
                transcript=excluded.transcript,
                created_at=excluded.created_at
            """,
            (
                call_id,
                summary.caller_name,
                summary.caller_phone,
                summary.reason_for_call,
                summary.callback_requested,
                summary.preferred_callback_time,
                summary.urgency,
                summary.summary,
                summary.transcript,
                ended_at,
            ),
        )
        conn.execute(
            """
            UPDATE calls SET
                ended_at = ?, summary = ?, status = 'completed',
                caller_name = ?, caller_phone = ?, reason_for_call = ?,
                callback_requested = ?, preferred_callback_time = ?, urgency = ?
            WHERE id = ?
            """,
            (
                ended_at,
                summary.summary,
                summary.caller_name,
                summary.caller_phone,
                summary.reason_for_call,
                summary.callback_requested,
                summary.preferred_callback_time,
                summary.urgency,
                call_id,
            ),
        )


def get_call(call_id: str, include_messages: bool = False) -> dict | None:
    with db_connect() as conn:
        call = conn.execute(
            """
            SELECT id, started_at, ended_at, summary, status, caller_name,
                   caller_phone, reason_for_call, callback_requested,
                   preferred_callback_time, urgency
            FROM calls WHERE id = ?
            """,
            (call_id,),
        ).fetchone()
        if call is None:
            return None
        data = dict(call)
        summary_row = conn.execute(
            "SELECT * FROM call_summaries WHERE call_id = ?", (call_id,)
        ).fetchone()
        data["call_summary"] = _summary_dict(summary_row)
        if include_messages:
            messages = conn.execute(
                """
                SELECT role, content, created_at
                FROM messages WHERE call_id = ? ORDER BY id
                """,
                (call_id,),
            ).fetchall()
            data["messages"] = [dict(message) for message in messages]
        return data


def list_calls() -> list[dict]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, started_at, ended_at, summary, status, caller_name,
                   caller_phone, reason_for_call, callback_requested,
                   preferred_callback_time, urgency
            FROM calls ORDER BY started_at DESC LIMIT 100
            """
        ).fetchall()
    return [dict(row) for row in rows]
